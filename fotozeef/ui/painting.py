from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF

STAR_FILL = QColor(255, 199, 44)
STAR_EDGE = QColor(40, 30, 0, 200)
CLOCK_COLOR = QColor(120, 170, 255)
MISSING_OVERLAY = QColor(20, 20, 20, 150)


def draw_star(painter: QPainter, center: QPointF, radius: float) -> None:
    points: list[QPointF] = []
    for index in range(10):
        distance = radius if index % 2 == 0 else radius * 0.45
        radians = math.radians(-90.0 + index * 36.0)
        points.append(
            QPointF(
                center.x() + distance * math.cos(radians),
                center.y() + distance * math.sin(radians),
            )
        )
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(STAR_EDGE, 1.2))
    painter.setBrush(QBrush(STAR_FILL))
    painter.drawPolygon(QPolygonF(points))
    painter.restore()


def draw_estimated_marker(painter: QPainter, rect: QRectF) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(CLOCK_COLOR, 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(rect)
    center = rect.center()
    painter.drawLine(center, QPointF(center.x(), rect.top() + rect.height() * 0.22))
    painter.drawLine(center, QPointF(rect.right() - rect.width() * 0.22, center.y()))
    painter.restore()
