import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from platformdirs import user_config_dir

from track_glow.wled import ControllerSpec, ProgressSpec

VERSION = 1
_CHOICES = {
    "series": ("cup", "xfinity", "truck", "any"),
    "source": ("live", "replay"),
    "offline": ("amber", "hold"),
}


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

    def to_dict(self) -> dict:
        d = asdict(self)
        d["controllers"] = list(self.controllers)
        return {"version": VERSION, **d}

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        return cls()._with(d)

    def merged(self, patch: dict) -> "Settings":
        known = {f.name for f in fields(self)}
        for key in patch:
            if key not in known:
                raise SettingsError(key, f"Unknown setting {key}")
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
