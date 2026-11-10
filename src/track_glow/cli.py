import logging
import os
import sys
import time
from enum import StrEnum
from typing import Annotated

import typer

from track_glow.engine import Engine, status_text
from track_glow.models import Series
from track_glow.outputs.wled import WledOutput
from track_glow.server import ServerStartError, WebServer
from track_glow.sources import build_source
from track_glow.wled import ControllerSpec

DEFAULT_PORT = 8780
DESKTOP_EXTRA_HINT = (
    "Desktop mode needs the desktop extra: install track-glow[desktop], or run with --headless"
)
NO_DISPLAY_HINT = "No display found: run with --headless"

log = logging.getLogger(__name__)


class SeriesChoice(StrEnum):
    cup = "cup"
    xfinity = "xfinity"
    truck = "truck"
    any = "any"


app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


def has_display() -> bool:
    if not sys.platform.startswith("linux"):
        return True
    return any(os.environ.get(v) for v in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"))


def _run_headless(engine: Engine, host: str, port: int, lights: WledOutput | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    srv = WebServer(host, port, engine, lights)
    srv.start()
    log.info("Track Glow web UI: %s", srv.url)
    last = None
    try:
        while True:
            state = engine.snapshot()
            key = (state.flag, state.feed.health, state.waiting_for_series)
            if key != last:
                log.info("Status: %s", status_text(state))
                last = key
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    return 0


def _run_desktop(engine: Engine, host: str, port: int, lights: WledOutput | None = None) -> int:
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
    return launcher.run_launcher(engine, host, port, lights)


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
    series: Annotated[
        SeriesChoice, typer.Option(help="Series to follow; other live series are ignored.")
    ] = SeriesChoice.cup,
    replay: Annotated[bool, typer.Option("--replay", help="Loop a demo race.")] = False,
    wled: Annotated[
        list[str] | None,
        typer.Option(
            "--wled",
            metavar="HOST[:LEDS]",
            help="WLED controller, repeatable, in strip order. LEDS skips discovery.",
        ),
    ] = None,
) -> int:
    if host is None:
        host = "0.0.0.0" if headless else "127.0.0.1"
    follow = None if series is SeriesChoice.any else Series[series.name.upper()]
    kind = "replay" if replay else "live"
    engine = Engine(build_source(kind, follow), follow, kind)
    try:
        specs = [ControllerSpec.parse(w) for w in wled or []]
    except ValueError as e:
        print(f"Invalid --wled value: {e}", file=sys.stderr)
        return 2
    lights = WledOutput(engine, specs) if specs else None
    engine.start()
    if lights is not None:
        lights.start()
    try:
        runner = _run_headless if headless else _run_desktop
        return runner(engine, host, port, lights)
    except ServerStartError as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        if lights is not None:
            lights.stop()
        engine.stop()


def main(argv: list[str] | None = None) -> int:
    try:
        rv = app(args=argv, prog_name="track-glow", standalone_mode=False)
    except typer.Exit as e:
        return e.exit_code
    except typer.TyperException as e:
        e.show()
        return e.exit_code
    return 0 if rv is None else rv
