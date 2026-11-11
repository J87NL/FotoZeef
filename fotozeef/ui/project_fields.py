from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fotozeef.core.library import DEFAULT_DESTINATION_NAME, folder_key


class SourceList(QWidget):
    """The folders a project reads from, with Add and Remove."""

    changed = Signal()

    def __init__(self, paths: Iterable[Path] = (), parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._list = QListWidget(self)
        self._list.setMinimumHeight(110)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for path in paths:
            self._list.addItem(str(path))

        self._add = QPushButton(self.tr("Add folder…"), self)
        self._add.clicked.connect(self._pick)
        self._remove = QPushButton(self.tr("Remove"), self)
        self._remove.clicked.connect(self.remove_selected)

        buttons = QHBoxLayout()
        buttons.addWidget(self._add)
        buttons.addWidget(self._remove)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list)
        layout.addLayout(buttons)

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(Path(self._list.item(row).text()) for row in range(self._list.count()))

    def add(self, folder: str | Path) -> bool:
        if not str(folder):
            return False
        text = str(Path(folder))
        if folder_key(text) in {folder_key(path) for path in self.paths}:
            return False
        self._list.addItem(text)
        self.changed.emit()
        return True

    def remove_selected(self) -> None:
        items = self._list.selectedItems()
        for item in items:
            self._list.takeItem(self._list.row(item))
        if items:
            self.changed.emit()

    def select_row(self, row: int) -> None:
        self._list.setCurrentRow(row)

    def _pick(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, self.tr("Add source folder"))
        if chosen:
            self.add(chosen)


class DestinationField(QWidget):
    """Where selected photos go. Empty means a `selectie` folder in the first source."""

    def __init__(self, destination: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._edit = QLineEdit(str(destination) if destination else "", self)
        self._choose = QPushButton(self.tr("Choose…"), self)
        self._choose.clicked.connect(self._pick)
        self._help = QLabel(self)
        self._help.setWordWrap(True)
        self._help.setObjectName("fieldHelp")
        self._help.setStyleSheet("color: #8e8e96;")
        self._default: Path | None = None

        row = QHBoxLayout()
        row.addWidget(self._edit, 1)
        row.addWidget(self._choose)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(row)
        layout.addWidget(self._help)
        self.set_first_source(None)

    @property
    def help_text(self) -> str:
        return self._help.text()

    @property
    def text(self) -> str:
        return self._edit.text().strip()

    def set_text(self, text: str) -> None:
        self._edit.setText(text)

    def set_first_source(self, folder: Path | None) -> None:
        """Updates the hint and placeholder to the folder an empty field will use."""
        self._default = folder / DEFAULT_DESTINATION_NAME if folder is not None else None
        if self._default is None:
            self._edit.setPlaceholderText(f"<first source>/{DEFAULT_DESTINATION_NAME}")
            self._help.setText(
                self.tr(
                    "Leave empty to use a new folder named “{0}” inside the first source folder."
                ).format(DEFAULT_DESTINATION_NAME)
            )
            return
        self._edit.setPlaceholderText(str(self._default))
        self._help.setText(
            self.tr(
                "Leave empty to use {0}. It is created when you select the first photo."
            ).format(self._default)
        )

    def destination(self) -> Path | None:
        """The chosen folder, or None to let the project use its default."""
        return Path(self.text) if self.text else None

    def resolved(self) -> Path | None:
        return self.destination() or self._default

    def _pick(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, self.tr("Choose destination folder"))
        if chosen:
            self._edit.setText(chosen)
