import dataclasses
import json
import os
import re
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from urllib.parse import urlsplit

from platformdirs import user_config_dir

from track_glow.models import Flag, Series
from track_glow.sources import build_source as default_build_source
from track_glow.wled import ControllerSpec, ProgressSpec

VERSION = 1
_CHOICES = {
    "series": ("cup", "xfinity", "truck", "any"),
    "source": ("live", "replay"),
    "offline": ("amber", "hold"),
}
SCENE_LABELS = {
    **{f.key: f.label.split(" · ")[0].title() for f in Flag},
    "no_race": "No race",
    "offline": "Feed offline",
    "blackout": "Blackout",
}
SCENE_KEYS = tuple(SCENE_LABELS)
_SCENE_ID = re.compile(r"scene\.[a-z0-9_]+")
_HA_FIELDS = ("ha_url", "ha_token", "ha_verify_tls", "ha_scenes")


class SettingsError(Exception):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True)
class Settings:
    series: str = "cup"
    source: str = "live"
    controllers: tuple[str, ...] = ()
    progress: str | None = None
    offline: str = "amber"
    ha_url: str = ""
    ha_token: str = dataclasses.field(default="", repr=False)
    ha_verify_tls: bool = True
    ha_scenes: dict[str, str] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["controllers"] = list(self.controllers)
        return {"version": VERSION, **d}

    def public_dict(self) -> dict:
        return {**self.to_dict(), "ha_token": "", "ha_token_set": bool(self.ha_token)}

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        return cls()._with(d)

    def merged(self, patch: dict) -> "Settings":
        known = {f.name for f in fields(self)}
        patch = {k: v for k, v in patch.items() if k not in ("version", "ha_token_set")}
        for key in patch:
            if key not in known:
                raise SettingsError(key, f"Unknown setting {key}")
        if isinstance(patch.get("ha_token"), str):
            patch["ha_token"] = patch["ha_token"].strip()
            if not patch["ha_token"]:
                del patch["ha_token"]
        # The UI can't read the saved token back, so a new URL must not inherit it:
        # otherwise anyone who can PATCH the URL gets the token sent to their host.
        if (
            isinstance(patch.get("ha_url"), str)
            and "ha_token" not in patch
            and _normalize_url(patch["ha_url"]) not in ("", self.ha_url)
        ):
            patch["ha_token"] = ""
        return self._with(patch)

    def _with(self, d: dict) -> "Settings":
        changes = {f.name: d[f.name] for f in fields(self) if f.name in d}
        if "controllers" in changes:
            value = changes["controllers"]
            if not isinstance(value, list) or not all(isinstance(c, str) for c in value):
                raise SettingsError(
                    "controllers", "Controllers must be a list of HOST[:LEDS] strings"
                )
            changes["controllers"] = tuple(value)
        if "progress" in changes and not isinstance(changes["progress"], str | None):
            raise SettingsError("progress", "Progress must be START-STOP, HOST/SEG or empty")
        for name in ("ha_url", "ha_token"):
            if name in changes and not isinstance(changes[name], str):
                raise SettingsError(name, f"{name} must be a string")
        if "ha_verify_tls" in changes and not isinstance(changes["ha_verify_tls"], bool):
            raise SettingsError("ha_verify_tls", "ha_verify_tls must be true or false")
        if "ha_scenes" in changes:
            value = changes["ha_scenes"]
            if not isinstance(value, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items()
            ):
                raise SettingsError("ha_scenes", "Scenes must map scene keys to scene.* ids")
            changes["ha_scenes"] = {k: v for k, v in value.items() if v}
        if "ha_url" in changes:
            changes["ha_url"] = _normalize_url(changes["ha_url"])
        result = replace(self, **changes)
        result.validate()
        return result

    def validate(self) -> None:
        for field, choices in _CHOICES.items():
            value = getattr(self, field)
            if value not in choices:
                raise SettingsError(
                    field, f"Invalid {field} {value!r}; expected one of {', '.join(choices)}"
                )
        self._validate_ha()
        specs = self.specs()
        hosts = [s.host for s in specs]
        for host in hosts:
            if hosts.count(host) > 1:
                raise SettingsError("controllers", f"Controller {host} is listed more than once")
        if self.progress is None:
            return
        if not specs:
            raise SettingsError("progress", "Progress bar needs at least one controller")
        bar = self.progress_spec()
        if bar.host is not None and bar.host not in hosts:
            raise SettingsError(
                "progress", f"Progress bar host {bar.host} is not one of the controllers"
            )

    def _validate_ha(self) -> None:
        if self.ha_url:
            parts = urlsplit(self.ha_url)
            try:
                _ = parts.port
                valid = parts.scheme in ("http", "https") and bool(parts.hostname)
            except ValueError:
                valid = False
            if not valid:
                raise SettingsError(
                    "ha_url",
                    f"Invalid Home Assistant URL {self.ha_url!r}; expected http(s)://HOST[:PORT]",
                )
            if not self.ha_token:
                raise SettingsError("ha_token", "Home Assistant needs an access token")
        if self.ha_token and not (self.ha_token.isascii() and self.ha_token.isprintable()):
            raise SettingsError("ha_token", "Access token has invalid characters")
        for key, entity in self.ha_scenes.items():
            if key not in SCENE_KEYS:
                raise SettingsError("ha_scenes", f"Unknown scene key {key}")
            if not _SCENE_ID.fullmatch(entity):
                raise SettingsError(
                    "ha_scenes", f"Scene for {key} must start with 'scene.', got {entity!r}"
                )

    def specs(self) -> list[ControllerSpec]:
        try:
            return [ControllerSpec.parse(c) for c in self.controllers]
        except ValueError as e:
            raise SettingsError("controllers", f"Invalid controller value: {e}") from None

    def progress_spec(self) -> ProgressSpec | None:
        if self.progress is None:
            return None
        try:
            return ProgressSpec.parse(self.progress)
        except ValueError as e:
            raise SettingsError("progress", f"Invalid progress value: {e}") from None


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    scheme, sep, rest = url.partition("://")
    url = f"{scheme.lower()}://{rest}" if sep else f"http://{url}"
    return url.rstrip("/")


def default_path() -> Path:
    env = os.environ.get("TRACK_GLOW_CONFIG")
    if env:
        return Path(env)
    return Path(user_config_dir("track-glow")) / "settings.json"


def load(path: Path) -> tuple[Settings, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return Settings.from_dict(data), None
    except FileNotFoundError:
        return Settings(), None
    except (OSError, ValueError, SettingsError) as e:
        return (
            Settings(),
            f"Settings file {path} is invalid ({e}); using defaults. Saving will replace it.",
        )


def save(path: Path, settings: Settings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings.to_dict(), f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def follow_of(series: str) -> Series | None:
    return None if series == "any" else Series[series.upper()]


class SettingsService:
    def __init__(
        self,
        path: Path,
        settings: Settings,
        engine,
        lights,
        build_source: Callable = default_build_source,
        warning: str | None = None,
        ha=None,
    ):
        self._path = path
        self._settings = settings
        self._engine = engine
        self._lights = lights
        self.ha = ha
        self._build_source = build_source
        self._warning = warning
        self._bad_file = warning is not None
        self._lock = threading.Lock()

    def get(self) -> Settings:
        with self._lock:
            return self._settings

    @property
    def warning(self) -> str | None:
        with self._lock:
            return self._warning

    def update(self, patch: dict) -> Settings:
        with self._lock:
            old = self._settings
            new = old.merged(patch)
            if new == old:
                return old
            if (new.series, new.source) != (old.series, old.source):
                follow = follow_of(new.series)
                self._engine.configure(self._build_source(new.source, follow), follow, new.source)
            if (new.controllers, new.progress, new.offline) != (
                old.controllers,
                old.progress,
                old.offline,
            ):
                self._lights.configure(
                    new.specs(), progress=new.progress_spec(), offline_hold=new.offline == "hold"
                )
            if self.ha is not None and any(
                getattr(new, f) != getattr(old, f) for f in (*_HA_FIELDS, "offline")
            ):
                self.ha.configure(
                    url=new.ha_url,
                    token=new.ha_token,
                    verify_tls=new.ha_verify_tls,
                    scenes=dict(new.ha_scenes),
                    offline_hold=new.offline == "hold",
                )
            self._settings = new
            try:
                if self._bad_file and self._path.exists():
                    os.replace(self._path, f"{self._path}.bad")
                    self._bad_file = False
                    kept = f"Your old settings file was invalid; it was kept as {self._path}.bad"
                else:
                    kept = None
                save(self._path, new)
                self._warning = kept
            except OSError as e:
                self._warning = f"Applied, but couldn't save settings: {e.strerror or e}"
            return new
