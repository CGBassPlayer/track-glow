import socket
import threading
import time

import uvicorn

from track_glow.web import EngineLike, LightsLike, SettingsLike, create_app

START_TIMEOUT = 5.0
STOP_TIMEOUT = 5.0


class ServerStartError(Exception):
    pass


class _ThreadedServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        pass


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def display_host(host: str) -> str:
    return lan_ip() if host == "0.0.0.0" else host


class WebServer:
    def __init__(
        self,
        host: str,
        port: int,
        engine: EngineLike,
        lights: LightsLike | None = None,
        settings: SettingsLike | None = None,
    ):
        self.settings = settings
        self.host = host
        self.port = port
        self.engine = engine
        self.lights = lights
        self._server: _ThreadedServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{display_host(self.host)}:{self.port}"

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        config = uvicorn.Config(
            create_app(self.engine, self.lights, self.settings),
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        self._server = _ThreadedServer(config)
        self._thread = threading.Thread(target=self._run, name="track-glow-web", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + START_TIMEOUT
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                self.stop()
                raise ServerStartError(f"Can't listen on {self.host}:{self.port}")
            time.sleep(0.02)

    def _run(self) -> None:
        # uvicorn calls sys.exit() on bind failure; contain it to this thread.
        try:
            self._server.run()
        except BaseException:
            pass

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(STOP_TIMEOUT)
        self._server = None
        self._thread = None
