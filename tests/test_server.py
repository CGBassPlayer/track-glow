import socket

import httpx2
import pytest
from conftest import FakeEngine

from track_glow import server
from track_glow.server import ServerStartError, WebServer, display_host, lan_ip


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_start_serves_health_then_stop():
    srv = WebServer("127.0.0.1", free_port(), FakeEngine())
    srv.start()
    try:
        assert httpx2.get(f"{srv.url}/api/health").json()["status"] == "ok"
        assert httpx2.get(f"{srv.url}/api/state").json()["status"] == "No race"
    finally:
        srv.stop()
    assert not srv.running


def test_port_in_use_raises_start_error():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        with pytest.raises(ServerStartError, match="Can't listen"):
            WebServer("127.0.0.1", s.getsockname()[1], FakeEngine()).start()


def test_stop_twice_is_safe():
    srv = WebServer("127.0.0.1", free_port(), FakeEngine())
    srv.start()
    srv.stop()
    srv.stop()
    assert not srv.running


def test_display_host_replaces_wildcard(monkeypatch):
    monkeypatch.setattr(server, "lan_ip", lambda: "192.168.1.40")
    assert display_host("0.0.0.0") == "192.168.1.40"
    assert display_host("127.0.0.1") == "127.0.0.1"


def test_url_uses_display_host(monkeypatch):
    monkeypatch.setattr(server, "lan_ip", lambda: "192.168.1.40")
    assert WebServer("0.0.0.0", 8780, FakeEngine()).url == "http://192.168.1.40:8780"


def test_lan_ip_falls_back_on_oserror(monkeypatch):
    def boom(*a, **k):
        raise OSError

    monkeypatch.setattr(socket.socket, "connect", boom)
    assert lan_ip() == "127.0.0.1"
