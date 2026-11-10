import builtins
import socket
import sys

import pytest

from track_glow import cli, launcher
from track_glow.cli import main
from track_glow.engine import Engine
from track_glow.models import Series
from track_glow.outputs.wled import WledOutput
from track_glow.sources import build_source
from track_glow.sources.nascar import NascarFeedSource
from track_glow.sources.replay import ReplaySource


@pytest.fixture(autouse=True)
def settings_file(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    monkeypatch.setenv("TRACK_GLOW_CONFIG", str(path))
    return path


class Calls(list):
    service = None


@pytest.fixture(autouse=True)
def no_engine_thread(monkeypatch):
    monkeypatch.setattr(Engine, "start", lambda self: None)
    monkeypatch.setattr(WledOutput, "start", lambda self: None)
    from track_glow.outputs.ha import HomeAssistantOutput

    monkeypatch.setattr(HomeAssistantOutput, "start", lambda self: None)


@pytest.fixture
def calls(monkeypatch):
    recorded = Calls()

    def record(mode):
        def run(engine, h, p, lights=None, settings=None):
            snap = engine.snapshot()
            recorded.append((mode, h, p, snap.source_kind, snap.follow))
            recorded.service = settings
            if lights is not None and lights.status():
                recorded.append(("lights", [(c.host, c.led_count) for c in lights.status()]))
                recorded.append(("bar", lights.bar_status().state != "off"))
            return 0

        return run

    monkeypatch.setattr(cli, "has_display", lambda: True)
    monkeypatch.setattr(cli, "_run_headless", record("headless"))
    monkeypatch.setattr(launcher, "run_launcher", record("desktop"))
    return recorded


def test_defaults_desktop(calls):
    assert main([]) == 0
    assert calls == [("desktop", "127.0.0.1", 8780, "live", Series.CUP)]


def test_defaults_headless(calls):
    assert main(["--headless"]) == 0
    assert calls == [("headless", "0.0.0.0", 8780, "live", Series.CUP)]


def test_explicit_host_port_win(calls):
    assert main(["--headless", "--host", "127.0.0.1", "--port", "9000"]) == 0
    assert calls == [("headless", "127.0.0.1", 9000, "live", Series.CUP)]


@pytest.mark.parametrize("port", ["0", "70000"])
def test_port_out_of_range_rejected(calls, capsys, port):
    assert main(["--headless", "--port", port]) == 2
    assert calls == []


def test_help_exits_0(capsys):
    assert main(["--help"]) == 0
    assert "--headless" in capsys.readouterr().out


def fail_launcher_import(monkeypatch, error: ImportError) -> None:
    monkeypatch.setenv("DISPLAY", ":0")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "track_glow.launcher":
            raise error
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_missing_pyside_prints_hint(monkeypatch, capsys):
    fail_launcher_import(
        monkeypatch, ModuleNotFoundError("No module named 'PySide6'", name="PySide6")
    )
    assert main([]) == 1
    assert "track-glow[desktop]" in capsys.readouterr().err


def test_broken_desktop_import_shows_real_error(monkeypatch, capsys):
    fail_launcher_import(monkeypatch, ImportError("libEGL.so.1: cannot open shared object file"))
    assert main([]) == 1
    err = capsys.readouterr().err
    assert "libEGL.so.1" in err and "track-glow[desktop]" not in err


def test_no_display_on_linux_suggests_headless(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    for var in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"):
        monkeypatch.delenv(var, raising=False)
    assert main([]) == 1
    assert "--headless" in capsys.readouterr().err


def test_headless_port_in_use_exits_1(capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert main(["--headless", "--host", "127.0.0.1", "--port", str(s.getsockname()[1])]) == 1
    assert "Can't listen" in capsys.readouterr().err


def test_series_and_replay_flags(calls):
    assert main(["--headless", "--replay", "--series", "xfinity"]) == 0
    assert calls == [("headless", "0.0.0.0", 8780, "replay", Series.XFINITY)]


def test_series_any_means_none(calls):
    assert main(["--headless", "--series", "any"]) == 0
    assert calls[0][4] is None


def test_bad_series_exit_2(calls):
    assert main(["--headless", "--series", "f1"]) == 2
    assert calls == []


def test_build_source_kinds():
    assert isinstance(build_source("live", Series.CUP), NascarFeedSource)
    replay = build_source("replay", None)
    assert isinstance(replay, ReplaySource) and replay.fetch().series is Series.CUP
    assert build_source("replay", Series.TRUCK).fetch().series is Series.TRUCK


def test_wled_specs_build_output(calls):
    assert main(["--headless", "--wled", "10.0.0.5:60", "--wled", "wled.local"]) == 0
    assert calls[1] == ("lights", [("10.0.0.5", 60), ("wled.local", None)])


def test_no_wled_means_no_output(calls):
    assert main(["--headless"]) == 0
    assert len(calls) == 1


def test_bad_wled_spec_exit_2(calls, capsys):
    assert main(["--headless", "--wled", "10.0.0.5:abc"]) == 2
    assert calls == []
    assert "10.0.0.5:abc" in capsys.readouterr().err


def test_progress_passed_to_output(calls):
    assert main(["--headless", "--wled", "10.0.0.5:60", "--progress", "10-20"]) == 0
    assert ("bar", True) in calls


def test_no_progress_means_bar_off(calls):
    assert main(["--headless", "--wled", "10.0.0.5:60"]) == 0
    assert ("bar", False) in calls


def test_bad_progress_exit_2(calls, capsys):
    assert main(["--headless", "--wled", "10.0.0.5:60", "--progress", "20-10"]) == 2
    assert calls == []
    assert "--progress: Invalid progress value" in capsys.readouterr().err


def test_progress_without_wled_exit_2(calls, capsys):
    assert main(["--headless", "--progress", "10-20"]) == 2
    assert calls == []
    assert "--progress: Progress bar needs at least one controller" in capsys.readouterr().err


def test_settings_file_used_without_flags(calls, settings_file):
    from track_glow.settings import Settings, save

    save(settings_file, Settings(series="truck", source="replay", controllers=("10.0.0.5:60",)))
    assert main(["--headless"]) == 0
    assert calls[0] == ("headless", "0.0.0.0", 8780, "replay", Series.TRUCK)
    assert calls[1] == ("lights", [("10.0.0.5", 60)])
    assert calls.service.get().series == "truck"
    assert calls.service.warning is None


def test_flags_override_file_for_this_run_only(calls, settings_file):
    from track_glow.settings import Settings, load, save

    saved = Settings(series="truck", controllers=("10.0.0.5:60",))
    save(settings_file, saved)
    assert main(["--headless", "--series", "xfinity", "--wled", "10.0.0.9:30"]) == 0
    assert calls[0][4] == Series.XFINITY
    assert calls[1] == ("lights", [("10.0.0.9", 30)])
    assert load(settings_file) == (saved, None)


def test_corrupt_settings_file_starts_with_warning(calls, settings_file):
    settings_file.write_text("{nope")
    assert main(["--headless"]) == 0
    assert calls[0] == ("headless", "0.0.0.0", 8780, "live", Series.CUP)
    assert "invalid" in calls.service.warning
    assert settings_file.read_text() == "{nope"


def test_duplicate_wled_host_exit_2(calls, capsys):
    assert main(["--headless", "--wled", "a", "--wled", "a:5"]) == 2
    assert calls == []
    assert "--wled: " in capsys.readouterr().err


def test_wled_override_drops_saved_segment_bar_of_missing_host(calls, settings_file, capsys):
    from track_glow.settings import Settings, save

    save(settings_file, Settings(controllers=("a:30",), progress="a/1"))
    assert main(["--headless", "--wled", "b:30"]) == 0
    assert calls[1] == ("lights", [("b", 30)])
    assert calls.service.get().progress is None
    assert "Ignoring saved progress bar a/1" in capsys.readouterr().err


def test_home_assistant_built_from_settings_and_stopped(calls, settings_file, monkeypatch):
    from track_glow.outputs.ha import HomeAssistantOutput
    from track_glow.settings import Settings, save

    stopped = []
    monkeypatch.setattr(HomeAssistantOutput, "stop", lambda self: stopped.append(self))
    save(
        settings_file,
        Settings(ha_url="http://ha:8123", ha_token="t", ha_scenes={"green": "scene.g"}),
    )
    assert main(["--headless"]) == 0
    ha = calls.service.ha
    assert ha.ha_status().state == "idle"
    assert ha._config.url == "http://ha:8123" and dict(ha._config.scenes) == {"green": "scene.g"}
    assert stopped == [ha]
