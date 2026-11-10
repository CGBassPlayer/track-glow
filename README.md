# Track Glow

Track Glow syncs your home lights with the flag in a live race. It watches a race feed and drives
WLED controllers and Home Assistant so the room goes green, yellow, red, or checkered with the
track. One process runs the engine and a web UI on your LAN for setup and control. On a desktop,
a small launcher window shows status and the web UI address and sits in the system tray. On a
server, it runs headless.

## Usage

```sh
uv run track-glow                                         # desktop launcher (binds 127.0.0.1:8780)
uv run track-glow --headless [--host HOST] [--port PORT]  # no window (binds 0.0.0.0:8780)
uv run track-glow --replay                                # loop a ~2-minute demo race
uv run track-glow --series xfinity                        # cup (default), xfinity, truck, any
uv run track-glow --wled 10.0.0.5 --wled 10.0.0.6:60      # drive WLED controllers, in strip order
uv run track-glow --wled 10.0.0.5 --progress 10.0.0.5/1  # lap progress bar on WLED segment 1
uv run pytest                                             # run the tests
```

The launcher lets you pick the bind address (this computer only, or all interfaces) and the port,
then opens the web UI in your browser. If your desktop has no system tray, **Hide to tray**
minimizes the window instead.

### Setup and controls (web UI)

Everything else is set up in the web UI and applies immediately, with no restart:

- **Controls:** fire a test flag (stays until **Clear**), **On / Pause / Blackout** (Pause hands
  the lights back to WLED; Blackout keeps them dark), **Live / Replay**, and the followed series.
  Test flag and Pause/Blackout aren't saved: a restart comes back on, with no test flag.
- **Setup:** WLED controllers, the lap progress bar, and what to show when the feed goes offline
  (dim amber, or hold the last flag).

Settings are saved to `settings.json` in your OS config folder (on Linux
`~/.config/track-glow/settings.json`), or to the path in `TRACK_GLOW_CONFIG`. The file is written
owner-only. If it can't be read, Track Glow starts with defaults, leaves the file alone, and shows a
warning until you save.

The `--series`, `--replay`, `--wled` and `--progress` flags override the saved settings for one run
and don't change the file, unless you then save from the web UI.

Race data comes from NASCAR's public live feed (`cf.nascar.com/live/feeds/live-feed.json`),
polled every 3 seconds. The feed carries one race at a time, so `--series` is a filter: with
`--series xfinity` and a Cup race live, status reads "Waiting for Xfinity". After 3 failed polls the
feed is marked offline; polling backs off to 30 seconds and recovers on its own. API:
`GET /api/state` returns the current state as JSON; `POST /api/override {"flag": "red"}` forces a
flag (`{"flag": null}` clears it); `POST /api/mode {"mode": "on"|"paused"|"blackout"}`;
`GET /api/settings` and `PATCH /api/settings` (partial JSON) read and change settings;
`POST /api/ha/test` checks the saved Home Assistant connection.

### WLED

Pass one `--wled HOST[:LEDS]` per controller, in the order the strip runs. Track Glow treats them
as one continuous strip: on every flag change it flashes 6-LED blocks of the flag color for 1.5 s
(5 s of white/black blocks for checkered), then holds. Blocks run across controller joins. Frames
go to every controller in the same tick over DDP (UDP port 4048), resent once a second while
holding. Without `:LEDS`, the LED count is read from `http://HOST/json/info`; an unreachable
controller is retried every 3 s and the rest keep working.

- WLED must have **Receive UDP realtime** turned on (Config → Sync Interfaces; on by default).
- With no race live, Track Glow stops sending and WLED returns to its own state after ~2.5 s.
  If the feed goes offline mid-race, the strip shows dim amber.
- WLED's own brightness applies.
- The web UI shows a live preview of the strip. Sync on real hardware is not yet validated.

#### Lap progress bar

`--progress` puts one bar on part of the strip. It fills by laps (`lap / laps in race`, full on
checkered) in the current flag's color over a dim track. It doesn't flash, and the rest of the
strip keeps showing the flag. Give either:

- `START-STOP`: an LED range of the whole virtual strip, e.g. `--progress 100-120`.
- `HOST/SEG`: segment `SEG` on the `--wled` controller `HOST`, e.g. `--progress 10.0.0.6/1`.
  The range is read from WLED's segment settings and follows the controller's position in the
  strip.

Both use WLED's own convention: LEDs are numbered from 0 and the stop is exclusive (WLED's
segment "Stop" field). The bar's status shows next to the lights in the web UI and launcher.

### Home Assistant

Track Glow can also trigger a Home Assistant scene on each change. Set it up in the web UI under
**Setup → Home Assistant**:

1. In Home Assistant, open your profile → **Security** → **Long-lived access tokens** → **Create
   token**.
2. Enter the HA URL (e.g. `http://homeassistant.local:8123`) and the token, then **Save**.
3. **Test connection** checks the token and lists your scenes.
4. Pick a scene for each state you want: one per flag, plus **No race**, **Feed offline** and
   **Blackout**. States without a scene are skipped. Then **Save**.

Each scene is triggered once when the state changes (no flashing on the HA side) and retried every
5 s if HA can't be reached. **Pause** leaves Home Assistant alone. With "hold the last flag", a feed
outage doesn't trigger the offline scene. The token is stored only in the owner-only settings file:
the web UI and API never send it back, and leaving the token field empty keeps the saved one. Clear
the URL to turn Home Assistant off.

The desktop launcher needs the `desktop` extra (PySide6). The repo's dev dependencies include
it. A headless-only install doesn't.

## Install and run

### Docker (headless server)

```sh
docker compose up -d --build        # builds the image, serves the web UI on port 8780
```

`compose.yaml` uses host networking, because Track Glow sends DDP to WLED controllers on your LAN
and `*.local` names don't resolve from a bridged container. Settings live in `./config` (mounted
at `/config`). The image has no Qt, runs as a non-root user, and has a healthcheck on
`/api/health`. Without compose:

```sh
docker build -t track-glow .
docker run -d --network host -v "$PWD/config:/config" --restart unless-stopped track-glow
```

### Desktop app (PyInstaller)

```sh
uv run pyinstaller packaging/track-glow.spec --noconfirm   # -> dist/track-glow/track-glow
```

This builds a one-folder app for the OS you run it on (build on Windows for Windows, on macOS
for macOS). The same executable runs the launcher, or `--headless`. `track-glow --version` and
`python -m track_glow` also work.

## Status

Milestone 7: WLED output (spanned, synced, with web preview), lap progress bar, web setup and
controls with a settings file, Home Assistant scenes, and Docker / PyInstaller packaging. Not yet
validated on real WLED hardware.
