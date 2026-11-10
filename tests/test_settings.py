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
