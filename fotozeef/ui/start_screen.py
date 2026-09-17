from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fotozeef.appinfo import APP_NAME, ICON_PATH
from fotozeef.core.models import Project


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

        self._subtitle = QLabel(self.tr("Fast culling of photo shoots"), self)
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

    def set_projects(self, projects: Sequence[Project]) -> None:
        self._list.clear()
        for project in projects:
            item = QListWidgetItem(f"{project.name}\n{project.destination}")
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            self._list.addItem(item)
        has_projects = bool(projects)
        self._list.setVisible(has_projects)
        self._empty.setVisible(not has_projects)
        self._recent_label.setVisible(has_projects)
        if has_projects:
            self._list.setCurrentRow(0)

    def _activate(self, item: QListWidgetItem) -> None:
        self.open_requested.emit(int(item.data(Qt.ItemDataRole.UserRole)))
