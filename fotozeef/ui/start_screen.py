from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from fotozeef.appinfo import APP_NAME, ICON_PATH
from fotozeef.core.models import Project

NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 1
PATH_ROLE = NAME_ROLE + 1
COUNT_ROLE = NAME_ROLE + 2

ROW_HEIGHT = 56
ROW_PADDING = 12
NAME_COLOR = QColor(228, 228, 234)
PATH_COLOR = QColor(138, 138, 146)
COUNT_COLOR = QColor(255, 199, 44)


class ProjectRowDelegate(QStyledItemDelegate):
    """Name and destination on the left, how many photos are kept on the right."""

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(47, 74, 120))

        count = index.data(COUNT_ROLE) or ""
        metrics = painter.fontMetrics()
        count_width = metrics.horizontalAdvance(count) + (2 * ROW_PADDING if count else 0)

        if count:
            count_rect = QRect(
                option.rect.right() - count_width,
                option.rect.top(),
                count_width - ROW_PADDING,
                option.rect.height(),
            )
            painter.setPen(COUNT_COLOR)
            painter.drawText(
                count_rect,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                count,
            )

        text_width = option.rect.width() - 2 * ROW_PADDING - count_width
        left = option.rect.left() + ROW_PADDING
        name_rect = QRect(left, option.rect.top() + 8, text_width, metrics.height())
        path_rect = QRect(left, name_rect.bottom() + 2, text_width, metrics.height())

        font = painter.font()
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(NAME_COLOR)
        painter.drawText(
            name_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(
                index.data(NAME_ROLE) or "", Qt.TextElideMode.ElideRight, text_width
            ),
        )

        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(PATH_COLOR)
        painter.drawText(
            path_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(
                index.data(PATH_ROLE) or "", Qt.TextElideMode.ElideMiddle, text_width
            ),
        )
        painter.restore()


class StartScreen(QWidget):
    """Shown whenever no project is open."""

    new_requested = Signal()
    browse_requested = Signal()
    open_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("startScreen")

        heading = QLabel(APP_NAME, self)
        heading_font = QFont(self.font())
        heading_font.setPointSize(max(22, heading_font.pointSize() + 12))
        heading_font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(heading_font)

        self._subtitle = QLabel(self.tr("Quickly sort through your photos."), self)
        self._subtitle.setObjectName("startSubtitle")

        icon = QLabel(self)
        if ICON_PATH.is_file():
            icon.setPixmap(
                QPixmap(str(ICON_PATH)).scaled(
                    72,
                    72,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        title_column.addWidget(heading)
        title_column.addWidget(self._subtitle)

        title_row = QHBoxLayout()
        title_row.setSpacing(16)
        title_row.addWidget(icon)
        title_row.addLayout(title_column)
        title_row.addStretch(1)

        self._new_button = QPushButton(self.tr("New project…"), self)
        self._new_button.setObjectName("primaryButton")
        self._new_button.setMinimumHeight(38)
        self._new_button.clicked.connect(self.new_requested)

        self._open_button = QPushButton(self.tr("Open project…"), self)
        self._open_button.setMinimumHeight(38)
        self._open_button.clicked.connect(self.browse_requested)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(self._new_button)
        buttons.addWidget(self._open_button)
        buttons.addStretch(1)

        self._recent_label = QLabel(self.tr("Recent projects"), self)
        self._recent_label.setObjectName("sectionLabel")

        self._list = QListWidget(self)
        self._list.setObjectName("recentList")
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setItemDelegate(ProjectRowDelegate(self._list))
        self._list.setUniformItemSizes(True)
        self._list.itemActivated.connect(self._activate)
        self._list.itemDoubleClicked.connect(self._activate)

        self._empty = QLabel(self.tr("No projects yet. Start with New project…"), self)
        self._empty.setObjectName("startSubtitle")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 48, 56, 48)
        layout.setSpacing(18)
        layout.addLayout(title_row)
        layout.addLayout(buttons)
        layout.addWidget(self._recent_label)
        layout.addWidget(self._empty)
        layout.addWidget(self._list, 1)

        self.setStyleSheet(
            """
            QWidget#startScreen { background: #141416; }
            QLabel#startSubtitle { color: #8e8e96; }
            QLabel#sectionLabel { color: #b4b4bc; font-weight: 600; }
            QPushButton { padding: 6px 18px; }
            QPushButton#primaryButton { font-weight: 600; }
            QListWidget#recentList {
                background: #1c1c1e; border: 1px solid #2c2c30; border-radius: 6px;
            }
            QListWidget#recentList::item { padding: 9px 12px; border-bottom: 1px solid #242428; }
            QListWidget#recentList::item:selected { background: #2f4straight; }
            """.replace("#2f4straight", "#2f4a78")
        )

    def retranslate(self) -> None:
        self._subtitle.setText(self.tr("Quickly sort through your photos."))
        self._new_button.setText(self.tr("New project…"))
        self._open_button.setText(self.tr("Open project…"))
        self._recent_label.setText(self.tr("Recent projects"))
        self._empty.setText(self.tr("No projects yet. Start with New project…"))

    def set_projects(
        self,
        projects: Sequence[Project],
        counts: Mapping[int, int] | None = None,
    ) -> None:
        selected = counts or {}
        self._list.clear()
        for project in projects:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            item.setData(NAME_ROLE, project.name)
            item.setData(PATH_ROLE, str(project.destination))
            item.setData(COUNT_ROLE, self._count_label(selected.get(project.id, 0)))
            self._list.addItem(item)
        has_projects = bool(projects)
        self._list.setVisible(has_projects)
        self._empty.setVisible(not has_projects)
        self._recent_label.setVisible(has_projects)
        if has_projects:
            self._list.setCurrentRow(0)

    def _count_label(self, count: int) -> str:
        if count <= 0:
            return ""
        return self.tr("{0} in selection").format(count)

    def _activate(self, item: QListWidgetItem) -> None:
        self.open_requested.emit(int(item.data(Qt.ItemDataRole.UserRole)))
