from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from fotozeef.core.models import TimelineEntry
from fotozeef.ui.painting import draw_star

BACKGROUND = QColor(18, 18, 20)
CAPTION = QColor(215, 215, 220)
CAPTION_DIM = QColor(150, 150, 158)
HINT_BACKGROUND = QColor(0, 0, 0, 170)

CAPTION_HEIGHT = 34
FIT = 1.0
MAX_ZOOM = 16.0
ZOOM_STEP = 1.25


class Viewer(QWidget):
    zoom_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entry: TimelineEntry | None = None
        self._pixmap: QPixmap | None = None
        self._selected = False
        self._message: str | None = None
        self._hint: str | None = None
        self._placeholder = self.tr("Open or create a project to start culling")
        self._zoom = FIT
        self._pan = QPointF(0.0, 0.0)
        self._drag_from: QPoint | None = None
        self._natural_width = 0
        self.setMinimumSize(320, 240)
        self.setAutoFillBackground(True)
        self.setMouseTracking(True)

    def show_entry(
        self,
        entry: TimelineEntry | None,
        pixmap: QPixmap | None,
        selected: bool,
        natural_width: int = 0,
    ) -> None:
        changed = entry is None or self._entry is None or entry.photo.id != self._entry.photo.id
        self._entry = entry
        self._pixmap = pixmap
        self._selected = selected
        self._message = None
        self._natural_width = natural_width
        if changed:
            self._pan = QPointF(0.0, 0.0)
        self.update()

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def zoomed(self) -> bool:
        return self._zoom > FIT + 1e-6

    def set_zoom(self, zoom: float, anchor: QPoint | None = None) -> None:
        clamped = min(max(zoom, FIT), MAX_ZOOM)
        if abs(clamped - self._zoom) < 1e-6:
            return
        if anchor is not None and self._zoom > 0:
            offset = QPointF(anchor) - QPointF(self.rect().center())
            factor = clamped / self._zoom
            self._pan = (self._pan - offset) * factor + offset
        self._zoom = clamped
        if not self.zoomed:
            self._pan = QPointF(0.0, 0.0)
        self._clamp_pan()
        self.zoom_changed.emit(self._zoom)
        self.update()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / ZOOM_STEP)

    def zoom_to_fit(self) -> None:
        self.set_zoom(FIT)

    def zoom_to_actual_size(self) -> None:
        """One image pixel per screen pixel, as far as the loaded image allows."""
        fitted = self._fitted_width()
        if not fitted or not self._natural_width:
            self.set_zoom(2.0)
            return
        self.set_zoom(self._natural_width / fitted)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._entry is None:
            return
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        self.set_zoom(self._zoom * (ZOOM_STEP**steps), event.position().toPoint())
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.zoomed:
            self._drag_from = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_from is None:
            return
        delta = event.position().toPoint() - self._drag_from
        self._drag_from = event.position().toPoint()
        self._pan += QPointF(delta)
        self._clamp_pan()
        self.update()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._drag_from = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self.zoomed:
            self.zoom_to_fit()
            return
        self.set_zoom(2.0, event.position().toPoint())

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def show_hint(self, text: str | None) -> None:
        self._hint = text
        self.update()

    def show_message(self, text: str) -> None:
        self._message = text
        self.update()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)

        if self._entry is None:
            self._draw_placeholder(painter)
            painter.end()
            return

        caption_height = CAPTION_HEIGHT
        canvas = self._canvas()
        if self._message is not None:
            self._draw_centered_text(painter, canvas, self._message, CAPTION_DIM)
        elif self._pixmap is None or self._pixmap.isNull():
            self._draw_centered_text(painter, canvas, self.tr("Loading…"), CAPTION_DIM)
        else:
            target = self._draw_pixmap(painter, canvas)
            if self._selected:
                draw_star(painter, QPointF(target.right() - 20, target.top() + 20), 14.0)

        self._draw_caption(painter, caption_height)
        self._draw_hint(painter)
        painter.end()

    def _draw_pixmap(self, painter: QPainter, canvas: QRect) -> QRect:
        pixmap = self._pixmap
        assert pixmap is not None
        target = self._target_rect(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.save()
        painter.setClipRect(canvas)
        painter.drawPixmap(target, pixmap)
        painter.restore()
        return target.intersected(canvas)

    def _target_rect(self, canvas: QRect) -> QRect:
        pixmap = self._pixmap
        if pixmap is None:
            return canvas
        ratio = pixmap.devicePixelRatio()
        width = pixmap.width() / ratio
        height = pixmap.height() / ratio
        if not width or not height:
            return canvas
        scale = min(canvas.width() / width, canvas.height() / height) * self._zoom
        size_w = max(1, round(width * scale))
        size_h = max(1, round(height * scale))
        target = QRect(0, 0, size_w, size_h)
        target.moveCenter(canvas.center() + self._pan.toPoint())
        return target

    def _fitted_width(self) -> float:
        pixmap = self._pixmap
        if pixmap is None:
            return 0.0
        canvas = self._canvas()
        ratio = pixmap.devicePixelRatio()
        width = pixmap.width() / ratio
        height = pixmap.height() / ratio
        if not width or not height:
            return 0.0
        return width * min(canvas.width() / width, canvas.height() / height)

    def _canvas(self) -> QRect:
        return self.rect().adjusted(12, 12, -12, -(CAPTION_HEIGHT + 12))

    def _clamp_pan(self) -> None:
        if not self.zoomed or self._pixmap is None:
            self._pan = QPointF(0.0, 0.0)
            return
        canvas = self._canvas()
        target = self._target_rect(canvas)
        limit_x = max(0.0, (target.width() - canvas.width()) / 2)
        limit_y = max(0.0, (target.height() - canvas.height()) / 2)
        self._pan = QPointF(
            min(max(self._pan.x(), -limit_x), limit_x),
            min(max(self._pan.y(), -limit_y), limit_y),
        )

    def _draw_hint(self, painter: QPainter) -> None:
        if self._hint is None:
            return
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(self._hint) + 28
        height = metrics.height() + 16
        box = QRect(int((self.width() - width) / 2), 24, width, height)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(HINT_BACKGROUND)
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(CAPTION)
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), self._hint)

    def _draw_caption(self, painter: QPainter, height: int) -> None:
        entry = self._entry
        if entry is None:
            return
        rect = QRect(12, self.height() - height, self.width() - 24, height)
        font = QFont(self.font())
        font.setPointSizeF(max(9.0, font.pointSizeF()))
        painter.setFont(font)
        painter.setPen(CAPTION)
        painter.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            entry.photo.filename,
        )
        painter.setPen(CAPTION_DIM)
        painter.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            self._detail_text(entry),
        )

    def _detail_text(self, entry: TimelineEntry) -> str:
        parts = [entry.source.label]
        moment = entry.effective_at.strftime("%Y-%m-%d %H:%M:%S")
        parts.append(f"{moment}~" if entry.is_estimated_time else moment)
        if entry.photo.missing:
            parts.append(self.tr("missing"))
        return "   ".join(parts)

    def _draw_placeholder(self, painter: QPainter) -> None:
        self._draw_centered_text(painter, self.rect(), self._placeholder, CAPTION_DIM)

    def _draw_centered_text(self, painter: QPainter, rect: QRect, text: str, color: QColor) -> None:
        painter.setPen(color)
        painter.drawText(QRectF(rect), int(Qt.AlignmentFlag.AlignCenter), text)
