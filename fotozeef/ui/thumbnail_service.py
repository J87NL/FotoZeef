from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

from fotozeef.core.models import TimelineEntry
from fotozeef.core.thumbnails import (
    FILMSTRIP_SIZE,
    PREVIEW_SIZE,
    ThumbnailCache,
    ThumbnailRequest,
    ThumbnailWorker,
)

_FILMSTRIP_CACHE_ENTRIES = 900
_PREVIEW_CACHE_ENTRIES = 16


class ThumbnailService(QObject):
    """Bridges the headless thumbnail worker onto the Qt event loop."""

    ready = Signal(int, int)
    failed = Signal(int, int, str)

    def __init__(
        self,
        cache: ThumbnailCache,
        scale: float = 1.0,
        max_workers: int = 4,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._scale = max(1.0, scale)
        self._paths: dict[tuple[int, int], Path] = {}
        self._pixmaps: OrderedDict[tuple[int, int], QPixmap] = OrderedDict()
        self._worker = ThumbnailWorker(
            cache,
            max_workers=max_workers,
            on_ready=self._on_ready,
            on_failed=self._on_failed,
        )

    @property
    def filmstrip_target(self) -> int:
        return int(FILMSTRIP_SIZE * self._scale)

    @property
    def preview_target(self) -> int:
        return int(PREVIEW_SIZE * self._scale)

    def set_positions(self, positions: dict[int, int]) -> None:
        self._worker.set_positions(positions)

    def set_cursor(self, index: int) -> None:
        self._worker.set_cursor(index)

    def clear(self) -> None:
        self._worker.drop_pending()
        self._paths.clear()
        self._pixmaps.clear()

    def shutdown(self) -> None:
        self._worker.shutdown()

    def pixmap(self, entry: TimelineEntry, target: int) -> QPixmap | None:
        key = (entry.photo.id, target)
        cached = self._pixmaps.get(key)
        if cached is not None:
            self._pixmaps.move_to_end(key)
            return cached
        path = self._paths.get(key)
        if path is None:
            path = self._worker.submit(self._request(entry, target))
            if path is None:
                return None
            self._paths[key] = path
        return self._load(key, path)

    def request(self, entry: TimelineEntry, target: int) -> None:
        key = (entry.photo.id, target)
        if key in self._pixmaps or key in self._paths:
            return
        path = self._worker.submit(self._request(entry, target))
        if path is not None:
            self._paths[key] = path
            self.ready.emit(entry.photo.id, target)

    def _request(self, entry: TimelineEntry, target: int) -> ThumbnailRequest:
        return ThumbnailRequest(
            photo_id=entry.photo.id,
            path=entry.absolute_path,
            mtime=entry.photo.mtime,
            file_size=entry.photo.file_size,
            target=target,
            orientation=entry.photo.orientation,
        )

    def _load(self, key: tuple[int, int], path: Path) -> QPixmap | None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return None
        pixmap.setDevicePixelRatio(self._scale)
        self._pixmaps[key] = pixmap
        self._pixmaps.move_to_end(key)
        self._trim(key[1])
        return pixmap

    def _trim(self, target: int) -> None:
        is_preview = target >= self.preview_target
        limit = _PREVIEW_CACHE_ENTRIES if is_preview else _FILMSTRIP_CACHE_ENTRIES
        same_target = [key for key in self._pixmaps if key[1] == target]
        while len(same_target) > limit:
            self._pixmaps.pop(same_target.pop(0), None)

    def _on_ready(self, request: ThumbnailRequest, path: Path) -> None:
        self._paths[(request.photo_id, request.target)] = path
        self.ready.emit(request.photo_id, request.target)

    def _on_failed(self, request: ThumbnailRequest, error: Exception) -> None:
        self.failed.emit(request.photo_id, request.target, str(error))
