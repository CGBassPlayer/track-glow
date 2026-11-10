import json
from typing import Annotated, Any, Literal, Protocol

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from track_glow import __version__
from track_glow.engine import EngineState, status_text
from track_glow.ha import HaClient, HaError
from track_glow.models import Flag
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


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Track Glow</title>
<style>
  :root { --bg: #f6f6f4; --fg: #1b1b1b; --muted: #666; --card: #fff; --line: #ddd;
          --accent: #1b1b1b; --accent-fg: #fff; --err: #b3261e; --warn-bg: #fff4d6; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #141414; --fg: #eee; --muted: #999; --card: #1e1e1e; --line: #333;
            --accent: #eee; --accent-fg: #141414; --err: #f2b8b5; --warn-bg: #3a3112; }
  }
  body { margin: 0; padding: 2rem 1rem; background: var(--bg); color: var(--fg);
         font-family: system-ui, sans-serif; }
  main { max-width: 40rem; margin: 0 auto; display: grid; gap: 1rem; }
  h1 { margin: 0; }
  h2 { font-size: 1rem; margin: 0 0 .75rem; }
  .card { padding: 1rem; background: var(--card); border: 1px solid var(--line);
          border-radius: 8px; }
  .status { display: flex; gap: 1rem; align-items: center; }
  #swatch { width: 3.5rem; height: 3.5rem; border-radius: 6px; flex: none;
            background: #9e9e9e; border: 1px solid var(--line); }
  #status { font-size: 1.25rem; font-weight: 600; margin: 0; }
  .muted { color: var(--muted); margin: .25rem 0 0; }
  #strip { width: 100%; display: block; background: #000; border-radius: 6px; }
  .row { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; margin-bottom: .75rem; }
  .row:last-child { margin-bottom: 0; }
  .row > span { min-width: 5.5rem; color: var(--muted); font-size: .9rem; }
  button, select, input, textarea { font: inherit; color: var(--fg); background: var(--bg);
    border: 1px solid var(--line); border-radius: 6px; padding: .35rem .7rem; }
  button { cursor: pointer; }
  button[aria-pressed="true"] { background: var(--accent); color: var(--accent-fg);
                                border-color: var(--accent); }
  button .dot { display: inline-block; width: .7rem; height: .7rem; border-radius: 50%;
                margin-right: .35rem; vertical-align: -1px; border: 1px solid var(--line); }
  label { display: grid; gap: .3rem; margin-bottom: .75rem; font-size: .9rem; }
  textarea { min-height: 4.5rem; font-family: ui-monospace, monospace; }
  input, textarea, select { width: 100%; box-sizing: border-box; }
  .err { color: var(--err); font-size: .85rem; min-height: 0; }
  #warning { background: var(--warn-bg); border-color: var(--line); }
</style>
</head>
<body>
<main>
  <h1>Track Glow</h1>
  <div id="warning" class="card" hidden></div>
  <div class="card status">
    <div id="swatch"></div>
    <div>
      <p id="status">No race</p>
      <p id="detail" class="muted"></p>
      <p id="feed" class="muted"></p>
    </div>
  </div>
  <div id="strip-wrap" hidden>
    <canvas id="strip"></canvas>
    <p id="lights" class="muted"></p>
  </div>
  <section id="controls" class="card">
    <h2>Controls</h2>
    <div class="row"><span>Test flag</span><span id="flag-buttons"></span>
      <button data-flag="">Clear</button></div>
    <div class="row"><span>Lights</span>
      <button data-mode="on">On</button>
      <button data-mode="paused">Pause</button>
      <button data-mode="blackout">Blackout</button></div>
    <div class="row"><span>Source</span>
      <button data-source="live">Live</button>
      <button data-source="replay">Replay</button></div>
    <div class="row"><span>Series</span>
      <select id="series" style="width:auto">
        <option value="cup">Cup</option><option value="xfinity">Xfinity</option>
        <option value="truck">Truck</option><option value="any">Any</option>
      </select></div>
    <p id="controls-err" class="err"></p>
  </section>
  <form id="settings-form" class="card">
    <h2>Setup</h2>
    <label>WLED controllers, one per line, in strip order (HOST or HOST:LEDS)
      <textarea id="controllers" spellcheck="false"></textarea>
      <span class="err" data-err="controllers"></span></label>
    <label>Lap progress bar (START-STOP or HOST/SEG, empty for none)
      <input id="progress" spellcheck="false">
      <span class="err" data-err="progress"></span></label>
    <label>When the feed goes offline
      <select id="offline">
        <option value="amber">Show dim amber</option>
        <option value="hold">Hold the last flag</option>
      </select>
      <span class="err" data-err="offline"></span></label>
    <h2>Home Assistant</h2>
    <p id="ha-status" class="muted"></p>
    <label>URL (e.g. http://homeassistant.local:8123, empty to turn off)
      <input id="ha-url" spellcheck="false">
      <span class="err" data-err="ha_url"></span></label>
    <label>Long-lived access token
      <input id="ha-token" type="password" autocomplete="off" spellcheck="false">
      <span class="err" data-err="ha_token"></span></label>
    <label style="display:flex;gap:.5rem;align-items:center">
      <input id="ha-verify" type="checkbox" style="width:auto"> Verify TLS certificate</label>
    <div class="row"><button type="button" id="ha-test">Test connection</button>
      <span id="ha-test-result" class="muted"></span></div>
    <datalist id="ha-scene-list"></datalist>
    <div id="ha-scenes"></div>
    <span class="err" data-err="ha_scenes"></span>
    <button type="submit">Save</button> <span id="saved" class="muted"></span>
    <span id="form-err" class="err"></span>
  </form>
</main>
<script>
const FLAGS = __FLAGS__;
const SCENES = __SCENES__;
function disconnected(reason) {
  document.getElementById("status").textContent = "Not connected";
  document.getElementById("swatch").style.background = "#9e9e9e";
  document.getElementById("detail").textContent = "";
  document.getElementById("feed").textContent = reason;
}
function press(attr, value) {
  document.querySelectorAll("[" + attr + "]").forEach(b =>
    b.setAttribute("aria-pressed", String(b.getAttribute(attr) === value)));
}
async function refresh() {
  try {
    const r = await fetch("/api/state");
    if (!r.ok) { disconnected("Track Glow error (HTTP " + r.status + ")"); return; }
    const s = await r.json();
    document.getElementById("status").textContent = s.status;
    document.getElementById("swatch").style.background = s.flag_color || "#9e9e9e";
    document.getElementById("detail").textContent =
      [s.track_name, s.run_name].filter(Boolean).join(" · ");
    const feed = s.source === "replay" ? "Replay" : "Feed " + s.feed.health;
    document.getElementById("feed").textContent =
      s.feed.message ? feed + " — " + s.feed.message : feed;
    press("data-mode", s.mode);
    const ha = s.home_assistant;
    document.getElementById("ha-status").textContent = !ha || ha.state === "off"
      ? "Off" : ha.state === "ok" ? "OK · last scene " + ha.scene
      : ha.state + (ha.message ? " — " + ha.message : "");
    press("data-flag", s.override || "");
  } catch (e) {
    disconnected("Track Glow not reachable");
  }
}
let lastWarning = null;
function showSettings(body) {
  lastWarning = body.warning;
  const w = document.getElementById("warning");
  w.hidden = !body.warning;
  w.textContent = body.warning || "";
  const st = body.settings;
  press("data-source", st.source);
  document.getElementById("series").value = st.series;
  return st;
}
function fillForm(st) {
  document.getElementById("controllers").value = st.controllers.join("\\n");
  document.getElementById("progress").value = st.progress || "";
  document.getElementById("offline").value = st.offline;
  document.getElementById("ha-url").value = st.ha_url;
  document.getElementById("ha-token").value = "";
  document.getElementById("ha-token").placeholder =
    st.ha_token_set ? "saved — leave empty to keep" : "";
  document.getElementById("ha-verify").checked = st.ha_verify_tls;
  SCENES.forEach(([key]) => {
    document.getElementById("scene-" + key).value = st.ha_scenes[key] || "";
  });
}
async function loadSettings() {
  const r = await fetch("/api/settings");
  if (r.ok) fillForm(showSettings(await r.json()));
}
async function patchSettings(patch, errEl) {
  document.querySelectorAll("[data-err]").forEach(e => e.textContent = "");
  document.getElementById("controls-err").textContent = "";
  document.getElementById("form-err").textContent = "";
  const r = await fetch("/api/settings", {
    method: "PATCH", headers: {"content-type": "application/json"},
    body: JSON.stringify(patch)});
  let body;
  try { body = await r.json(); } catch (e) {
    errEl.textContent = "Track Glow error (HTTP " + r.status + ")";
    return false;
  }
  if (r.ok) { showSettings(body); refresh(); return true; }
  const target = document.querySelector('[data-err="' + body.field + '"]') || errEl;
  target.textContent = body.error;
  return false;
}
async function post(url, payload) {
  await fetch(url, {method: "POST", headers: {"content-type": "application/json"},
                    body: JSON.stringify(payload)});
  refresh();
}
const sceneBox = document.getElementById("ha-scenes");
SCENES.forEach(([key, label]) => {
  const l = document.createElement("label");
  l.append(label + " scene");
  const i = document.createElement("input");
  i.id = "scene-" + key;
  i.setAttribute("list", "ha-scene-list");
  i.spellcheck = false;
  l.append(i);
  sceneBox.append(l);
});
document.getElementById("ha-test").onclick = async () => {
  const out = document.getElementById("ha-test-result");
  out.textContent = "Testing…";
  const r = await (await fetch("/api/ha/test", {method: "POST"})).json();
  if (!r.ok) { out.textContent = r.error; return; }
  out.textContent = "Connected · " + r.scenes.length + " scenes";
  const list = document.getElementById("ha-scene-list");
  list.replaceChildren(...r.scenes.map(s => { const o = document.createElement("option");
    o.value = s; return o; }));
};
const flagButtons = document.getElementById("flag-buttons");
FLAGS.forEach(f => {
  const b = document.createElement("button");
  b.dataset.flag = f.key;
  b.innerHTML = '<span class="dot"></span>';
  b.querySelector(".dot").style.background = f.color;
  b.append(f.short);
  flagButtons.append(b, " ");
});
document.querySelectorAll("[data-flag]").forEach(b => b.onclick = () =>
  post("/api/override", {flag: b.dataset.flag || null}));
document.querySelectorAll("[data-mode]").forEach(b => b.onclick = () =>
  post("/api/mode", {mode: b.dataset.mode}));
const controlsErr = document.getElementById("controls-err");
document.querySelectorAll("[data-source]").forEach(b => b.onclick = () =>
  patchSettings({source: b.dataset.source}, controlsErr));
document.getElementById("series").onchange = e =>
  patchSettings({series: e.target.value}, controlsErr);
document.getElementById("settings-form").onsubmit = async e => {
  e.preventDefault();
  const controllers = document.getElementById("controllers").value
    .split("\\n").map(l => l.trim()).filter(Boolean);
  const progress = document.getElementById("progress").value.trim() || null;
  const patch = {controllers, progress, offline: document.getElementById("offline").value,
    ha_url: document.getElementById("ha-url").value.trim(),
    ha_verify_tls: document.getElementById("ha-verify").checked,
    ha_scenes: Object.fromEntries(SCENES.map(([key]) =>
      [key, document.getElementById("scene-" + key).value.trim()]))};
  const token = document.getElementById("ha-token").value.trim();
  if (token) patch.ha_token = token;
  const ok = await patchSettings(patch, document.getElementById("form-err"));
  if (ok) loadSettings();
  document.getElementById("saved").textContent = ok && !lastWarning ? "Saved" : "";
  if (ok) refreshLights();
};
refresh();
setInterval(refresh, 2000);
loadSettings();

const LED = 10;
const FRAME_MS = 100;
let lights = [];
function barText(p) {
  if (!p || p.state === "off") return "";
  return p.state === "ok" ? "Bar " + Math.round(p.fraction * 100) + "%" : "Bar: " + p.message;
}
async function refreshLights() {
  let progress = null;
  try {
    const s = await (await fetch("/api/state")).json();
    lights = s.lights;
    progress = s.progress;
  } catch (e) {}
  document.getElementById("strip-wrap").hidden = lights.length === 0;
  document.getElementById("lights").textContent = lights
    .map(l => l.host + ": " + (l.state === "ok"
      ? l.led_count + " LEDs"
      : l.state + (l.message ? " — " + l.message : "")))
    .concat(barText(progress) || [])
    .join(" · ");
}
async function drawStrip() {
  try {
    if (lights.length) {
      const r = await fetch("/api/frame");
      if (r.ok) {
        const f = await r.json();
        const c = document.getElementById("strip");
        const perRow = Math.max(1, Math.floor(c.clientWidth / LED));
        const n = f.led_count;
        c.width = perRow * LED;
        c.height = Math.max(1, Math.ceil(n / perRow)) * LED;
        const g = c.getContext("2d");
        g.fillStyle = "#000";
        g.fillRect(0, 0, c.width, c.height);
        for (let i = 0; i < n; i++) {
          g.fillStyle = "#" + f.pixels.substr(i * 6, 6);
          g.fillRect((i % perRow) * LED + 1, Math.floor(i / perRow) * LED + 1, LED - 2, LED - 2);
        }
      }
    }
  } catch (e) {}
  setTimeout(drawStrip, FRAME_MS);
}
refreshLights();
setInterval(refreshLights, 2000);
drawStrip();
</script>
</body>
</html>
"""


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

    page = INDEX_HTML.replace("__FLAGS__", json.dumps(FLAG_BUTTONS)).replace(
        "__SCENES__", json.dumps(list(SCENE_LABELS.items()))
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return page

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
