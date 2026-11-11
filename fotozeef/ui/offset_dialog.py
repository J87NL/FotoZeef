from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from fotozeef.core.library import Clock
from fotozeef.core.models import TimelineEntry
from fotozeef.core.ordering import calibration_offset

_OFFSET_LIMIT = 60 * 60 * 24 * 7


class OffsetDialog(QDialog):
    """Clock correction per camera per folder, with a two-photo calibration shortcut."""

    def __init__(
        self,
        clocks: Sequence[Clock],
        reference: TimelineEntry | None = None,
        target: TimelineEntry | None = None,
        reference_pixmap: QPixmap | None = None,
        target_pixmap: QPixmap | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Time offsets"))
        self.setMinimumWidth(560)
        self._clocks = tuple(clocks)
        self._spins: dict[tuple[int, str], QSpinBox] = {}
        several_folders = len({clock.source.id for clock in self._clocks}) > 1

        form = QFormLayout()
        for clock in self._clocks:
            spin = QSpinBox(self)
            spin.setRange(-_OFFSET_LIMIT, _OFFSET_LIMIT)
            spin.setSingleStep(60)
            spin.setSuffix(" s")
            spin.setValue(clock.offset)
            spin.setToolTip(str(clock.source.path))
            self._spins[clock.key] = spin
            form.addRow(self._clock_label(clock, several_folders), spin)

        layout = QVBoxLayout(self)
        box = QGroupBox(self.tr("Offset per camera"), self)
        box.setLayout(form)
        layout.addWidget(box)

        calibration = self._build_calibration(reference, target, reference_pixmap, target_pixmap)
        if calibration is not None:
            layout.addWidget(calibration)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def offsets(self) -> dict[tuple[int, str], int]:
        return {key: spin.value() for key, spin in self._spins.items()}

    def changed_offsets(self) -> dict[tuple[int, str], int]:
        """(source id, camera) to its new offset, for the cameras that changed."""
        current = self.offsets()
        return {
            clock.key: current[clock.key]
            for clock in self._clocks
            if current[clock.key] != clock.offset
        }

    def _clock_label(self, clock: Clock, several_folders: bool) -> str:
        camera = clock.camera or self.tr("Unknown camera")
        label = self.tr("{0} ({1} photos)").format(camera, clock.photos)
        if several_folders:
            label = f"{label} — {clock.source.path.name or clock.source.path}"
        return label

    def _build_calibration(
        self,
        reference: TimelineEntry | None,
        target: TimelineEntry | None,
        reference_pixmap: QPixmap | None,
        target_pixmap: QPixmap | None,
    ) -> QWidget | None:
        box = QGroupBox(self.tr("Calibrate on one moment"), self)
        layout = QVBoxLayout(box)

        if reference is None or target is None:
            explanation = QLabel(
                self.tr(
                    "Mark a reference photo (Timeline ▸ Set time reference), then move to"
                    " the matching photo from the other camera and reopen this dialog."
                ),
                box,
            )
            explanation.setWordWrap(True)
            layout.addWidget(explanation)
            return box

        if reference.clock == target.clock:
            layout.addWidget(
                QLabel(self.tr("The reference photo and the current photo share one camera."), box)
            )
            return box
        if target.clock not in self._spins:
            return box

        delta = calibration_offset(reference, target)
        photos = QHBoxLayout()
        photos.addWidget(self._photo_card(box, self.tr("Reference"), reference, reference_pixmap))
        photos.addWidget(self._photo_card(box, self.tr("Current"), target, target_pixmap))
        layout.addLayout(photos)

        apply = QPushButton(self.tr("Set {0} to {1:+d} s").format(target.camera_label, delta), box)
        apply.clicked.connect(lambda: self._spins[target.clock].setValue(delta))
        layout.addWidget(apply)
        return box

    def _photo_card(
        self,
        parent: QWidget,
        title: str,
        entry: TimelineEntry,
        pixmap: QPixmap | None,
    ) -> QWidget:
        card = QWidget(parent)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(f"{title} — {entry.camera_label}", card)
        heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(heading)
        if pixmap is not None and not pixmap.isNull():
            thumbnail = QLabel(card)
            thumbnail.setPixmap(
                pixmap.scaled(
                    180,
                    120,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            layout.addWidget(thumbnail)
        raw = entry.photo.captured_at
        layout.addWidget(QLabel(entry.photo.filename, card))
        layout.addWidget(
            QLabel(raw.strftime("%Y-%m-%d %H:%M:%S") if raw else self.tr("no capture time"), card)
        )
        layout.addStretch(1)
        return card
