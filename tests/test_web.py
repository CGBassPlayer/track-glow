from fastapi.testclient import TestClient

from track_glow import __version__
from track_glow.web import create_app


def test_health_reports_ok_and_version():
    r = TestClient(create_app()).get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


def test_index_is_placeholder_page():
    r = TestClient(create_app()).get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Track Glow" in r.text and "No race" in r.text
