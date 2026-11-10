import json
import os
import sys

import pytest

from track_glow import settings as settings_mod
from track_glow.settings import Settings, SettingsError, default_path, load, save
from track_glow.wled import ControllerSpec, ProgressSpec


def test_defaults_round_trip():
    s = Settings()
    d = s.to_dict()
    assert d == {
        "version": 1,
        "series": "cup",
        "source": "live",
        "controllers": [],
        "progress": None,
        "offline": "amber",
    }
    assert Settings.from_dict(d) == s


def test_to_dict_controllers_is_list():
    s = Settings(controllers=("a:10", "b"))
    assert s.to_dict()["controllers"] == ["a:10", "b"]
    assert Settings.from_dict(s.to_dict()) == s


def test_from_dict_ignores_unknown_keys():
    s = Settings.from_dict({"series": "truck", "bogus": 1, "version": 1})
    assert s == Settings(series="truck")


def test_from_dict_missing_keys_use_defaults():
    assert Settings.from_dict({}) == Settings()


@pytest.mark.parametrize(
    "field,value",
    [("series", "nascar"), ("source", "tape"), ("offline", "off"), ("series", 3)],
)
def test_enum_rejects_bad_value(field, value):
    with pytest.raises(SettingsError) as e:
        Settings.from_dict({field: value})
    assert e.value.field == field
    assert str(e.value) == e.value.message


@pytest.mark.parametrize("series", ["cup", "xfinity", "truck", "any"])
def test_series_values_accepted(series):
    assert Settings(series=series).series == series
    Settings(series=series).validate()


def test_bad_controller_names_value():
    with pytest.raises(SettingsError) as e:
        Settings.from_dict({"controllers": ["good", "bad:x"]})
    assert e.value.field == "controllers"
    assert "Invalid controller" in e.value.message
    assert "'bad:x'" in e.value.message


@pytest.mark.parametrize("value", ["a", [1], None])
def test_controllers_bad_type(value):
    with pytest.raises(SettingsError) as e:
        Settings.from_dict({"controllers": value})
    assert e.value.field == "controllers"


def test_duplicate_controller_host():
    with pytest.raises(SettingsError) as e:
        Settings(controllers=("a:10", "a:20")).validate()
    assert e.value.field == "controllers"
    assert "a" in e.value.message


def test_progress_without_controllers():
    with pytest.raises(SettingsError) as e:
        Settings(progress="0-10").validate()
    assert e.value.field == "progress"
    assert e.value.message == "Progress bar needs at least one controller"


def test_progress_segment_host_not_controller():
    with pytest.raises(SettingsError) as e:
        Settings(controllers=("a",), progress="b/0").validate()
    assert e.value.field == "progress"
    assert "b" in e.value.message


def test_progress_segment_host_is_controller():
    Settings(controllers=("a:30",), progress="a/1").validate()


def test_progress_bad_syntax():
    with pytest.raises(SettingsError) as e:
        Settings(controllers=("a",), progress="nope").validate()
    assert e.value.field == "progress"
    assert "Invalid progress" in e.value.message
    assert "'nope'" in e.value.message


def test_progress_bad_type():
    with pytest.raises(SettingsError) as e:
        Settings.from_dict({"controllers": ["a"], "progress": 5})
    assert e.value.field == "progress"


def test_merged_unknown_key():
    with pytest.raises(SettingsError) as e:
        Settings().merged({"colour": "red"})
    assert e.value.field == "colour"
    assert e.value.message == "Unknown setting colour"


def test_merged_partial_keeps_other_fields():
    s = Settings(series="truck", controllers=("a",), offline="hold")
    m = s.merged({"source": "replay"})
    assert m == Settings(series="truck", source="replay", controllers=("a",), offline="hold")


def test_merged_validates():
    with pytest.raises(SettingsError) as e:
        Settings().merged({"progress": "0-10"})
    assert e.value.field == "progress"


def test_merged_controllers_list_becomes_tuple():
    assert Settings().merged({"controllers": ["a"]}).controllers == ("a",)


def test_specs_and_progress_spec():
    s = Settings(controllers=("a:10", "b"), progress="2-8")
    assert s.specs() == [ControllerSpec("a", 10), ControllerSpec("b")]
    assert s.progress_spec() == ProgressSpec(start=2, stop=8)
    assert Settings().progress_spec() is None


def test_default_path_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACK_GLOW_CONFIG", str(tmp_path / "x.json"))
    assert default_path() == tmp_path / "x.json"


def test_default_path_platformdirs(monkeypatch, tmp_path):
    monkeypatch.delenv("TRACK_GLOW_CONFIG", raising=False)
    monkeypatch.setattr(settings_mod, "user_config_dir", lambda app: str(tmp_path / app))
    assert default_path() == tmp_path / "track-glow" / "settings.json"


def test_load_missing(tmp_path):
    assert load(tmp_path / "none.json") == (Settings(), None)


def test_load_corrupt_json(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    s, warning = load(path)
    assert s == Settings()
    assert warning is not None
    assert str(path) in warning
    assert warning.endswith("using defaults. Saving will replace it.")
    assert path.read_text() == "{not json"


def test_load_non_object_json(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("[1, 2]")
    s, warning = load(path)
    assert s == Settings()
    assert warning is not None


def test_load_invalid_value(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"series": "nascar"}))
    s, warning = load(path)
    assert s == Settings()
    assert warning is not None and str(path) in warning


def test_load_unreadable(tmp_path):
    path = tmp_path / "dir.json"
    path.mkdir()
    s, warning = load(path)
    assert s == Settings()
    assert warning is not None


def test_save_load_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(
        series="any", source="replay", controllers=("a:10", "b"), progress="b/2", offline="hold"
    )
    save(path, s)
    assert load(path) == (s, None)
    assert json.loads(path.read_text())["version"] == 1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_save_mode_0600(tmp_path):
    path = tmp_path / "settings.json"
    save(path, Settings())
    assert path.stat().st_mode & 0o777 == 0o600


def test_save_creates_parents(tmp_path):
    path = tmp_path / "a" / "b" / "settings.json"
    save(path, Settings())
    assert load(path) == (Settings(), None)


def test_save_is_atomic(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    save(path, Settings(series="truck"))
    original = path.read_text()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        save(path, Settings(series="xfinity"))
    assert path.read_text() == original
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


def test_save_overwrites_existing(tmp_path):
    path = tmp_path / "settings.json"
    save(path, Settings(series="truck"))
    save(path, Settings(series="xfinity"))
    assert load(path)[0].series == "xfinity"


def _service(tmp_path, settings=None, warning=None):
    from conftest import FakeEngine, FakeLights

    from track_glow.settings import SettingsService

    engine, lights = FakeEngine(), FakeLights()
    built = []

    def build(kind, follow):
        built.append((kind, follow))
        return f"source:{kind}"

    svc = SettingsService(
        tmp_path / "s.json",
        settings or Settings(),
        engine,
        lights,
        build_source=build,
        warning=warning,
    )
    return svc, engine, lights, built


def test_service_series_change_reconfigures_engine_only(tmp_path):
    from track_glow.models import Series

    svc, engine, lights, built = _service(tmp_path)
    assert svc.update({"series": "truck"}).series == "truck"
    assert built == [("live", Series.TRUCK)]
    assert engine.configured == [("source:live", Series.TRUCK, "live")]
    assert not hasattr(lights, "configured")


def test_service_source_any_series_follows_none(tmp_path):
    svc, engine, lights, built = _service(tmp_path)
    svc.update({"source": "replay", "series": "any"})
    assert built == [("replay", None)]


def test_service_controllers_change_reconfigures_lights_only(tmp_path):
    from track_glow.wled import ControllerSpec, ProgressSpec

    svc, engine, lights, built = _service(tmp_path)
    svc.update({"controllers": ["a:10", "b"], "progress": "a/1", "offline": "hold"})
    assert lights.configured == [
        ([ControllerSpec("a", 10), ControllerSpec("b", None)], ProgressSpec.parse("a/1"), True)
    ]
    assert not hasattr(engine, "configured")


def test_service_invalid_patch_applies_and_saves_nothing(tmp_path):
    svc, engine, lights, built = _service(tmp_path)
    with pytest.raises(SettingsError) as e:
        svc.update({"series": "f1", "controllers": ["a"]})
    assert e.value.field == "series"
    assert svc.get() == Settings()
    assert not (tmp_path / "s.json").exists()
    assert built == [] and not hasattr(lights, "configured")


def test_service_saves_and_clears_warning(tmp_path):
    svc, *_ = _service(tmp_path, warning="bad file")
    svc.update({"offline": "hold"})
    assert load(tmp_path / "s.json") == (Settings(offline="hold"), None)
    assert svc.warning is None


def test_service_save_failure_still_applies_and_warns(tmp_path, monkeypatch):
    import track_glow.settings as mod

    def boom(path, settings):
        raise OSError("disk full")

    monkeypatch.setattr(mod, "save", boom)
    svc, engine, lights, built = _service(tmp_path)
    assert svc.update({"series": "truck"}).series == "truck"
    assert svc.get().series == "truck"
    assert svc.warning == "Applied, but couldn't save settings: disk full"


def test_hosts_compared_case_insensitively():
    with pytest.raises(SettingsError, match="more than once"):
        Settings().merged({"controllers": ["A", "a:5"]})
    assert Settings().merged({"controllers": ["A:5"], "progress": "a/1"}).progress == "a/1"


def test_empty_controller_rejected():
    with pytest.raises(SettingsError) as e:
        Settings().merged({"controllers": [""]})
    assert e.value.field == "controllers"


def test_merged_ignores_version():
    s = Settings(series="truck")
    assert s.merged(s.to_dict()) == s


def test_service_moves_bad_file_aside_before_first_save(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"controllers": ["10.0.0.5:60",]}')
    settings, warning = load(path)
    svc, *_ = _service(tmp_path, settings=settings, warning=warning)
    svc.update({"source": "replay"})
    assert (tmp_path / "s.json.bad").read_text() == '{"controllers": ["10.0.0.5:60",]}'
    assert load(path)[0].source == "replay"
    assert svc.warning == f"Your old settings file was invalid; it was kept as {path}.bad"
    svc.update({"series": "truck"})
    assert svc.warning is None


def test_service_noop_patch_does_not_save(tmp_path):
    svc, *_ = _service(tmp_path)
    svc.update({})
    assert not (tmp_path / "s.json").exists()
