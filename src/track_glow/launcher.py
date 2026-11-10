import html
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from track_glow.engine import status_text
from track_glow.server import ServerStartError, WebServer
from track_glow.web import EngineLike

APP_NAME = "Track Glow"
TRAY_COLOR = "#2e7d32"
IDLE_COLOR = "#9e9e9e"
STATUS_REFRESH_MS = 500
HOSTS = [
    ("This computer only (127.0.0.1)", "127.0.0.1"),
    ("All interfaces (0.0.0.0)", "0.0.0.0"),
]


def open_in_browser(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class LauncherWindow(QMainWindow):
    def __init__(
        self,
        engine: EngineLike,
        host: str,
        port: int,
        server_factory: Callable[[str, int], WebServer] | None = None,
        open_url: Callable[[str], object] = open_in_browser,
        tray_available: bool | None = None,
    ):
        super().__init__()
        self._engine = engine
        self._server_factory = server_factory or (lambda h, p: WebServer(h, p, engine))
        self._open_url = open_url
        self._server: WebServer | None = None
        if tray_available is None:
            tray_available = QSystemTrayIcon.isSystemTrayAvailable()

        self.setWindowTitle(APP_NAME)
        icon_pixmap = QPixmap(64, 64)
        icon_pixmap.fill(QColor(TRAY_COLOR))
        icon = QIcon(icon_pixmap)
        self.setWindowIcon(icon)

        self.flag_swatch = QLabel()
        self.flag_swatch.setFixedSize(24, 24)
        self.status_label = QLabel("No race")
        status_row = QHBoxLayout()
        status_row.addWidget(self.flag_swatch)
        status_row.addWidget(self.status_label, 1)

        self.host_combo = QComboBox()
        for label, value in HOSTS:
            self.host_combo.addItem(label, value)
        index = self.host_combo.findData(host)
        if index < 0:
            self.host_combo.addItem(host, host)
            index = self.host_combo.count() - 1
        self.host_combo.setCurrentIndex(index)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(min(1024, port), 65535)
        self.port_spin.setValue(port)
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply)
        address_row = QHBoxLayout()
        address_row.addWidget(QLabel("Web UI address"))
        address_row.addWidget(self.host_combo, 1)
        address_row.addWidget(self.port_spin)
        address_row.addWidget(self.apply_button)

        self.url_label = QLabel()
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.url_label.linkActivated.connect(self._open_url)

        self.open_button = QPushButton("Open Web UI")
        self.open_button.clicked.connect(self.open_web_ui)
        self.hide_button = QPushButton("Hide to tray")
        self.hide_button.clicked.connect(self.hide_to_tray)
        self.quit_button = QPushButton("Quit")
        self.quit_button.clicked.connect(self.quit)
        button_row = QHBoxLayout()
        button_row.addWidget(self.open_button)
        button_row.addWidget(self.hide_button)
        button_row.addStretch(1)
        button_row.addWidget(self.quit_button)

        layout = QVBoxLayout()
        layout.addLayout(status_row)
        layout.addLayout(address_row)
        layout.addWidget(self.url_label)
        layout.addLayout(button_row)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.tray: QSystemTrayIcon | None = None
        if tray_available:
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip(APP_NAME)
            menu = QMenu(self)
            for text, slot in (
                ("Show", self.show_window),
                ("Open Web UI", self.open_web_ui),
                ("Quit", self.quit),
            ):
                action = QAction(text, menu)
                action.triggered.connect(slot)
                menu.addAction(action)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self._tray_activated)
            self.tray.show()

        self._start(host, port)
        self.refresh_status()
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self.refresh_status)
        self._status_timer.start(STATUS_REFRESH_MS)

    def refresh_status(self) -> None:
        state = self._engine.snapshot()
        text = status_text(state)
        color = state.flag.color if state.flag else IDLE_COLOR
        self.status_label.setText(text)
        self.flag_swatch.setStyleSheet(f"background: {color}; border-radius: 4px;")
        if self.tray is not None:
            self.tray.setToolTip(f"{APP_NAME} · {text}")

    def _start(self, host: str, port: int) -> None:
        self._server = self._server_factory(host, port)
        try:
            self._server.start()
        except ServerStartError as e:
            self.url_label.setText(
                f'<span style="color: #c62828;">{html.escape(str(e), quote=False)}</span>'
            )
            self.open_button.setEnabled(False)
            return
        url = html.escape(self._server.url)
        self.url_label.setText(f'<a href="{url}">{url}</a>')
        self.open_button.setEnabled(True)

    def _stop(self) -> None:
        if self._server is not None:
            self._server.stop()

    def apply(self) -> None:
        self._stop()
        self._start(self.host_combo.currentData(), self.port_spin.value())

    def open_web_ui(self) -> None:
        if self._server is not None and self._server.running:
            self._open_url(self._server.url)

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self) -> None:
        if self.tray is not None:
            self.hide()
        else:
            self.showMinimized()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window()

    def quit(self) -> None:
        self._status_timer.stop()
        self._stop()
        self._engine.stop()
        if self.tray is not None:
            self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.quit()
        event.accept()


def run_launcher(engine: EngineLike, host: str, port: int) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    window = LauncherWindow(engine, host, port)
    window.show()
    return app.exec()
