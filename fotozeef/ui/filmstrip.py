from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from fotozeef.core.models import TimelineEntry
from fotozeef.ui.painting import MISSING_OVERLAY, draw_estimated_marker, draw_star
from fotozeef.ui.thumbnail_service import ThumbnailService

THUMBNAIL_ROLE = int(Qt.ItemDataRole.UserRole) + 1
SELECTED_ROLE = THUMBNAIL_ROLE + 1
MISSING_ROLE = THUMBNAIL_ROLE + 2
ESTIMATED_ROLE = THUMBNAIL_ROLE + 3

ITEM_WIDTH = 150
ITEM_HEIGHT = 120
ITEM_PADDING = 6


class FilmstripModel(QAbstractListModel):
    def __init__(self, service: ThumbnailService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._entries: tuple[TimelineEntry, ...] = ()
        self._selected: set[int] = set()
        self._rows_by_photo: dict[int, int] = {}

    def set_entries(self, entries: Sequence[TimelineEntry]) -> None:
        self.beginResetModel()
        self._entries = tuple(entries)
        self._rows_by_photo = {entry.photo.id: row for row, entry in enumerate(self._entries)}
        self.endResetModel()

    def set_selected(self, selected: set[int]) -> None:
        self.beginResetModel()
        self._selected = set(selected)
        self.endResetModel()

    def mark_selected(self, photo_id: int, selected: bool) -> None:
        if selected:
            self._selected.add(photo_id)
        else:
            self._selected.discard(photo_id)
        self.refresh_photo(photo_id)

    def refresh_photo(self, photo_id: int) -> None:
        row = self._rows_by_photo.get(photo_id)
        if row is None:
            return
        index = self.index(row, 0)
        self.dataChanged.emit(index, index)

    def entry(self, row: int) -> TimelineEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        if parent.isValid():
            return 0
        return len(self._entries)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object:
        entry = self.entry(index.row())
        if entry is None:
            return None
        if role == THUMBNAIL_ROLE:
            return self._service.pixmap(entry, self._service.filmstrip_target)
        if role == SELECTED_ROLE:
            return entry.photo.id in self._selected
        if role == MISSING_ROLE:
            return entry.photo.missing
        if role == ESTIMATED_ROLE:
            return entry.is_estimated_time
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return f"{entry.photo.filename}\n{entry.source.label}"
        return None


class FilmstripDelegate(QStyledItemDelegate):
    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return QSize(ITEM_WIDTH, ITEM_HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        rect = option.rect.adjusted(ITEM_PADDING, ITEM_PADDING, -ITEM_PADDING, -ITEM_PADDING)
        painter.save()
        painter.fillRect(option.rect, QColor(28, 28, 30))

        pixmap = index.data(THUMBNAIL_ROLE)
        if pixmap is None:
            painter.fillRect(rect, QColor(48, 48, 52))
        else:
            scaled = pixmap.scaled(
                rect.size() * pixmap.devicePixelRatio(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            ratio = pixmap.devicePixelRatio()
            scaled.setDevicePixelRatio(ratio)
            target = QRect(0, 0, int(scaled.width() / ratio), int(scaled.height() / ratio))
            target.moveCenter(rect.center())
            painter.drawPixmap(target, scaled)
            rect = target

        if index.data(MISSING_ROLE):
            painter.fillRect(rect, MISSING_OVERLAY)

        if index.data(ESTIMATED_ROLE):
            marker = QRectF(rect.left() + 4, rect.bottom() - 16, 12, 12)
            draw_estimated_marker(painter, marker)

        if index.data(SELECTED_ROLE):
            draw_star(painter, QPointF(rect.right() - 12, rect.top() + 12), 9.0)

        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QPen(QColor(240, 240, 245), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
        painter.restore()


class Filmstrip(QListView):
    cursor_moved = Signal(int)

    def __init__(self, model: FilmstripModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setModel(model)
        self.setItemDelegate(FilmstripDelegate(self))
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(64)
        self.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(ITEM_HEIGHT + self.horizontalScrollBar().sizeHint().height() + 4)
        self.setStyleSheet("QListView { background: #1c1c1e; border: none; }")
        self.selectionModel().currentChanged.connect(self._on_current_changed)

    def set_cursor(self, row: int) -> None:
        model = self.model()
        if model is None or model.rowCount() == 0:
            return
        index = model.index(min(max(row, 0), model.rowCount() - 1), 0)
        if index == self.currentIndex():
            return
        self.setCurrentIndex(index)
        self.scrollTo(index, QListView.ScrollHint.PositionAtCenter)

    def _on_current_changed(
        self,
        current: QModelIndex | QPersistentModelIndex,
        _previous: QModelIndex | QPersistentModelIndex,
    ) -> None:
        if current.isValid():
            self.scrollTo(current, QListView.ScrollHint.PositionAtCenter)
            self.cursor_moved.emit(current.row())
