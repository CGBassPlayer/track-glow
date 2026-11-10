import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from track_glow.launcher import LauncherWindow  # noqa: E402
from track_glow.server import ServerStartError  # noqa: E402


class FakeServer:
    instances: list["FakeServer"] = []

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.running = False
        FakeServer.instances.append(self)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        if self.port == 1:
            raise ServerStartError(f"Can't listen on {self.host}:{self.port}")
        self.running = True

    def stop(self) -> None:
        self.running = False


opened: list[str] = []


@pytest.fixture(autouse=True)
def reset():
    FakeServer.instances.clear()
    opened.clear()


def make(qtbot, host="127.0.0.1", port=8780):
    w = LauncherWindow(host, port, FakeServer, opened.append, tray_available=False)
    qtbot.addWidget(w)
    return w


def test_starts_server_and_shows_url(qtbot):
    w = make(qtbot)
    assert FakeServer.instances[-1].running
    assert "http://127.0.0.1:8780" in w.url_label.text()
    assert w.status_label.text() == "No race"


def test_open_web_ui_opens_server_url(qtbot):
    w = make(qtbot)
    w.open_button.click()
    assert opened == ["http://127.0.0.1:8780"]


def test_apply_restarts_on_new_port(qtbot):
    w = make(qtbot)
    old = FakeServer.instances[-1]
    w.port_spin.setValue(9000)
    w.apply_button.click()
    assert not old.running
    assert FakeServer.instances[-1].port == 9000
    assert FakeServer.instances[-1].running
    assert "http://127.0.0.1:9000" in w.url_label.text()


def test_apply_switches_host(qtbot):
    w = make(qtbot)
    w.host_combo.setCurrentIndex(w.host_combo.findData("0.0.0.0"))
    w.apply_button.click()
    assert FakeServer.instances[-1].host == "0.0.0.0"


def test_host_combo_selects_initial_host(qtbot):
    w = make(qtbot, host="0.0.0.0")
    assert w.host_combo.currentData() == "0.0.0.0"


def test_start_error_shown_and_open_disabled(qtbot):
    w = make(qtbot, port=1)
    assert "Can't listen" in w.url_label.text()
    assert not w.open_button.isEnabled()


def test_apply_after_error_recovers(qtbot):
    w = make(qtbot, port=1)
    w.port_spin.setValue(8781)
    w.apply_button.click()
    assert w.open_button.isEnabled()
    assert "http://127.0.0.1:8781" in w.url_label.text()


def test_hide_without_tray_minimizes(qtbot):
    w = make(qtbot)
    w.show()
    w.hide_button.click()
    assert w.isMinimized() or w.windowState() & Qt.WindowMinimized


def test_quit_stops_server(qtbot, monkeypatch):
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    w = make(qtbot)
    w.quit_button.click()
    assert not FakeServer.instances[-1].running


def test_close_quits(qtbot, monkeypatch):
    quits = []
    monkeypatch.setattr(QApplication, "quit", lambda: quits.append(True))
    w = make(qtbot)
    w.show()
    w.close()
    assert quits
    assert not FakeServer.instances[-1].running
