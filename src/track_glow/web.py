import json
from typing import Annotated, Any, Literal, Protocol

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from track_glow import __version__
from track_glow.engine import EngineState, status_text
from track_glow.ha import HaClient, HaError
from track_glow.models import Flag
from track_glow.pages import DASHBOARD_HTML, SETTINGS_HTML
from track_glow.settings import SCENE_LABELS, SettingsError

FLAG_BUTTONS = [
    {"key": f.key, "short": f.label.split(" · ")[0].title(), "color": f.color} for f in Flag
]
FlagKey = Literal[tuple(f.key for f in Flag)]  # type: ignore[valid-type]


class EngineLike(Protocol):
    def snapshot(self) -> EngineState: ...
    def set_override(self, flag: Flag | None) -> None: ...
    def set_mode(self, mode: str) -> None: ...
    def stop(self) -> None: ...


class LightsLike(Protocol):
    def status(self) -> list: ...
    def frame(self) -> bytes: ...
    def bar_status(self) -> Any: ...


class OverrideRequest(BaseModel):
    flag: FlagKey | None  # type: ignore[valid-type]


class ModeRequest(BaseModel):
    mode: Literal["on", "paused", "blackout"]


class SettingsLike(Protocol):
    warning: str | None

    def get(self) -> Any: ...
    def update(self, patch: dict) -> Any: ...


def state_json(state: EngineState) -> dict[str, Any]:
    race = state.race
    flag = state.flag
    return {
        "flag": flag.key if flag else None,
        "flag_label": flag.label if flag else None,
        "flag_color": flag.color if flag else None,
        "series": race.series.label if race else None,
        "lap": race.lap if race else None,
        "laps_in_race": race.laps_in_race if race else None,
        "track_name": race.track_name if race else "",
        "run_name": race.run_name if race else "",
        "feed": {
            "health": state.feed.health,
            "message": state.feed.message,
            "failures": state.feed.failures,
        },
        "follow": state.follow.label if state.follow else None,
        "waiting_for_series": state.waiting_for_series.label if state.waiting_for_series else None,
        "override": state.override.key if state.override else None,
        "source": state.source_kind,
        "mode": state.mode,
        "status": status_text(state),
    }


def lights_json(lights: LightsLike | None) -> list[dict[str, Any]]:
    if lights is None:
        return []
    return [
        {"host": c.host, "led_count": c.led_count, "state": c.state, "message": c.message}
        for c in lights.status()
    ]


def progress_json(lights: LightsLike | None) -> dict[str, Any] | None:
    if lights is None:
        return None
    b = lights.bar_status()
    return {
        "state": b.state,
        "message": b.message,
        "start": b.start,
        "stop": b.stop,
        "fraction": b.fraction,
    }


def create_app(
    engine: EngineLike, lights: LightsLike | None = None, settings: SettingsLike | None = None
) -> FastAPI:
    app = FastAPI(title="Track Glow", version=__version__)

    dashboard = DASHBOARD_HTML.replace("__FLAGS__", json.dumps(FLAG_BUTTONS))
    settings_page = SETTINGS_HTML.replace("__SCENES__", json.dumps(list(SCENE_LABELS.items())))

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return dashboard

    @app.get("/settings", response_class=HTMLResponse)
    def settings_view() -> str:
        return settings_page

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return {
            **state_json(engine.snapshot()),
            "lights": lights_json(lights),
            "progress": progress_json(lights),
            "home_assistant": ha_json(),
        }

    @app.get("/api/frame")
    def frame() -> dict[str, Any]:
        pixels = lights.frame() if lights is not None else b""
        return {"pixels": pixels.hex(), "led_count": len(pixels) // 3}

    def ha_json() -> dict[str, Any] | None:
        ha = getattr(settings, "ha", None)
        if ha is None:
            return None
        st = ha.ha_status()
        return {"state": st.state, "message": st.message, "scene": st.scene}

    def settings_json() -> dict[str, Any]:
        return {"settings": settings.get().public_dict(), "warning": settings.warning}

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        if settings is None:
            raise HTTPException(404)
        return settings_json()

    @app.patch("/api/settings")
    def patch_settings(patch: Annotated[Any, Body()]) -> Any:
        if settings is None:
            raise HTTPException(404)
        if not isinstance(patch, dict):
            return JSONResponse({"field": "", "error": "Expected a JSON object"}, 422)
        try:
            settings.update(patch)
        except SettingsError as e:
            return JSONResponse({"field": e.field, "error": e.message}, 422)
        return settings_json()

    @app.post("/api/ha/test")
    def ha_test() -> dict[str, Any]:
        if settings is None:
            raise HTTPException(404)
        s = settings.get()
        if not s.ha_url or not s.ha_token:
            return {"ok": False, "error": "Set the URL and token first"}
        client = HaClient(s.ha_url, s.ha_token, s.ha_verify_tls)
        try:
            client.check()
            return {"ok": True, "scenes": client.list_scenes()}
        except HaError as e:
            return {"ok": False, "error": str(e)}
        finally:
            client.close()

    @app.post("/api/mode")
    def mode(req: ModeRequest) -> dict[str, Any]:
        engine.set_mode(req.mode)
        return {**state_json(engine.snapshot()), "lights": lights_json(lights)}

    @app.post("/api/override")
    def override(req: OverrideRequest) -> dict[str, Any]:
        engine.set_override(Flag[req.flag.upper()] if req.flag else None)
        return {
            **state_json(engine.snapshot()),
            "lights": lights_json(lights),
            "progress": progress_json(lights),
            "home_assistant": ha_json(),
        }

    return app
