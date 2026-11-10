import builtins
import socket
import sys

from track_glow.cli import main, parse_args


def test_defaults_desktop():
    a = parse_args([])
    assert (a.headless, a.host, a.port) == (False, "127.0.0.1", 8780)


def test_defaults_headless():
    a = parse_args(["--headless"])
    assert (a.host, a.port) == ("0.0.0.0", 8780)


def test_explicit_host_port_win():
    a = parse_args(["--headless", "--host", "127.0.0.1", "--port", "9000"])
    assert (a.host, a.port) == ("127.0.0.1", 9000)


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
