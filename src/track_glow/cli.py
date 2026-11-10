import logging
import os
import signal
import sys
import time
from enum import StrEnum
from typing import Annotated

import typer

from track_glow import __version__
from track_glow.engine import Engine, status_text
from track_glow.outputs.ha import HomeAssistantOutput
from track_glow.outputs.wled import WledOutput
from track_glow.server import ServerStartError, WebServer
from track_glow.settings import SettingsError, SettingsService, default_path, follow_of, load
from track_glow.sources import build_source

DEFAULT_PORT = 8780
DESKTOP_EXTRA_HINT = (
    "Desktop mode needs the desktop extra: install track-glow[desktop], or run with --headless"
)
NO_DISPLAY_HINT = "No display found: run with --headless"
FLAG_FOR_FIELD = {
    "series": "--series",
    "source": "--replay",
    "controllers": "--wled",
    "progress": "--progress",
}

log = logging.getLogger(__name__)


class SeriesChoice(StrEnum):
    cup = "cup"
    xfinity = "xfinity"
    truck = "truck"
    any = "any"


app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


def _interrupt(signum, frame) -> None:
    # Docker and systemd stop with SIGTERM; route it through the same cleanup as Ctrl-C.
    raise KeyboardInterrupt


def _print_version(value: bool) -> None:
    if value:
        print(f"track-glow {__version__}")
        raise typer.Exit()


def has_display() -> bool:
    if not sys.platform.startswith("linux"):
        return True
    return any(os.environ.get(v) for v in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"))


def _run_headless(
    engine: Engine,
    host: str,
    port: int,
    lights: WledOutput | None = None,
    settings: SettingsService | None = None,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    if settings is not None and settings.warning:
        log.warning("%s", settings.warning)
    signal.signal(signal.SIGTERM, _interrupt)
    srv = WebServer(host, port, engine, lights, settings)
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


def _run_desktop(
    engine: Engine,
    host: str,
    port: int,
    lights: WledOutput | None = None,
    settings: SettingsService | None = None,
) -> int:
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
    return launcher.run_launcher(engine, host, port, lights, settings)


@app.command()
def run(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_print_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
    headless: Annotated[
        bool, typer.Option("--headless", help="Serve the web UI with no window.")
    ] = False,
    host: Annotated[
        str | None,
        typer.Option(help="Bind address. Default 127.0.0.1, or 0.0.0.0 when headless."),
    ] = None,
    port: Annotated[int, typer.Option(min=1, max=65535, help="Web UI port.")] = DEFAULT_PORT,
    series: Annotated[
        SeriesChoice | None,
        typer.Option(help="Series to follow for this run (default: from settings, else cup)."),
    ] = None,
    replay: Annotated[
        bool, typer.Option("--replay", help="Loop a demo race for this run.")
    ] = False,
    wled: Annotated[
        list[str] | None,
        typer.Option(
            "--wled",
            metavar="HOST[:LEDS]",
            help="WLED controller for this run, repeatable, in strip order. "
            "LEDS skips discovery. Replaces the saved controllers.",
        ),
    ] = None,
    progress: Annotated[
        str | None,
        typer.Option(
            metavar="START-STOP|HOST/SEG",
            help="Lap progress bar: LED range of the whole strip (0-based, stop exclusive) "
            "or a WLED segment ID on one --wled controller.",
        ),
    ] = None,
) -> int:
    if host is None:
        host = "0.0.0.0" if headless else "127.0.0.1"
    path = default_path()
    settings, warning = load(path)
    patch: dict = {}
    if series is not None:
        patch["series"] = series.value
    if replay:
        patch["source"] = "replay"
    if wled:
        patch["controllers"] = wled
        saved_bar = settings.progress_spec()
        if progress is None and saved_bar is not None and saved_bar.host is not None:
            hosts = {w.partition(":")[0].strip().lower() for w in wled}
            if saved_bar.host not in hosts:
                print(
                    f"Ignoring saved progress bar {settings.progress} for this run: "
                    f"{saved_bar.host} isn't in --wled",
                    file=sys.stderr,
                )
                patch["progress"] = None
    if progress is not None:
        patch["progress"] = progress
    try:
        settings = settings.merged(patch)
    except SettingsError as e:
        print(f"{FLAG_FOR_FIELD.get(e.field, e.field)}: {e.message}", file=sys.stderr)
        return 2
    follow = follow_of(settings.series)
    engine = Engine(build_source(settings.source, follow), follow, settings.source)
    lights = WledOutput(
        engine,
        settings.specs(),
        progress=settings.progress_spec(),
        offline_hold=settings.offline == "hold",
    )
    ha = HomeAssistantOutput(engine)
    ha.configure(
        url=settings.ha_url,
        token=settings.ha_token,
        verify_tls=settings.ha_verify_tls,
        scenes=dict(settings.ha_scenes),
        offline_hold=settings.offline == "hold",
    )
    service = SettingsService(path, settings, engine, lights, warning=warning, ha=ha)
    engine.start()
    lights.start()
    ha.start()
    try:
        runner = _run_headless if headless else _run_desktop
        return runner(engine, host, port, lights, service)
    except ServerStartError as e:
        print(e, file=sys.stderr)
        return 1
    finally:
        ha.stop()
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
