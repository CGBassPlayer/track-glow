import argparse
import logging
import os
import sys
import threading

from track_glow.server import ServerStartError, WebServer

DEFAULT_PORT = 8780
DESKTOP_EXTRA_HINT = (
    "Desktop mode needs the desktop extra: install track-glow[desktop], or run with --headless"
)

NO_DISPLAY_HINT = "No display found: run with --headless"

log = logging.getLogger(__name__)


def has_display() -> bool:
    if not sys.platform.startswith("linux"):
        return True
    return any(os.environ.get(v) for v in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="track-glow")
    parser.add_argument("--headless", action="store_true", help="serve the web UI with no window")
    parser.add_argument("--host", help="bind address (default 127.0.0.1, or 0.0.0.0 if headless)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    if args.host is None:
        args.host = "0.0.0.0" if args.headless else "127.0.0.1"
    return args


def _run_headless(host: str, port: int) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    srv = WebServer(host, port)
    srv.start()
    log.info("Track Glow web UI: %s", srv.url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.headless:
            return _run_headless(args.host, args.port)
        if not has_display():
            print(NO_DISPLAY_HINT, file=sys.stderr)
            return 1
        try:
            from track_glow.launcher import run_launcher
        except ImportError as e:
            pyside_missing = (
                isinstance(e, ModuleNotFoundError) and (e.name or "").split(".")[0] == "PySide6"
            )
            print(
                DESKTOP_EXTRA_HINT if pyside_missing else f"Can't start desktop mode: {e}",
                file=sys.stderr,
            )
            return 1
        return run_launcher(args.host, args.port)
    except ServerStartError as e:
        print(e, file=sys.stderr)
        return 1
