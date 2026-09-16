from __future__ import annotations

import hashlib
import io
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from fotozeef.core.imaging import register_codecs
from fotozeef.core.scanner import RAW_EXTENSIONS

FILMSTRIP_SIZE = 200
PREVIEW_SIZE = 2048
JPEG_QUALITY = 85


class ThumbnailSize(IntEnum):
    FILMSTRIP = FILMSTRIP_SIZE
    PREVIEW = PREVIEW_SIZE


@dataclass(frozen=True, slots=True)
class ThumbnailRequest:
    photo_id: int
    path: Path
    mtime: float
    file_size: int
    target: int
    orientation: int = 1


def cache_key(path: Path, mtime: float, file_size: int, target: int) -> str:
    digest = hashlib.sha256()
    digest.update(str(path).encode("utf-8", "surrogateescape"))
    digest.update(f"|{mtime!r}|{file_size}|{target}".encode())
    return digest.hexdigest()


class ThumbnailCache:
    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, request: ThumbnailRequest) -> Path:
        key = cache_key(request.path, request.mtime, request.file_size, request.target)
        return self._root / key[:2] / f"{key}.jpg"

    def lookup(self, request: ThumbnailRequest) -> Path | None:
        target = self.path_for(request)
        if target.is_file():
            return target
        return None

    def store(self, request: ThumbnailRequest, payload: bytes) -> Path:
        target = self.path_for(request)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(payload)
        temporary.replace(target)
        return target

    def get_or_create(self, request: ThumbnailRequest) -> Path:
        existing = self.lookup(request)
        if existing is not None:
            return existing
        return self.store(request, render(request))

    def clear(self) -> None:
        if not self._root.is_dir():
            return
        for child in self._root.rglob("*.jpg"):
            child.unlink(missing_ok=True)


def render(request: ThumbnailRequest) -> bytes:
    register_codecs()
    from PIL import Image, ImageOps

    source = _open_for_thumbnail(request)
    with source:
        image = ImageOps.exif_transpose(source) or source
        image = image.convert("RGB")
        image.thumbnail((request.target, request.target), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def _open_for_thumbnail(request: ThumbnailRequest):  # noqa: ANN202
    from PIL import Image

    if request.path.suffix.lower() in RAW_EXTENSIONS:
        return _open_raw_preview(request.path)
    image = Image.open(request.path)
    if image.format == "JPEG":
        image.draft("RGB", (request.target, request.target))
    return image


def _open_raw_preview(path: Path):  # noqa: ANN202
    import rawpy
    from PIL import Image

    with rawpy.imread(str(path)) as raw:
        thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            return Image.open(io.BytesIO(thumb.data))
        return Image.fromarray(thumb.data)


class ThumbnailWorker:
    """Bounded pool that always renders the requests closest to the cursor first."""

    def __init__(
        self,
        cache: ThumbnailCache,
        max_workers: int = 4,
        on_ready: Callable[[ThumbnailRequest, Path], None] | None = None,
        on_failed: Callable[[ThumbnailRequest, Exception], None] | None = None,
    ) -> None:
        self._cache = cache
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="thumb")
        self._on_ready = on_ready
        self._on_failed = on_failed
        self._lock = threading.Lock()
        self._pending: dict[tuple[int, int], ThumbnailRequest] = {}
        self._inflight: set[tuple[int, int]] = set()
        self._positions: dict[int, int] = {}
        self._cursor = 0
        self._closed = False
        self._max_workers = max_workers

    def set_positions(self, positions: dict[int, int]) -> None:
        with self._lock:
            self._positions = positions

    def set_cursor(self, index: int) -> None:
        with self._lock:
            self._cursor = index
        self._pump()

    def submit(self, request: ThumbnailRequest) -> Path | None:
        cached = self._cache.lookup(request)
        if cached is not None:
            return cached
        key = (request.photo_id, request.target)
        with self._lock:
            if self._closed or key in self._inflight or key in self._pending:
                return None
            self._pending[key] = request
        self._pump()
        return None

    def drop_pending(self) -> None:
        with self._lock:
            self._pending.clear()

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            self._pending.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _pump(self) -> None:
        while True:
            with self._lock:
                if self._closed or not self._pending:
                    return
                if len(self._inflight) >= self._max_workers:
                    return
                key = min(self._pending, key=self._priority)
                request = self._pending.pop(key)
                self._inflight.add(key)
            future = self._executor.submit(self._run, request)
            future.add_done_callback(lambda _f, k=key: self._finish(k))

    def _priority(self, key: tuple[int, int]) -> tuple[int, int]:
        photo_id, target = key
        position = self._positions.get(photo_id)
        distance = abs(position - self._cursor) if position is not None else 1_000_000
        return (distance, target)

    def _run(self, request: ThumbnailRequest) -> None:
        try:
            path = self._cache.get_or_create(request)
        except Exception as error:
            if self._on_failed is not None:
                self._on_failed(request, error)
            return
        if self._on_ready is not None:
            self._on_ready(request, path)

    def _finish(self, key: tuple[int, int]) -> None:
        with self._lock:
            self._inflight.discard(key)
        self._pump()
