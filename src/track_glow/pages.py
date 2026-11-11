_CSS = """
  :root { color-scheme: light dark;
          --bg: #f6f6f4; --fg: #1b1b1b; --muted: #666; --card: #fff; --line: #ddd;
          --accent: #1b1b1b; --accent-fg: #fff; --err: #b3261e; --warn-bg: #fff4d6; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #141414; --fg: #eee; --muted: #999; --card: #1e1e1e; --line: #333;
            --accent: #eee; --accent-fg: #141414; --err: #f2b8b5; --warn-bg: #3a3112; }
  }
  body { margin: 0; padding: 2rem 1rem; background: var(--bg); color: var(--fg);
         font-family: system-ui, sans-serif; }
  main { max-width: 40rem; margin: 0 auto; display: grid; gap: 1rem; }
  header { display: flex; flex-wrap: wrap; gap: .5rem 1.5rem; align-items: baseline;
           justify-content: space-between; }
  h1 { margin: 0; }
  nav { display: flex; gap: 1rem; }
  nav a { color: var(--muted); text-decoration: none; }
  nav a:hover { color: var(--fg); }
  nav a[aria-current="page"] { color: var(--fg); font-weight: 600; }
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
  button, select, input { font: inherit; color: var(--fg); background: var(--bg);
    border: 1px solid var(--line); border-radius: 6px; padding: .35rem .7rem; }
  button { cursor: pointer; }
  button[aria-pressed="true"] { background: var(--accent); color: var(--accent-fg);
                                border-color: var(--accent); }
  button .dot { display: inline-block; width: .7rem; height: .7rem; border-radius: 50%;
                margin-right: .35rem; vertical-align: -1px; border: 1px solid var(--line); }
  label, .field { display: grid; gap: .3rem; margin-bottom: .75rem; font-size: .9rem; }
  input, select { width: 100%; box-sizing: border-box; }
  .ctl { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; margin-bottom: .4rem; }
  .ctl .num { width: 1.25rem; color: var(--muted); }
  .ctl .host { flex: 1 1 9rem; width: auto; min-width: 0; }
  .ctl .leds { flex: none; width: 6rem; }
  .ctl button:disabled { opacity: .4; cursor: default; }
  @media (max-width: 30rem) { .ctl .up { margin-left: 1.65rem; } }
  #add-controller { justify-self: start; }
  .err { color: var(--err); font-size: .85rem; min-height: 0; }
  #warning { background: var(--warn-bg); border-color: var(--line); }
"""

# Shared by both pages; each page defines its own showSettings(body) and refresh().
_COMMON_JS = """
function press(attr, value) {
  document.querySelectorAll("[" + attr + "]").forEach(b =>
    b.setAttribute("aria-pressed", String(b.getAttribute(attr) === value)));
}
let lastWarning = null;
function showWarning(body) {
  lastWarning = body.warning;
  const w = document.getElementById("warning");
  w.hidden = !body.warning;
  w.textContent = body.warning || "";
  return body.settings;
}
async function patchSettings(patch, errEl) {
  document.querySelectorAll("[data-err]").forEach(e => e.textContent = "");
  errEl.textContent = "";
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
"""


def _page(title: str, path: str, body: str, script: str) -> str:
    links = "".join(
        f'<a href="{href}"{' aria-current="page"' if href == path else ""}>{name}</a>'
        for href, name in (("/", "Dashboard"), ("/settings", "Settings"))
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
  <header><h1>Track Glow</h1><nav>{links}</nav></header>
  <div id="warning" class="card" hidden></div>
{body}
</main>
<script>{_COMMON_JS}{script}</script>
</body>
</html>
"""


DASHBOARD_HTML = _page(
    "Track Glow",
    "/",
    """  <div class="card status">
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
  </section>""",
    """
const FLAGS = __FLAGS__;
function disconnected(reason) {
  document.getElementById("status").textContent = "Not connected";
  document.getElementById("swatch").style.background = "#9e9e9e";
  document.getElementById("detail").textContent = "";
  document.getElementById("feed").textContent = reason;
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
    press("data-flag", s.override || "");
  } catch (e) {
    disconnected("Track Glow not reachable");
  }
}
function showSettings(body) {
  const st = showWarning(body);
  press("data-source", st.source);
  document.getElementById("series").value = st.series;
}
async function loadSettings() {
  const r = await fetch("/api/settings");
  if (r.ok) showSettings(await r.json());
}
async function post(url, payload) {
  await fetch(url, {method: "POST", headers: {"content-type": "application/json"},
                    body: JSON.stringify(payload)});
  refresh();
}
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
""",
)

SETTINGS_HTML = _page(
    "Track Glow · Settings",
    "/settings",
    """  <form id="settings-form" class="card">
    <h2>WLED</h2>
    <div class="field">WLED controllers, in strip order (empty LEDs = auto-detect)
      <div id="controllers"></div>
      <button type="button" id="add-controller">+ Add controller</button>
      <span class="err" data-err="controllers"></span></div>
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
    <div id="ha-scenes"></div>
    <span class="err" data-err="ha_scenes"></span>
    <button type="submit">Save</button> <span id="saved" class="muted"></span>
    <span id="form-err" class="err"></span>
  </form>""",
    """
const SCENES = __SCENES__;
let haScenes = [];
function sceneName(id) {
  const s = haScenes.find(s => s.id === id);
  return s ? s.name : id;
}
const controllerBox = document.getElementById("controllers");
function controllerRow(host, leds) {
  const row = document.createElement("div");
  row.className = "ctl";
  row.innerHTML = '<span class="num"></span>' +
    '<input class="host" placeholder="10.0.0.5 or wled.local" spellcheck="false"' +
    ' aria-label="Host">' +
    '<input class="leds" type="number" min="1" placeholder="auto" aria-label="LEDs">' +
    '<button type="button" class="up" aria-label="Move up">↑</button>' +
    '<button type="button" class="down" aria-label="Move down">↓</button>' +
    '<button type="button" class="del" aria-label="Remove">✕</button>';
  row.querySelector(".host").value = host;
  row.querySelector(".leds").value = leds;
  return row;
}
function renumber() {
  const rows = [...controllerBox.children];
  rows.forEach((row, i) => {
    row.querySelector(".num").textContent = i + 1;
    row.querySelector(".up").disabled = i === 0;
    row.querySelector(".down").disabled = i === rows.length - 1;
  });
}
controllerBox.onclick = e => {
  const row = e.target.closest(".ctl");
  const btn = e.target.closest("button");
  if (!row || !btn) return;
  if (btn.classList.contains("del")) {
    const near = row.nextElementSibling || row.previousElementSibling;
    row.remove();
    renumber();
    if (near) near.querySelector(".host").focus();
    else document.getElementById("add-controller").focus();
    return;
  }
  const up = btn.classList.contains("up");
  const prev = row.previousElementSibling;
  const next = row.nextElementSibling;
  if (up && prev) row.after(prev);
  else if (!up && next) row.before(next);
  renumber();
  if (btn.disabled) row.querySelector(up ? ".down" : ".up").focus();
};
document.getElementById("add-controller").onclick = () => {
  controllerBox.append(controllerRow("", ""));
  renumber();
};
async function refresh() {
  let ha = null;
  try {
    const r = await fetch("/api/state");
    if (!r.ok) return;
    ha = (await r.json()).home_assistant;
  } catch (e) { return; }
  document.getElementById("ha-status").textContent = !ha || ha.state === "off"
    ? "Off" : ha.state === "ok" ? "OK · last scene " + sceneName(ha.scene)
    : ha.state + (ha.message ? " — " + ha.message : "");
}
function sceneOption(value, text) {
  const o = document.createElement("option");
  o.value = value;
  o.textContent = text;
  return o;
}
// A saved scene HA doesn't list (renamed, deleted, or HA unreachable) stays selectable.
function selectScene(sel, id) {
  if (id && ![...sel.options].some(o => o.value === id)) sel.append(sceneOption(id, id));
  sel.value = id;
}
function fillSceneOptions(scenes) {
  haScenes = scenes;
  const shared = name => scenes.filter(s => s.name === name).length > 1;
  SCENES.forEach(([key]) => {
    const sel = document.getElementById("scene-" + key);
    const keep = sel.value;
    sel.replaceChildren(sceneOption("", "None"), ...scenes.map(s =>
      sceneOption(s.id, shared(s.name) ? s.name + " (" + s.id + ")" : s.name)));
    selectScene(sel, keep);
  });
}
function showSettings(body) {
  return showWarning(body);
}
function fillForm(st) {
  controllerBox.replaceChildren(...st.controllers.map(c => {
    const i = c.indexOf(":");
    return i < 0 ? controllerRow(c, "") : controllerRow(c.slice(0, i), c.slice(i + 1));
  }));
  renumber();
  document.getElementById("progress").value = st.progress || "";
  document.getElementById("offline").value = st.offline;
  document.getElementById("ha-url").value = st.ha_url;
  document.getElementById("ha-token").value = "";
  document.getElementById("ha-token").placeholder =
    st.ha_token_set ? "saved — leave empty to keep" : "";
  document.getElementById("ha-verify").checked = st.ha_verify_tls;
  SCENES.forEach(([key]) =>
    selectScene(document.getElementById("scene-" + key), st.ha_scenes[key] || ""));
  if (st.ha_url && st.ha_token_set) {
    loadScenes();
  } else {
    sceneLoads++;
    document.getElementById("ha-test-result").textContent = "";
    fillSceneOptions([]);
  }
}
async function loadSettings() {
  const r = await fetch("/api/settings");
  if (r.ok) fillForm(showSettings(await r.json()));
}
const sceneBox = document.getElementById("ha-scenes");
SCENES.forEach(([key, label]) => {
  const l = document.createElement("label");
  l.append(label + " scene");
  const sel = document.createElement("select");
  sel.id = "scene-" + key;
  sel.append(sceneOption("", "None"));
  l.append(sel);
  sceneBox.append(l);
});
let sceneLoads = 0;
async function loadScenes() {
  const n = ++sceneLoads;
  const out = document.getElementById("ha-test-result");
  out.textContent = "Testing…";
  let r;
  try {
    const res = await fetch("/api/ha/test", {method: "POST"});
    if (n !== sceneLoads) return;
    r = await res.json();
    if (n !== sceneLoads) return;
  } catch (e) {
    if (n !== sceneLoads) return;
    out.textContent = "Test failed (Track Glow error)";
    return;
  }
  if (!r.ok) { out.textContent = r.error; return; }
  out.textContent = "Connected · " + r.scenes.length + " scenes";
  fillSceneOptions(r.scenes);
  refresh();
}
document.getElementById("ha-test").onclick = loadScenes;
document.getElementById("settings-form").onsubmit = async e => {
  e.preventDefault();
  const controllers = [...controllerBox.children]
    .map(r => ({host: r.querySelector(".host").value.trim(),
                leds: r.querySelector(".leds").value.trim()}))
    .filter(c => c.host)
    .map(c => c.leds ? c.host + ":" + c.leds : c.host);
  const progress = document.getElementById("progress").value.trim() || null;
  const patch = {controllers, progress, offline: document.getElementById("offline").value,
    ha_url: document.getElementById("ha-url").value.trim(),
    ha_verify_tls: document.getElementById("ha-verify").checked,
    ha_scenes: Object.fromEntries(SCENES.map(([key]) =>
      [key, document.getElementById("scene-" + key).value]))};
  const token = document.getElementById("ha-token").value.trim();
  if (token) patch.ha_token = token;
  const ok = await patchSettings(patch, document.getElementById("form-err"));
  if (ok) loadSettings();
  document.getElementById("saved").textContent = ok && !lastWarning ? "Saved" : "";
};
refresh();
setInterval(refresh, 2000);
loadSettings();
""",
)
