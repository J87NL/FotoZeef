from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

WINDOW = QColor(32, 32, 35)
BASE = QColor(24, 24, 26)
TEXT = QColor(226, 226, 230)
DISABLED = QColor(128, 128, 134)
HIGHLIGHT = QColor(72, 110, 168)


def apply_dark_theme(app: QApplication) -> None:
    """A neutral dark surround; anything brighter skews how photos read."""
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, WINDOW)
    palette.setColor(QPalette.ColorRole.WindowText, TEXT)
    palette.setColor(QPalette.ColorRole.Base, BASE)
    palette.setColor(QPalette.ColorRole.AlternateBase, WINDOW)
    palette.setColor(QPalette.ColorRole.ToolTipBase, WINDOW)
    palette.setColor(QPalette.ColorRole.ToolTipText, TEXT)
    palette.setColor(QPalette.ColorRole.Text, TEXT)
    palette.setColor(QPalette.ColorRole.Button, WINDOW)
    palette.setColor(QPalette.ColorRole.ButtonText, TEXT)
    palette.setColor(QPalette.ColorRole.Highlight, HIGHLIGHT)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    for group in (QPalette.ColorGroup.Disabled,):
        palette.setColor(group, QPalette.ColorRole.Text, DISABLED)
        palette.setColor(group, QPalette.ColorRole.ButtonText, DISABLED)
        palette.setColor(group, QPalette.ColorRole.WindowText, DISABLED)
    app.setPalette(palette)
