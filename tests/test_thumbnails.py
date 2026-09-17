from __future__ import annotations

import io
import threading
from pathlib import Path

from PIL import Image

from fotozeef.core.thumbnails import (
    FILMSTRIP_SIZE,
    ThumbnailCache,
    ThumbnailRequest,
    ThumbnailWorker,
    cache_key,
    render,
    render_full,
)


def _request(path: Path, target: int = FILMSTRIP_SIZE, photo_id: int = 1) -> ThumbnailRequest:
    stat = path.stat()
    return ThumbnailRequest(
        photo_id=photo_id,
        path=path,
        mtime=stat.st_mtime,
        file_size=stat.st_size,
        target=target,
    )


def test_cache_key_changes_with_every_input(tmp_path: Path) -> None:
    path = tmp_path / "a.jpg"
    base = cache_key(path, 1.0, 10, 200)

    assert base != cache_key(path, 2.0, 10, 200)
    assert base != cache_key(path, 1.0, 11, 200)
    assert base != cache_key(path, 1.0, 10, 2048)
    assert base != cache_key(tmp_path / "b.jpg", 1.0, 10, 200)


def test_render_fits_the_long_edge(tmp_path: Path, jpeg_factory) -> None:
    path = jpeg_factory(tmp_path / "a.jpg", size=(1000, 500))

    payload = render(_request(path))

    with Image.open(io.BytesIO(payload)) as image:
        assert max(image.size) == FILMSTRIP_SIZE
        assert image.format == "JPEG"


def test_render_applies_exif_orientation(tmp_path: Path) -> None:
    path = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (200, 100), (10, 20, 30))
    exif = image.getexif()
    exif[274] = 6
    image.save(path, format="JPEG", exif=exif)

    payload = render(_request(path))

    with Image.open(io.BytesIO(payload)) as thumbnail:
        assert thumbnail.height > thumbnail.width


def test_cache_reuses_stored_thumbnail(tmp_path: Path, jpeg_factory) -> None:
    path = jpeg_factory(tmp_path / "a.jpg")
    cache = ThumbnailCache(tmp_path / "cache")
    request = _request(path)

    first = cache.get_or_create(request)
    assert cache.lookup(request) == first

    second = cache.get_or_create(request)
    assert second == first


def test_worker_reports_ready_thumbnails(tmp_path: Path, jpeg_factory) -> None:
    paths = [jpeg_factory(tmp_path / f"{index}.jpg") for index in range(6)]
    cache = ThumbnailCache(tmp_path / "cache")
    done = threading.Event()
    ready: list[int] = []

    def on_ready(request: ThumbnailRequest, _path: Path) -> None:
        ready.append(request.photo_id)
        if len(ready) == len(paths):
            done.set()

    worker = ThumbnailWorker(cache, max_workers=2, on_ready=on_ready)
    worker.set_positions({index: index for index in range(len(paths))})
    for index, path in enumerate(paths):
        worker.submit(_request(path, photo_id=index))

    assert done.wait(30)
    worker.shutdown()
    assert sorted(ready) == list(range(len(paths)))


def test_worker_returns_cached_path_without_queueing(tmp_path: Path, jpeg_factory) -> None:
    path = jpeg_factory(tmp_path / "a.jpg")
    cache = ThumbnailCache(tmp_path / "cache")
    request = _request(path)
    cache.get_or_create(request)

    worker = ThumbnailWorker(cache, max_workers=1)
    result = worker.submit(request)
    worker.shutdown()

    assert result is not None


def test_worker_reports_failures(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"nope")
    cache = ThumbnailCache(tmp_path / "cache")
    failed = threading.Event()

    worker = ThumbnailWorker(cache, max_workers=1, on_failed=lambda _request, _error: failed.set())
    worker.submit(_request(broken))

    assert failed.wait(30)
    worker.shutdown()


def test_render_full_keeps_the_original_resolution(tmp_path: Path, jpeg_factory) -> None:
    path = jpeg_factory(tmp_path / "big.jpg", size=(1600, 900))

    payload, width, height = render_full(path)

    assert (width, height) == (1600, 900)
    assert len(payload) == width * height * 3


def test_render_full_applies_orientation(tmp_path: Path) -> None:
    path = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (400, 200), (10, 20, 30))
    exif = image.getexif()
    exif[274] = 6
    image.save(path, format="JPEG", exif=exif)

    _payload, width, height = render_full(path)

    assert (width, height) == (200, 400)
