from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from fotozeef.core.slideshow import (
    MAX_SECONDS,
    MIN_SECONDS,
    PauseMode,
    PhotoScope,
    SlideOrder,
    SlideshowSettings,
    Transition,
)

SUBOPTION_INDENT = 22


class SlideshowDialog(QDialog):
    """Settings for a show. Closing keeps them too, so a show can be set up in advance."""

    def __init__(
        self,
        settings: SlideshowSettings,
        selected_count: int,
        parent: QWidget | None = None,
        screens: tuple[tuple[str, str], ...] = (),
    ) -> None:
        """`screens` lists (name, label) per screen; the choice shows only with two or more."""
        super().__init__(parent)
        self.setWindowTitle(self.tr("Slideshow"))
        self.setMinimumWidth(440)
        self._start = False

        self._all = QRadioButton(self.tr("All photos"), self)
        self._selected = QRadioButton(
            self.tr("Only the selected photos ({0})").format(selected_count), self
        )
        scope_group = QButtonGroup(self)
        scope_group.addButton(self._all)
        scope_group.addButton(self._selected)
        self._all.setChecked(settings.scope is PhotoScope.ALL)
        self._selected.setChecked(settings.scope is PhotoScope.SELECTED)
        self._subfolders = QCheckBox(self.tr("Include photos in subfolders"), self)
        self._subfolders.setChecked(settings.include_subfolders)
        self._all.toggled.connect(self._subfolders.setEnabled)
        self._subfolders.setEnabled(settings.scope is PhotoScope.ALL)

        self._seconds = QSpinBox(self)
        self._seconds.setRange(MIN_SECONDS, MAX_SECONDS)
        self._seconds.setValue(settings.seconds)
        self._seconds.setSuffix(self.tr(" s"))

        self._chronological = QRadioButton(self.tr("Chronological"), self)
        self._random = QRadioButton(self.tr("Random"), self)
        order_group = QButtonGroup(self)
        order_group.addButton(self._chronological)
        order_group.addButton(self._random)
        self._chronological.setChecked(settings.order is SlideOrder.CHRONOLOGICAL)
        self._random.setChecked(settings.order is SlideOrder.RANDOM)
        self._start_at_current = QCheckBox(self.tr("Start at the current photo"), self)
        self._start_at_current.setChecked(settings.start_at_current)
        self._start_at_current.setEnabled(settings.order is SlideOrder.CHRONOLOGICAL)
        self._chronological.toggled.connect(self._start_at_current.setEnabled)
        self._stop_after_one_round = QCheckBox(
            self.tr("Stop after one round, on a black screen"), self
        )
        self._stop_after_one_round.setChecked(settings.stop_after_one_round)

        self._screen = QComboBox(self)
        self._screen.addItem(self.tr("The screen FotoZeef is on"), "")
        for name, label in screens:
            self._screen.addItem(label, name)
        stored = self._screen.findData(settings.screen)
        self._screen.setCurrentIndex(max(stored, 0))
        if stored < 0 and settings.screen:
            # Not connected now; keep the choice for when it is.
            self._screen.addItem(
                self.tr("{0} (not connected)").format(settings.screen), settings.screen
            )
            self._screen.setCurrentIndex(self._screen.count() - 1)

        self._transitions: dict[Transition, QCheckBox] = {
            Transition.FADE: QCheckBox(self.tr("Fade"), self),
            Transition.SLIDE_LEFT: QCheckBox(self.tr("Slide in from the left"), self),
            Transition.SLIDE_RIGHT: QCheckBox(self.tr("Slide in from the right"), self),
            Transition.SLIDE_TOP: QCheckBox(self.tr("Slide in from the top"), self),
            Transition.SLIDE_BOTTOM: QCheckBox(self.tr("Slide in from the bottom"), self),
        }
        for transition, box in self._transitions.items():
            box.setChecked(transition in settings.transitions)

        self._hold = QRadioButton(self.tr("Keep the photo on screen"), self)
        self._black = QRadioButton(self.tr("Show a black screen"), self)
        pause_group = QButtonGroup(self)
        pause_group.addButton(self._hold)
        pause_group.addButton(self._black)
        self._hold.setChecked(settings.pause_mode is PauseMode.HOLD)
        self._black.setChecked(settings.pause_mode is PauseMode.BLACK)

        photos = QGroupBox(self.tr("Photos"), self)
        photos_layout = QVBoxLayout(photos)
        photos_layout.addWidget(self._all)
        subfolders_row = QHBoxLayout()
        subfolders_row.setContentsMargins(SUBOPTION_INDENT, 0, 0, 0)
        subfolders_row.addWidget(self._subfolders)
        photos_layout.addLayout(subfolders_row)
        photos_layout.addWidget(self._selected)

        playback = QGroupBox(self.tr("Playback"), self)
        playback_form = QFormLayout(playback)
        playback_form.addRow(self.tr("Each photo"), self._seconds)
        order_box = QVBoxLayout()
        order_box.addWidget(self._chronological)
        start_row = QHBoxLayout()
        start_row.setContentsMargins(SUBOPTION_INDENT, 0, 0, 0)
        start_row.addWidget(self._start_at_current)
        order_box.addLayout(start_row)
        order_box.addWidget(self._random)
        playback_form.addRow(self.tr("Order"), order_box)
        playback_form.addRow("", self._stop_after_one_round)
        pause_box = QVBoxLayout()
        pause_box.addWidget(self._hold)
        pause_box.addWidget(self._black)
        playback_form.addRow(self.tr("When paused (Space)"), pause_box)
        if len(screens) > 1:
            playback_form.addRow(self.tr("Screen"), self._screen)
        else:
            self._screen.hide()

        effects = QGroupBox(self.tr("Transitions"), self)
        effects_layout = QVBoxLayout(effects)
        for box in self._transitions.values():
            effects_layout.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        self._start_button = QPushButton(self.tr("Start slideshow"), self)
        self._start_button.setDefault(True)
        buttons.addButton(self._start_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._accept_start)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(photos)
        layout.addWidget(playback)
        layout.addWidget(effects)
        layout.addWidget(buttons)

    @property
    def start_requested(self) -> bool:
        return self._start

    @property
    def settings(self) -> SlideshowSettings:
        return SlideshowSettings(
            scope=PhotoScope.SELECTED if self._selected.isChecked() else PhotoScope.ALL,
            include_subfolders=self._subfolders.isChecked(),
            seconds=self._seconds.value(),
            order=SlideOrder.RANDOM if self._random.isChecked() else SlideOrder.CHRONOLOGICAL,
            transitions=frozenset(
                transition for transition, box in self._transitions.items() if box.isChecked()
            ),
            pause_mode=PauseMode.BLACK if self._black.isChecked() else PauseMode.HOLD,
            stop_after_one_round=self._stop_after_one_round.isChecked(),
            start_at_current=self._start_at_current.isChecked(),
            screen=str(self._screen.currentData() or ""),
        )

    def _accept_start(self) -> None:
        self._start = True
        self.accept()
