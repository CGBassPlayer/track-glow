import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from conftest import GREEN_CUP, FakeEngine  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from track_glow.engine import EngineState  # noqa: E402
from track_glow.launcher import LauncherWindow  # noqa: E402
from track_glow.models import FeedStatus, Flag, Series  # noqa: E402
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


def make(qtbot, host="127.0.0.1", port=8780, engine=None):
    engine = engine or FakeEngine()
    w = LauncherWindow(engine, host, port, FakeServer, opened.append, tray_available=False)
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


def test_status_follows_engine(qtbot):
    engine = FakeEngine()
    w = make(qtbot, engine=engine)
    assert w.status_label.text() == "No race"
    engine.state = EngineState(race=GREEN_CUP, feed=FeedStatus("ok"), follow=Series.CUP)
    w.refresh_status()
    assert w.status_label.text() == "GREEN · Cup · Lap 112/267"
    assert Flag.GREEN.color in w.flag_swatch.styleSheet()


def test_status_offline_resets_swatch(qtbot):
    engine = FakeEngine(EngineState(race=GREEN_CUP, feed=FeedStatus("ok")))
    w = make(qtbot, engine=engine)
    w.refresh_status()
    engine.state = EngineState(feed=FeedStatus("offline"))
    w.refresh_status()
    assert w.status_label.text() == "Feed offline"
    assert "#9e9e9e" in w.flag_swatch.styleSheet()


def test_quit_stops_engine(qtbot, monkeypatch):
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    engine = FakeEngine()
    w = make(qtbot, engine=engine)
    w.quit_button.click()
    assert engine.stopped


def test_lights_line_summarizes_status(qtbot):
    from conftest import FakeLights

    from track_glow.outputs.wled import ControllerStatus

    lights = FakeLights(
        [
            ControllerStatus("10.0.0.5", 60, "ok"),
            ControllerStatus("10.0.0.6", None, "error", "Can't reach WLED at 10.0.0.6"),
        ]
    )
    w = LauncherWindow(
        FakeEngine(),
        "127.0.0.1",
        8780,
        FakeServer,
        opened.append,
        tray_available=False,
        lights=lights,
    )
    qtbot.addWidget(w)
    assert w.lights_label.text() == "Lights: 1/2 ok — Can't reach WLED at 10.0.0.6"
    lights.statuses = [ControllerStatus("10.0.0.5", 60, "ok")]
    w.refresh_status()
    assert w.lights_label.text() == "Lights: 1/1 ok"


def test_no_lights_line_without_output(qtbot):
    w = make(qtbot)
    assert w.lights_label.isHidden()


def test_lights_summary_includes_bar():
    from track_glow.launcher import lights_summary
    from track_glow.outputs.wled import BarStatus, ControllerStatus

    ok = [ControllerStatus("10.0.0.5", 60, "ok")]
    assert lights_summary(ok, BarStatus("off")) == "Lights: 1/1 ok"
    assert lights_summary(ok, BarStatus("ok", "", 0, 10, 0.504)) == "Lights: 1/1 ok · Bar 50%"
    waiting = BarStatus("waiting", "Waiting for b")
    assert lights_summary(ok, waiting) == "Lights: 1/1 ok · Bar: Waiting for b"
    err = BarStatus("error", "WLED at b has no segment 9")
    assert lights_summary(ok, err) == "Lights: 1/1 ok · Bar: WLED at b has no segment 9"


def test_lights_line_includes_bar(qtbot):
    from conftest import FakeLights

    from track_glow.outputs.wled import BarStatus

    lights = FakeLights(bar=BarStatus("ok", "", 0, 10, 0.25))
    w = LauncherWindow(
        FakeEngine(),
        "127.0.0.1",
        8780,
        FakeServer,
        opened.append,
        tray_available=False,
        lights=lights,
    )
    qtbot.addWidget(w)
    assert w.lights_label.text() == "Lights: 1/1 ok · Bar 25%"
