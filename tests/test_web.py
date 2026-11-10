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
        "mode": "on",
        "status": "GREEN · Cup · Lap 112/267",
        "lights": [],
        "progress": None,
        "home_assistant": None,
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


def test_state_includes_lights(fake_engine):
    from conftest import FakeLights

    from track_glow.outputs.wled import ControllerStatus

    lights = FakeLights(
        [ControllerStatus("10.0.0.5", 60, "ok"), ControllerStatus("10.0.0.6", None, "error", "x")]
    )
    s = TestClient(create_app(fake_engine, lights)).get("/api/state").json()
    assert s["lights"] == [
        {"host": "10.0.0.5", "led_count": 60, "state": "ok", "message": ""},
        {"host": "10.0.0.6", "led_count": None, "state": "error", "message": "x"},
    ]


def test_state_lights_empty_without_output(fake_engine):
    assert client(fake_engine).get("/api/state").json()["lights"] == []


def test_frame_endpoint_hex(fake_engine):
    from conftest import FakeLights

    lights = FakeLights(frame=bytes([0, 255, 0, 0, 0, 0]))
    r = TestClient(create_app(fake_engine, lights)).get("/api/frame").json()
    assert r == {"pixels": "00ff00000000", "led_count": 2}


def test_frame_empty_without_output(fake_engine):
    assert client(fake_engine).get("/api/frame").json() == {"pixels": "", "led_count": 0}


def test_index_has_strip_preview(fake_engine):
    html = client(fake_engine).get("/").text
    assert 'id="strip"' in html and "/api/frame" in html


def test_strip_preview_polls_faster_than_flash_and_never_overlaps(fake_engine):
    html = client(fake_engine).get("/").text
    assert "setTimeout(drawStrip, FRAME_MS)" in html and "const FRAME_MS = 100" in html
    assert "setInterval(drawStrip" not in html


def test_state_includes_progress(fake_engine):
    from conftest import FakeLights

    from track_glow.outputs.wled import BarStatus

    lights = FakeLights(bar=BarStatus("ok", "", 10, 20, 0.5))
    s = TestClient(create_app(fake_engine, lights)).get("/api/state").json()
    assert s["progress"] == {
        "state": "ok",
        "message": "",
        "start": 10,
        "stop": 20,
        "fraction": 0.5,
    }


def test_state_progress_null_without_lights(fake_engine):
    assert client(fake_engine).get("/api/state").json()["progress"] is None


def test_page_shows_bar_status(fake_engine):
    html = client(fake_engine).get("/").text
    assert "s.progress" in html and "Bar " in html


def _settings_client(tmp_path, fake_engine, warning=None):
    from conftest import FakeLights

    from track_glow.settings import Settings, SettingsService

    lights = FakeLights()
    svc = SettingsService(
        tmp_path / "s.json",
        Settings(),
        fake_engine,
        lights,
        build_source=lambda k, f: None,
        warning=warning,
    )
    return TestClient(create_app(fake_engine, lights, svc))


def test_get_settings_with_warning(tmp_path, fake_engine):
    r = _settings_client(tmp_path, fake_engine, warning="bad file").get("/api/settings").json()
    assert r["warning"] == "bad file"
    assert r["settings"]["series"] == "cup" and r["settings"]["controllers"] == []


def test_patch_settings_ok(tmp_path, fake_engine):
    c = _settings_client(tmp_path, fake_engine)
    r = c.patch("/api/settings", json={"controllers": ["10.0.0.5:60"], "progress": "0-10"})
    assert r.status_code == 200
    assert r.json()["settings"]["controllers"] == ["10.0.0.5:60"]
    assert c.get("/api/settings").json()["settings"]["progress"] == "0-10"


def test_patch_settings_invalid_422(tmp_path, fake_engine):
    r = _settings_client(tmp_path, fake_engine).patch(
        "/api/settings", json={"controllers": ["x:abc"]}
    )
    assert r.status_code == 422
    body = r.json()
    assert body["field"] == "controllers" and "x:abc" in body["error"]


def test_patch_settings_unknown_key_422(tmp_path, fake_engine):
    r = _settings_client(tmp_path, fake_engine).patch("/api/settings", json={"nope": 1})
    assert r.status_code == 422 and r.json()["field"] == "nope"


def test_patch_settings_non_object_422(tmp_path, fake_engine):
    r = _settings_client(tmp_path, fake_engine).patch("/api/settings", json=[1])
    assert r.status_code == 422


def test_settings_404_without_service(fake_engine):
    c = client(fake_engine)
    assert c.get("/api/settings").status_code == 404
    assert c.patch("/api/settings", json={}).status_code == 404


def test_post_mode(fake_engine):
    c = client(fake_engine)
    r = c.post("/api/mode", json={"mode": "blackout"})
    assert r.status_code == 200 and r.json()["mode"] == "blackout"
    assert c.get("/api/state").json()["mode"] == "blackout"
    assert c.post("/api/mode", json={"mode": "disco"}).status_code == 422


def test_dashboard_has_controls(fake_engine):
    html = client(fake_engine).get("/").text
    for hook in ('id="controls"', "/api/mode", '"PATCH"', 'id="warning"'):
        assert hook in html, hook
    for flag in ("green", "yellow", "red", "white", "checkered"):
        assert f'"key": "{flag}"' in html
    for mode in ("on", "paused", "blackout"):
        assert f'data-mode="{mode}"' in html


def test_dashboard_has_no_settings_form(fake_engine):
    html = client(fake_engine).get("/").text
    assert 'id="settings-form"' not in html
    assert 'href="/settings"' in html
    assert '<a href="/" aria-current="page">' in html


def test_settings_page_served(fake_engine):
    r = client(fake_engine).get("/settings")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    for hook in ('id="settings-form"', 'id="ha-scenes"', '"PATCH"', 'id="warning"'):
        assert hook in r.text, hook
    assert '<a href="/settings" aria-current="page">' in r.text
    assert 'id="controls"' not in r.text


def test_pages_follow_color_scheme(fake_engine):
    c = client(fake_engine)
    for path in ("/", "/settings"):
        assert "color-scheme: light dark" in c.get(path).text, path


def test_page_only_says_saved_without_warning(fake_engine):
    html = client(fake_engine).get("/settings").text
    assert 'ok && !lastWarning ? "Saved"' in html


class _FakeHa:
    def __init__(self):
        from track_glow.outputs.ha import HaStatus

        self.st = HaStatus("ok", "", "scene.green")
        self.configured = []

    def ha_status(self):
        return self.st

    def configure(self, **kw):
        self.configured.append(kw)


def _ha_client(tmp_path, fake_engine, settings=None):
    from conftest import FakeLights

    from track_glow.settings import Settings, SettingsService

    svc = SettingsService(
        tmp_path / "s.json",
        settings or Settings(),
        fake_engine,
        FakeLights(),
        build_source=lambda k, f: None,
        ha=_FakeHa(),
    )
    return TestClient(create_app(fake_engine, FakeLights(), svc)), svc


def test_state_includes_home_assistant(tmp_path, fake_engine):
    c, _ = _ha_client(tmp_path, fake_engine)
    assert c.get("/api/state").json()["home_assistant"] == {
        "state": "ok",
        "message": "",
        "scene": "scene.green",
    }
    assert client(fake_engine).get("/api/state").json()["home_assistant"] is None


def test_settings_never_return_token(tmp_path, fake_engine):
    from track_glow.settings import Settings

    c, svc = _ha_client(
        tmp_path, fake_engine, Settings(ha_url="http://ha:8123", ha_token="s3cret-tkn")
    )
    r = c.get("/api/settings")
    assert "s3cret-tkn" not in r.text
    assert r.json()["settings"]["ha_token_set"] is True
    r = c.patch("/api/settings", json={"ha_url": "http://ha2:8123", "ha_token": ""})
    assert r.status_code == 200 and "s3cret-tkn" not in r.text
    assert svc.get().ha_token == "s3cret-tkn"
    assert "s3cret-tkn" not in c.get("/api/state").text


def test_ha_test_not_configured(tmp_path, fake_engine):
    c, _ = _ha_client(tmp_path, fake_engine)
    assert c.post("/api/ha/test").json() == {"ok": False, "error": "Set the URL and token first"}


def test_ha_test_ok_and_error(tmp_path, fake_engine, monkeypatch):
    import track_glow.web as web
    from track_glow.ha import HaError
    from track_glow.settings import Settings

    made = []

    class Fake:
        fail = None

        def __init__(self, url, token, verify_tls=True):
            made.append((url, token, verify_tls))

        def check(self):
            if Fake.fail:
                raise HaError(Fake.fail)

        def list_scenes(self):
            return [{"id": "scene.a", "name": "A"}, {"id": "scene.b", "name": "B"}]

        def close(self):
            pass

    monkeypatch.setattr(web, "HaClient", Fake)
    c, _ = _ha_client(tmp_path, fake_engine, Settings(ha_url="http://ha:8123", ha_token="t"))
    assert c.post("/api/ha/test").json() == {
        "ok": True,
        "scenes": [{"id": "scene.a", "name": "A"}, {"id": "scene.b", "name": "B"}],
    }
    assert made == [("http://ha:8123", "t", True)]
    Fake.fail = "Home Assistant rejected the access token"
    assert c.post("/api/ha/test").json() == {
        "ok": False,
        "error": "Home Assistant rejected the access token",
    }


def test_page_has_home_assistant_card(fake_engine):
    html = client(fake_engine).get("/settings").text
    for hook in ('id="ha-url"', 'id="ha-token"', "/api/ha/test", 'id="ha-scenes"'):
        assert hook in html, hook


def test_page_ha_test_handles_errors(fake_engine):
    html = client(fake_engine).get("/settings").text
    assert 'out.textContent = "Test failed' in html
