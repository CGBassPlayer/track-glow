import argparse
import logging
import sys
import threading

from track_glow.server import ServerStartError, WebServer

DEFAULT_PORT = 8780
DESKTOP_EXTRA_HINT = (
    "Desktop mode needs the desktop extra: install track-glow[desktop], or run with --headless"
)

log = logging.getLogger(__name__)


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
        try:
            from track_glow.launcher import run_launcher
        except ImportError:
            print(DESKTOP_EXTRA_HINT, file=sys.stderr)
            return 1
        return run_launcher(args.host, args.port)
    except ServerStartError as e:
        print(e, file=sys.stderr)
        return 1
