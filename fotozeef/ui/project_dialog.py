from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fotozeef.core.library import DEFAULT_DESTINATION_NAME
from fotozeef.core.models import ProjectSettings


@dataclass(frozen=True, slots=True)
class ProjectRequest:
    name: str
    sources: tuple[Path, ...]
    destination: Path | None
    settings: ProjectSettings


class ProjectDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New project")
        self.setMinimumWidth(560)

        self._name = QLineEdit(self)
        self._name.setPlaceholderText("Shoot name")
        self._sources = QListWidget(self)
        self._sources.setMinimumHeight(120)
        self._destination = QLineEdit(self)
        self._destination.setPlaceholderText(f"<first source>/{DEFAULT_DESTINATION_NAME}")
        self._recursive = QCheckBox("Scan subfolders", self)
        self._recursive.setChecked(True)
        self._copy_raw = QCheckBox("Copy the RAW file alongside its JPEG", self)
        self._copy_raw.setChecked(True)
        self._write_xmp = QCheckBox("Write XMP sidecars next to the originals", self)

        add_source = QPushButton("Add folder…", self)
        add_source.clicked.connect(self._add_source)
        remove_source = QPushButton("Remove", self)
        remove_source.clicked.connect(self._remove_source)
        pick_destination = QPushButton("Choose…", self)
        pick_destination.clicked.connect(self._pick_destination)

        source_buttons = QHBoxLayout()
        source_buttons.addWidget(add_source)
        source_buttons.addWidget(remove_source)
        source_buttons.addStretch(1)

        destination_row = QHBoxLayout()
        destination_row.addWidget(self._destination, 1)
        destination_row.addWidget(pick_destination)

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Sources", self._sources)
        form.addRow("", source_buttons)
        form.addRow("Destination", destination_row)
        form.addRow("", self._recursive)
        form.addRow("", self._copy_raw)
        form.addRow("", self._write_xmp)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._ok_button.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Originals are never moved or modified.", self))
        layout.addWidget(self._buttons)

    @property
    def _ok_button(self) -> QPushButton:
        return self._buttons.button(QDialogButtonBox.StandardButton.Ok)

    def request(self) -> ProjectRequest:
        sources = tuple(
            Path(self._sources.item(row).text()) for row in range(self._sources.count())
        )
        destination_text = self._destination.text().strip()
        name = self._name.text().strip() or (sources[0].name if sources else "Untitled")
        return ProjectRequest(
            name=name,
            sources=sources,
            destination=Path(destination_text) if destination_text else None,
            settings=ProjectSettings(
                recursive=self._recursive.isChecked(),
                copy_raw_sidecar=self._copy_raw.isChecked(),
                write_xmp=self._write_xmp.isChecked(),
            ),
        )

    def _add_source(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Add source folder")
        if not chosen:
            return
        existing = {self._sources.item(row).text() for row in range(self._sources.count())}
        if chosen in existing:
            return
        self._sources.addItem(chosen)
        if not self._name.text().strip():
            self._name.setText(Path(chosen).name)
        self._ok_button.setEnabled(True)

    def _remove_source(self) -> None:
        for item in self._sources.selectedItems():
            self._sources.takeItem(self._sources.row(item))
        self._ok_button.setEnabled(self._sources.count() > 0)

    def _pick_destination(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose destination folder")
        if chosen:
            self._destination.setText(chosen)
