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

The desktop launcher needs the `desktop` extra (PySide6). The repo's dev dependencies include
it. A headless-only install doesn't.

## Status

Milestone 3: WLED output (spanned, synced, with web preview). No progress bar or Home Assistant yet.
