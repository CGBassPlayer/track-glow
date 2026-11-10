from typing import Any, Literal, Protocol

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from track_glow import __version__
from track_glow.engine import EngineState, status_text
from track_glow.models import Flag

FlagKey = Literal[tuple(f.key for f in Flag)]  # type: ignore[valid-type]


class EngineLike(Protocol):
    def snapshot(self) -> EngineState: ...
    def set_override(self, flag: Flag | None) -> None: ...
    def stop(self) -> None: ...


class OverrideRequest(BaseModel):
    flag: FlagKey | None  # type: ignore[valid-type]


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
        "status": status_text(state),
    }


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Track Glow</title>
<style>
  :root { --bg: #f6f6f4; --fg: #1b1b1b; --muted: #666; --card: #fff; --line: #ddd; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #141414; --fg: #eee; --muted: #999; --card: #1e1e1e; --line: #333; }
  }
  body { margin: 0; padding: 2rem 1rem; background: var(--bg); color: var(--fg);
         font-family: system-ui, sans-serif; }
  main { max-width: 40rem; margin: 0 auto; }
  .card { display: flex; gap: 1rem; align-items: center; padding: 1rem;
          background: var(--card); border: 1px solid var(--line); border-radius: 8px; }
  #swatch { width: 3.5rem; height: 3.5rem; border-radius: 6px; flex: none;
            background: #9e9e9e; border: 1px solid var(--line); }
  #status { font-size: 1.25rem; font-weight: 600; margin: 0; }
  .muted { color: var(--muted); margin: .25rem 0 0; }
</style>
</head>
<body>
<main>
  <h1>Track Glow</h1>
  <div class="card">
    <div id="swatch"></div>
    <div>
      <p id="status">No race</p>
      <p id="detail" class="muted"></p>
      <p id="feed" class="muted"></p>
    </div>
  </div>
</main>
<script>
async function refresh() {
  try {
    const s = await (await fetch("/api/state")).json();
    document.getElementById("status").textContent = s.status;
    document.getElementById("swatch").style.background = s.flag_color || "#9e9e9e";
    document.getElementById("detail").textContent =
      [s.track_name, s.run_name].filter(Boolean).join(" · ");
    const feed = s.source === "replay" ? "Replay" : "Feed " + s.feed.health;
    document.getElementById("feed").textContent =
      s.feed.message ? feed + " — " + s.feed.message : feed;
  } catch (e) {
    document.getElementById("feed").textContent = "Track Glow not reachable";
  }
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


def create_app(engine: EngineLike) -> FastAPI:
    app = FastAPI(title="Track Glow", version=__version__)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return state_json(engine.snapshot())

    @app.post("/api/override")
    def override(req: OverrideRequest) -> dict[str, Any]:
        engine.set_override(Flag[req.flag.upper()] if req.flag else None)
        return state_json(engine.snapshot())

    return app
