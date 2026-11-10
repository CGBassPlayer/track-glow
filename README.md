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
uv run pytest                                             # run the tests
```

The launcher lets you pick the bind address (this computer only, or all interfaces) and the port,
then opens the web UI in your browser. If your desktop has no system tray, **Hide to tray**
minimizes the window instead.

Race data comes from NASCAR's public live feed (`cf.nascar.com/live/feeds/live-feed.json`),
polled every 3 seconds. The feed carries one race at a time, so `--series` is a filter: with
`--series xfinity` and a Cup race live, status reads "Waiting for Xfinity". After 3 failed polls the
feed is marked offline; polling backs off to 30 seconds and recovers on its own. `GET /api/state`
returns the current state as JSON; `POST /api/override {"flag": "red"}` forces a flag
(`{"flag": null}` clears it).

The desktop launcher needs the `desktop` extra (PySide6). The repo's dev dependencies include
it. A headless-only install doesn't.

## Status

Milestone 2: live race state (flag, laps, series) in the launcher and web UI. No lights yet.
