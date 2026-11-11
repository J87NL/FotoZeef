from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fotozeef.core.models import ProjectSettings
from fotozeef.ui.project_fields import DestinationField, SourceList


@dataclass(frozen=True, slots=True)
class ProjectRequest:
    name: str
    sources: tuple[Path, ...]
    destination: Path | None
    settings: ProjectSettings


class ProjectDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("New project"))
        self.setMinimumWidth(560)

        self._name = QLineEdit(self)
        self._name.setPlaceholderText(self.tr("Shoot name"))
        self._sources = SourceList(parent=self)
        self._sources.changed.connect(self._sources_changed)
        self._destination = DestinationField(parent=self)
        self._recursive = QCheckBox(self.tr("Scan subfolders"), self)
        self._recursive.setChecked(True)
        self._copy_raw = QCheckBox(self.tr("Copy the RAW file alongside its JPEG"), self)
        self._copy_raw.setChecked(True)

        form = QFormLayout()
        form.addRow(self.tr("Name"), self._name)
        form.addRow(self.tr("Sources"), self._sources)
        form.addRow(self.tr("Destination"), self._destination)
        form.addRow("", self._recursive)
        form.addRow("", self._copy_raw)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        self._ok_button.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel(self.tr("Originals are never moved or modified."), self))
        layout.addWidget(self._buttons)

    @property
    def _ok_button(self) -> QPushButton:
        return self._buttons.button(QDialogButtonBox.StandardButton.Ok)

    def request(self) -> ProjectRequest:
        sources = self._sources.paths
        name = self._name.text().strip() or (sources[0].name if sources else self.tr("Untitled"))
        return ProjectRequest(
            name=name,
            sources=sources,
            destination=self._destination.destination(),
            settings=ProjectSettings(
                recursive=self._recursive.isChecked(),
                copy_raw_sidecar=self._copy_raw.isChecked(),
            ),
        )

    def _sources_changed(self) -> None:
        paths = self._sources.paths
        self._ok_button.setEnabled(bool(paths))
        self._destination.set_first_source(paths[0] if paths else None)
        if paths and not self._name.text().strip():
            self._name.setText(paths[0].name)
