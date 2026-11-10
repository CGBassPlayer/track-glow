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


def test_missing_pyside_prints_hint(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "track_glow.launcher", None)
    assert main([]) == 1
    assert "track-glow[desktop]" in capsys.readouterr().err


def test_headless_port_in_use_exits_1(capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert main(["--headless", "--host", "127.0.0.1", "--port", str(s.getsockname()[1])]) == 1
    assert "Can't listen" in capsys.readouterr().err
