from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fotozeef.core.models import Project, ProjectSettings


class SettingsDialog(QDialog):
    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Project settings"))
        self.setMinimumWidth(520)

        self._name = QLineEdit(project.name, self)
        self._destination = QLineEdit(str(project.destination), self)
        self._recursive = QCheckBox(self.tr("Scan subfolders"), self)
        self._recursive.setChecked(project.settings.recursive)
        self._copy_raw = QCheckBox(self.tr("Copy the RAW file alongside its JPEG"), self)
        self._copy_raw.setChecked(project.settings.copy_raw_sidecar)
        self._write_xmp = QCheckBox(self.tr("Write XMP sidecars next to the originals"), self)
        self._write_xmp.setChecked(project.settings.write_xmp)

        pick = QPushButton(self.tr("Choose…"), self)
        pick.clicked.connect(self._pick_destination)
        destination_row = QHBoxLayout()
        destination_row.addWidget(self._destination, 1)
        destination_row.addWidget(pick)

        form = QFormLayout()
        form.addRow(self.tr("Name"), self._name)
        form.addRow(self.tr("Destination"), destination_row)
        form.addRow("", self._recursive)
        form.addRow("", self._copy_raw)
        form.addRow("", self._write_xmp)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @property
    def name(self) -> str:
        return self._name.text().strip()

    @property
    def destination(self) -> Path:
        return Path(self._destination.text().strip())

    @property
    def settings(self) -> ProjectSettings:
        return ProjectSettings(
            recursive=self._recursive.isChecked(),
            copy_raw_sidecar=self._copy_raw.isChecked(),
            write_xmp=self._write_xmp.isChecked(),
        )

    def _pick_destination(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, self.tr("Choose destination folder"))
        if chosen:
            self._destination.setText(chosen)
