from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QWidget

from fotozeef.core.models import TimelineEntry
from fotozeef.ui.painting import draw_star

BACKGROUND = QColor(18, 18, 20)
CAPTION = QColor(215, 215, 220)
CAPTION_DIM = QColor(150, 150, 158)


class Viewer(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entry: TimelineEntry | None = None
        self._pixmap: QPixmap | None = None
        self._selected = False
        self._placeholder = "Open or create a project to start culling"
        self.setMinimumSize(320, 240)
        self.setAutoFillBackground(True)

    def show_entry(
        self,
        entry: TimelineEntry | None,
        pixmap: QPixmap | None,
        selected: bool,
    ) -> None:
        self._entry = entry
        self._pixmap = pixmap
        self._selected = selected
        self.update()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
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

        caption_height = 34
        canvas = self.rect().adjusted(12, 12, -12, -(caption_height + 12))
        if self._pixmap is None or self._pixmap.isNull():
            self._draw_centered_text(painter, canvas, "Loading…", CAPTION_DIM)
        else:
            target = self._draw_pixmap(painter, canvas)
            if self._selected:
                draw_star(painter, QPointF(target.right() - 20, target.top() + 20), 14.0)

        self._draw_caption(painter, caption_height)
        painter.end()

    def _draw_pixmap(self, painter: QPainter, canvas: QRect) -> QRect:
        pixmap = self._pixmap
        assert pixmap is not None
        ratio = pixmap.devicePixelRatio()
        scaled = pixmap.scaled(
            canvas.size() * ratio,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        target = QRect(0, 0, int(scaled.width() / ratio), int(scaled.height() / ratio))
        target.moveCenter(canvas.center())
        painter.drawPixmap(target, scaled)
        return target

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
            parts.append("missing")
        return "   ".join(parts)

    def _draw_placeholder(self, painter: QPainter) -> None:
        self._draw_centered_text(painter, self.rect(), self._placeholder, CAPTION_DIM)

    def _draw_centered_text(self, painter: QPainter, rect: QRect, text: str, color: QColor) -> None:
        painter.setPen(color)
        painter.drawText(QRectF(rect), int(Qt.AlignmentFlag.AlignCenter), text)
