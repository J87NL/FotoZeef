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

from fotozeef.core.models import Source, TimelineEntry
from fotozeef.core.ordering import calibration_offset

_OFFSET_LIMIT = 60 * 60 * 24 * 7


class OffsetDialog(QDialog):
    """Per-source clock correction, with a two-photo calibration shortcut."""

    def __init__(
        self,
        sources: Sequence[Source],
        reference: TimelineEntry | None = None,
        target: TimelineEntry | None = None,
        reference_pixmap: QPixmap | None = None,
        target_pixmap: QPixmap | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Time offsets"))
        self.setMinimumWidth(560)
        self._sources = tuple(sources)
        self._spins: dict[int, QSpinBox] = {}

        form = QFormLayout()
        for source in self._sources:
            spin = QSpinBox(self)
            spin.setRange(-_OFFSET_LIMIT, _OFFSET_LIMIT)
            spin.setSingleStep(60)
            spin.setSuffix(" s")
            spin.setValue(source.time_offset_s)
            spin.setToolTip(str(source.path))
            self._spins[source.id] = spin
            form.addRow(source.label, spin)

        layout = QVBoxLayout(self)
        box = QGroupBox(self.tr("Offset per source"), self)
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

    def offsets(self) -> dict[int, int]:
        return {source_id: spin.value() for source_id, spin in self._spins.items()}

    def changed_offsets(self) -> dict[int, int]:
        current = self.offsets()
        return {
            source.id: current[source.id]
            for source in self._sources
            if current[source.id] != source.time_offset_s
        }

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
            layout.addWidget(
                QLabel(
                    self.tr(
                        "Mark a reference photo (Timeline ▸ Set time reference), then move to"
                        " the matching photo from the other camera and reopen this dialog."
                    ),
                    box,
                )
            )
            return box

        if reference.source.id == target.source.id:
            layout.addWidget(
                QLabel(self.tr("The reference photo and the current photo share one source."), box)
            )
            return box

        delta = calibration_offset(reference, target)
        photos = QHBoxLayout()
        photos.addWidget(self._photo_card(box, self.tr("Reference"), reference, reference_pixmap))
        photos.addWidget(self._photo_card(box, self.tr("Current"), target, target_pixmap))
        layout.addLayout(photos)

        apply = QPushButton(self.tr("Set {0} to {1:+d} s").format(target.source.label, delta), box)
        apply.clicked.connect(lambda: self._spins[target.source.id].setValue(delta))
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
        heading = QLabel(f"{title} — {entry.source.label}", card)
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
