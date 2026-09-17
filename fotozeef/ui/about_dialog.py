from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from fotozeef.appinfo import (
    APP_AUTHOR,
    APP_BUNDLE_ID,
    APP_NAME,
    APP_VERSION,
    ICON_PATH,
    THIRD_PARTY_PATH,
    cache_dir,
    database_path,
)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("About {0}").format(APP_NAME))
        self.setMinimumSize(620, 460)

        tabs = QTabWidget(self)
        tabs.addTab(self._about_tab(), self.tr("About"))
        tabs.addTab(self._shortcuts_tab(), self.tr("Keyboard"))
        tabs.addTab(self._licenses_tab(), self.tr("Licenses"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)

    def _about_tab(self) -> QWidget:
        page = QWidget(self)

        icon = QLabel(page)
        if ICON_PATH.is_file():
            icon.setPixmap(
                QPixmap(str(ICON_PATH)).scaled(
                    64,
                    64,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)

        heading = QLabel(APP_NAME, page)
        font = QFont(heading.font())
        font.setPointSize(font.pointSize() + 8)
        font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(font)

        body = QTextBrowser(page)
        body.setOpenExternalLinks(True)
        body.setHtml(
            "<p>{tagline}</p><p>{privacy}</p>"
            "<table cellpadding='3'>"
            "<tr><td><b>{version_label}</b></td><td>{version}</td></tr>"
            "<tr><td><b>{id_label}</b></td><td><code>{bundle}</code></td></tr>"
            "<tr><td><b>{by_label}</b></td><td>{author}</td></tr>"
            "<tr><td><b>{license_label}</b></td><td>MIT</td></tr>"
            "<tr><td><b>{db_label}</b></td><td><code>{database}</code></td></tr>"
            "<tr><td><b>{cache_label}</b></td><td><code>{cache}</code></td></tr>"
            "</table>".format(
                tagline=self.tr("Fast, keyboard-driven culling of photo shoots."),
                privacy=self.tr(
                    "Everything stays on this machine: no account, no cloud, no telemetry."
                    " Your originals are only ever read, never moved or changed."
                ),
                version_label=self.tr("Version"),
                version=APP_VERSION,
                id_label=self.tr("Identifier"),
                bundle=APP_BUNDLE_ID,
                by_label=self.tr("By"),
                author=APP_AUTHOR,
                license_label=self.tr("License"),
                db_label=self.tr("Database"),
                database=database_path(),
                cache_label=self.tr("Thumbnails"),
                cache=cache_dir(),
            )
        )

        text_column = QVBoxLayout()
        text_column.addWidget(heading)
        text_column.addWidget(body, 1)

        layout = QHBoxLayout(page)
        layout.addWidget(icon)
        layout.addSpacing(12)
        layout.addLayout(text_column, 1)
        return page

    def _shortcuts_tab(self) -> QWidget:
        rows = [
            ("←  →", self.tr("Previous / next photo")),
            ("Space", self.tr("Keep or unkeep the current photo")),
            ("Home / End", self.tr("First / last photo")),
            ("PgUp / PgDn", self.tr("Jump ten photos")),
            ("+  -", self.tr("Zoom in / out")),
            ("0", self.tr("Fit to window")),
            ("1", self.tr("Actual size")),
            (self.tr("Wheel, drag, double click"), self.tr("Zoom around the pointer, pan, toggle")),
            ("F", self.tr("Fullscreen")),
            ("Esc", self.tr("Unzoom, then leave fullscreen")),
            ("Ctrl+N / Ctrl+O / Ctrl+W", self.tr("New / open / close project")),
            ("Ctrl+,", self.tr("Project settings")),
        ]
        body = QTextBrowser(self)
        body.setHtml(
            "<table cellpadding='5' width='100%'>"
            + "".join(
                f"<tr><td width='42%'><code>{keys}</code></td><td>{what}</td></tr>"
                for keys, what in rows
            )
            + "</table>"
        )
        return body

    def _licenses_tab(self) -> QWidget:
        body = QTextBrowser(self)
        body.setOpenExternalLinks(True)
        if THIRD_PARTY_PATH.is_file():
            body.setMarkdown(THIRD_PARTY_PATH.read_text(encoding="utf-8"))
            return body
        body.setPlainText(self.tr("The third-party notice is missing from this build."))
        return body
