from fastapi.testclient import TestClient

from track_glow import __version__
from track_glow.web import create_app


def client(engine) -> TestClient:
    return TestClient(create_app(engine))


def test_health_reports_ok_and_version(fake_engine):
    r = client(fake_engine).get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


def test_index_is_placeholder_page(fake_engine):
    r = client(fake_engine).get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Track Glow" in r.text and "No race" in r.text


def test_index_has_state_polling(fake_engine):
    assert "/api/state" in client(fake_engine).get("/").text


def test_state_no_race(fake_engine):
    s = client(fake_engine).get("/api/state").json()
    assert s["flag"] is None and s["flag_label"] is None and s["lap"] is None
    assert s["feed"] == {"health": "connecting", "message": "", "failures": 0}
    assert s["follow"] == "Cup" and s["source"] == "live"
    assert s["status"] == "No race"


def test_state_green_cup(green_engine):
    s = client(green_engine).get("/api/state").json()
    assert s == {
        "flag": "green",
        "flag_label": "GREEN",
        "flag_color": "#2e7d32",
        "series": "Cup",
        "lap": 112,
        "laps_in_race": 267,
        "track_name": "Phoenix Raceway",
        "run_name": "NASCAR Cup Series Championship",
        "feed": {"health": "ok", "message": "", "failures": 0},
        "follow": "Cup",
        "waiting_for_series": None,
        "override": None,
        "source": "live",
        "status": "GREEN · Cup · Lap 112/267",
    }


def test_override_post_sets_and_clears(green_engine):
    c = client(green_engine)
    r = c.post("/api/override", json={"flag": "red"})
    assert r.status_code == 200 and r.json()["flag"] == "red" and r.json()["override"] == "red"
    r = c.post("/api/override", json={"flag": None})
    assert r.json()["flag"] == "green" and r.json()["override"] is None


def test_override_unknown_flag_422(green_engine):
    assert client(green_engine).post("/api/override", json={"flag": "purple"}).status_code == 422


def test_index_resets_display_when_unreachable(fake_engine):
    html = client(fake_engine).get("/").text
    assert "Not connected" in html and "r.ok" in html
