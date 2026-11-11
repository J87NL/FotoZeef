from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fotozeef.core.models import Project, ProjectSettings, Source
from fotozeef.ui.project_fields import DestinationField, SourceList


class SettingsDialog(QDialog):
    """A project's name, folders, destination and options, from the start screen or within."""

    def __init__(
        self,
        project: Project,
        sources: Sequence[Source] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Project settings"))
        self.setMinimumWidth(560)

        self._name = QLineEdit(project.name, self)
        self._sources = SourceList((source.path for source in sources), self)
        self._sources.changed.connect(self._sources_changed)
        self._destination = DestinationField(project.destination, self)
        self._recursive = QCheckBox(self.tr("Scan subfolders"), self)
        self._recursive.setChecked(project.settings.recursive)
        self._copy_raw = QCheckBox(self.tr("Copy the RAW file alongside its JPEG"), self)
        self._copy_raw.setChecked(project.settings.copy_raw_sidecar)

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

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)
        self._sources_changed()

    @property
    def name(self) -> str:
        return self._name.text().strip()

    @property
    def source_paths(self) -> tuple[Path, ...]:
        return self._sources.paths

    @property
    def destination(self) -> Path:
        """The folder typed in, or the default in the first source when left empty."""
        resolved = self._destination.resolved()
        assert resolved is not None, "OK is disabled without a source folder"
        return resolved

    @property
    def settings(self) -> ProjectSettings:
        return ProjectSettings(
            recursive=self._recursive.isChecked(),
            copy_raw_sidecar=self._copy_raw.isChecked(),
        )

    @property
    def _ok_button(self) -> QPushButton:
        return self._buttons.button(QDialogButtonBox.StandardButton.Ok)

    def _sources_changed(self) -> None:
        paths = self._sources.paths
        self._ok_button.setEnabled(bool(paths))
        self._destination.set_first_source(paths[0] if paths else None)
