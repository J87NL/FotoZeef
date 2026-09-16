from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fotozeef.core.models import Project


class OpenProjectDialog(QDialog):
    forget_requested = Signal(int)

    def __init__(self, projects: Sequence[Project], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open project")
        self.setMinimumWidth(520)
        self._projects = tuple(projects)

        self._list = QListWidget(self)
        for project in self._projects:
            item = QListWidgetItem(f"{project.name}\n{project.destination}")
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            self._list.addItem(item)
        self._list.itemDoubleClicked.connect(lambda _item: self.accept())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._delete = QPushButton("Forget project", self)
        self._delete.clicked.connect(self._forget)
        buttons.addButton(self._delete, QDialogButtonBox.ButtonRole.DestructiveRole)

        layout = QVBoxLayout(self)
        if not self._projects:
            layout.addWidget(QLabel("No projects yet.", self))
        layout.addWidget(self._list)
        layout.addWidget(buttons)

        if self._projects:
            self._list.setCurrentRow(0)

    def selected_project_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return int(item.data(Qt.ItemDataRole.UserRole))

    def _forget(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        self.forget_requested.emit(int(item.data(Qt.ItemDataRole.UserRole)))
        self._list.takeItem(self._list.row(item))
