from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QKeyEvent, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QVBoxLayout,
    QWidget,
)

from fotozeef.core.models import TimelineEntry
from fotozeef.ui.filmstrip import SELECTED_ROLE, FilmstripDelegate, FilmstripModel

GRID_SPACING = 4
TILE_WIDTHS = (100, 130, 160, 210, 270, 340, 420)
"""Tile widths per zoom step; tiles are 4:3 landscape."""
DEFAULT_ZOOM = 2

PixmapProvider = Callable[[TimelineEntry, QSize], QPixmap | None]


def tile_size(zoom: int) -> QSize:
    width = TILE_WIDTHS[min(max(zoom, 0), len(TILE_WIDTHS) - 1)]
    return QSize(width, round(width * 0.8))


class SelectedOnly(QSortFilterProxyModel):
    """Every photo, or with the filter on only the selected ones."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._only_selected = False
        self.setDynamicSortFilter(True)

    def set_only_selected(self, only: bool) -> None:
        if only == self._only_selected:
            return
        if hasattr(self, "beginFilterChange"):  # Qt 6.10 and later
            self.beginFilterChange()
            self._only_selected = only
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self._only_selected = only
            self.invalidateRowsFilter()

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if not self._only_selected:
            return True
        model = self.sourceModel()
        return bool(model.data(model.index(source_row, 0, source_parent), SELECTED_ROLE))


class OverviewGrid(QListView):
    """All thumbnails at once, wrapping to the window width."""

    open_requested = Signal(int)
    toggle_requested = Signal(int)
    close_requested = Signal()
    zoom_requested = Signal(int)
    """+1 for larger tiles, -1 for smaller ones (Ctrl and the mouse wheel)."""

    def __init__(
        self,
        model: SelectedOnly,
        parent: QWidget | None = None,
        pixmap: PixmapProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self.setModel(model)
        self._provider = pixmap
        self._delegate = FilmstripDelegate(
            self, tile_size(DEFAULT_ZOOM), self._pixmap if pixmap else None
        )
        self.setItemDelegate(self._delegate)
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setSpacing(GRID_SPACING)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setStyleSheet("QListView { background: #1c1c1e; border: none; }")
        # One click opens; Enter is handled in keyPressEvent. `activated` would fire
        # a second time on platforms where a single click activates.
        self.clicked.connect(self._open)

    def set_tile_size(self, size: QSize) -> None:
        """Re-lays the grid at a new tile size, keeping the current photo in view."""
        self._delegate.set_size(size)
        self.scheduleDelayedItemsLayout()
        self.viewport().update()
        # The new layout is only there once the event loop has run.
        QTimer.singleShot(0, self._center_current)

    def _center_current(self) -> None:
        if self.currentIndex().isValid():
            self.scrollTo(self.currentIndex(), QListView.ScrollHint.PositionAtCenter)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_requested.emit(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)

    def _pixmap(self, index: QModelIndex | QPersistentModelIndex, size: QSize) -> QPixmap | None:
        model = self.model()
        assert isinstance(model, SelectedOnly)
        source = model.sourceModel()
        assert isinstance(source, FilmstripModel) and self._provider is not None
        entry = source.entry(model.mapToSource(model.index(index.row(), 0)).row())
        return self._provider(entry, size) if entry is not None else None

    def source_row(self, index: QModelIndex | QPersistentModelIndex) -> int:
        model = self.model()
        assert isinstance(model, SelectedOnly)
        return model.mapToSource(model.index(index.row(), 0)).row()

    def show_row(self, source_row: int) -> None:
        """Makes the photo at this timeline row current and scrolls it into the middle."""
        model = self.model()
        assert isinstance(model, SelectedOnly)
        source = model.sourceModel()
        index = model.mapFromSource(source.index(source_row, 0))
        if not index.isValid():
            if model.rowCount() == 0:
                return
            index = model.index(0, 0)
        self.setCurrentIndex(index)
        self.scrollTo(index, QListView.ScrollHint.PositionAtCenter)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        current = self.currentIndex()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and current.isValid():
            self.open_requested.emit(self.source_row(current))
        elif key == Qt.Key.Key_Space and current.isValid():
            self.toggle_requested.emit(self.source_row(current))
        elif key == Qt.Key.Key_Escape:
            self.close_requested.emit()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def _open(self, index: QModelIndex) -> None:
        if index.isValid():
            self.open_requested.emit(self.source_row(index))


class OverviewPage(QWidget):
    """The grid with a short header: how many photos, and the selected-only filter."""

    zoom_changed = Signal(int)

    def __init__(
        self,
        model: FilmstripModel,
        parent: QWidget | None = None,
        pixmap: PixmapProvider | None = None,
        zoom: int = DEFAULT_ZOOM,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._proxy = SelectedOnly(self)
        self._proxy.setSourceModel(model)
        self.grid = OverviewGrid(self._proxy, self, pixmap)
        self.grid.zoom_requested.connect(self.zoom_by)
        self._zoom = DEFAULT_ZOOM
        self.set_zoom(zoom)

        self._summary = QLabel(self)
        self._only_selected = QCheckBox(self.tr("Only selected photos"), self)
        # Keyboard focus stays in the grid, so Space keeps selecting photos.
        self._only_selected.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._only_selected.toggled.connect(self._filter)
        self._hint = QLabel(self)
        self._hint.setStyleSheet("color: #8e8e96;")

        header = QHBoxLayout()
        header.setContentsMargins(12, 8, 12, 4)
        header.addWidget(self._summary)
        header.addSpacing(16)
        header.addWidget(self._only_selected)
        header.addStretch(1)
        header.addWidget(self._hint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.grid, 1)
        self.retranslate()

    @property
    def zoom(self) -> int:
        return self._zoom

    def set_zoom(self, zoom: int) -> None:
        self._zoom = min(max(zoom, 0), len(TILE_WIDTHS) - 1)
        self.grid.set_tile_size(tile_size(self._zoom))
        self.zoom_changed.emit(self._zoom)

    def zoom_by(self, steps: int) -> None:
        self.set_zoom(self._zoom + steps)

    @property
    def only_selected(self) -> bool:
        return self._only_selected.isChecked()

    def set_only_selected(self, only: bool) -> None:
        self._only_selected.setChecked(only)

    def update_summary(self, total: int, selected: int) -> None:
        self._summary.setText(self.tr("{0} photos, {1} selected").format(total, selected))

    def retranslate(self) -> None:
        self._only_selected.setText(self.tr("Only selected photos"))
        self._hint.setText(
            self.tr(
                "Click or Enter opens a photo · Space selects · Ctrl+scroll or Ctrl +/- zooms"
                " · G or Esc returns"
            )
        )

    def _filter(self, only: bool) -> None:
        current = self.grid.currentIndex()
        row = self.grid.source_row(current) if current.isValid() else 0
        self._proxy.set_only_selected(only)
        self.grid.show_row(row)
        self.grid.setFocus()
