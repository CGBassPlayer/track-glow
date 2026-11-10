import builtins
import socket
import sys

import pytest

from track_glow import cli, launcher
from track_glow.cli import main


@pytest.fixture
def calls(monkeypatch):
    recorded = []
    monkeypatch.setattr(cli, "has_display", lambda: True)
    monkeypatch.setattr(cli, "_run_headless", lambda h, p: recorded.append(("headless", h, p)) or 0)
    monkeypatch.setattr(
        launcher, "run_launcher", lambda h, p: recorded.append(("desktop", h, p)) or 0
    )
    return recorded


def test_defaults_desktop(calls):
    assert main([]) == 0
    assert calls == [("desktop", "127.0.0.1", 8780)]


def test_defaults_headless(calls):
    assert main(["--headless"]) == 0
    assert calls == [("headless", "0.0.0.0", 8780)]


def test_explicit_host_port_win(calls):
    assert main(["--headless", "--host", "127.0.0.1", "--port", "9000"]) == 0
    assert calls == [("headless", "127.0.0.1", 9000)]


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
