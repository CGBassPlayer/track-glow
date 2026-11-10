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
uv run pytest                                             # run the tests
```

The launcher lets you pick the bind address (this computer only, or all interfaces) and the port,
then opens the web UI in your browser. If your desktop has no system tray, **Hide to tray**
minimizes the window instead.

The desktop launcher needs the `desktop` extra (PySide6). The repo's dev dependencies include
it. A headless-only install doesn't.

## Status

Milestone 1: scaffold. No race data or lights yet.
