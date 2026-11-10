import logging
import os
import sys
import threading
from typing import Annotated

import typer

from track_glow.server import ServerStartError, WebServer

DEFAULT_PORT = 8780
DESKTOP_EXTRA_HINT = (
    "Desktop mode needs the desktop extra: install track-glow[desktop], or run with --headless"
)
NO_DISPLAY_HINT = "No display found: run with --headless"

log = logging.getLogger(__name__)
app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


def has_display() -> bool:
    if not sys.platform.startswith("linux"):
        return True
    return any(os.environ.get(v) for v in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"))


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


def _run_desktop(host: str, port: int) -> int:
    if not has_display():
        print(NO_DISPLAY_HINT, file=sys.stderr)
        return 1
    try:
        import track_glow.launcher as launcher
    except ImportError as e:
        pyside_missing = (
            isinstance(e, ModuleNotFoundError) and (e.name or "").split(".")[0] == "PySide6"
        )
        msg = DESKTOP_EXTRA_HINT if pyside_missing else f"Can't start desktop mode: {e}"
        print(msg, file=sys.stderr)
        return 1
    return launcher.run_launcher(host, port)


@app.command()
def run(
    headless: Annotated[
        bool, typer.Option("--headless", help="Serve the web UI with no window.")
    ] = False,
    host: Annotated[
        str | None,
        typer.Option(help="Bind address. Default 127.0.0.1, or 0.0.0.0 when headless."),
    ] = None,
    port: Annotated[int, typer.Option(min=1, max=65535, help="Web UI port.")] = DEFAULT_PORT,
) -> int:
    if host is None:
        host = "0.0.0.0" if headless else "127.0.0.1"
    try:
        return _run_headless(host, port) if headless else _run_desktop(host, port)
    except ServerStartError as e:
        print(e, file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    try:
        rv = app(args=argv, prog_name="track-glow", standalone_mode=False)
    except typer.Exit as e:
        return e.exit_code
    except typer.TyperException as e:
        e.show()
        return e.exit_code
    return 0 if rv is None else rv
