import ssl

import httpx2

from track_glow import __version__

_USER_AGENT = f"track-glow/{__version__}"
_TIMEOUT = 5.0
_TLS_MESSAGE = "TLS error talking to Home Assistant (self-signed certificate? turn off Verify TLS)"
_BAD_REPLY = "Unexpected reply from Home Assistant"


class HaError(Exception):
    pass


class HaClient:
    def __init__(
        self,
        url: str,
        token: str,
        verify_tls: bool = True,
        client: httpx2.Client | None = None,
    ):
        self._url = url
        self._headers = {"User-Agent": _USER_AGENT, "Authorization": f"Bearer {token}"}
        self._owned = client is None
        self._client = client or httpx2.Client(
            timeout=_TIMEOUT, verify=verify_tls, headers={"User-Agent": _USER_AGENT}
        )

    def turn_on_scene(self, entity: str) -> None:
        self._request("POST", "/api/services/scene/turn_on", json={"entity_id": entity})

    def list_scenes(self) -> list[dict[str, str]]:
        states = self._json(self._request("GET", "/api/states"))
        if not isinstance(states, list):
            raise HaError(_BAD_REPLY)
        scenes = []
        for s in states:
            if not isinstance(s, dict):
                continue
            entity = s.get("entity_id")
            if not isinstance(entity, str) or not entity.startswith("scene."):
                continue
            attrs = s.get("attributes")
            name = attrs.get("friendly_name") if isinstance(attrs, dict) else None
            scenes.append(
                {"id": entity, "name": name if isinstance(name, str) and name else entity}
            )
        return sorted(scenes, key=lambda s: (s["name"].casefold(), s["id"]))

    def check(self) -> None:
        self._json(self._request("GET", "/api/"))

    def close(self) -> None:
        if self._owned:
            self._client.close()

    def _request(self, method: str, path: str, **kwargs) -> httpx2.Response:
        # `from None`: a chained httpx2 exception carries the request, whose headers hold the token.
        try:
            response = self._client.request(
                method, f"{self._url}{path}", headers=self._headers, timeout=_TIMEOUT, **kwargs
            )
        except httpx2.InvalidURL:
            raise HaError("Invalid Home Assistant URL") from None
        except UnicodeError:
            raise HaError("Access token has invalid characters") from None
        except httpx2.RequestError as e:
            if _is_tls(e):
                raise HaError(_TLS_MESSAGE) from None
            raise HaError(
                f"Can't reach Home Assistant at {self._url} ({type(e).__name__})"
            ) from None
        if response.status_code == 401:
            raise HaError("Home Assistant rejected the access token")
        if not response.is_success:
            raise HaError(f"Home Assistant returned HTTP {response.status_code}")
        return response

    @staticmethod
    def _json(response: httpx2.Response) -> object:
        try:
            return response.json()
        except ValueError:
            raise HaError(_BAD_REPLY) from None


def _is_tls(exc: BaseException | None) -> bool:
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, ssl.SSLError):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False
