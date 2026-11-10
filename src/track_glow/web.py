from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from track_glow import __version__

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Track Glow</title>
<style>
  :root { --bg: #f6f6f4; --fg: #1b1b1b; --muted: #666; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #141414; --fg: #eee; --muted: #999; }
  }
  body { margin: 0; padding: 2rem 1rem; background: var(--bg); color: var(--fg);
         font-family: system-ui, sans-serif; }
  main { max-width: 40rem; margin: 0 auto; }
  .muted { color: var(--muted); }
</style>
</head>
<body>
<main>
  <h1>Track Glow</h1>
  <p>No race</p>
  <p class="muted">Setup arrives in a later milestone.</p>
</main>
</body>
</html>
"""


def create_app() -> FastAPI:
    app = FastAPI(title="Track Glow", version=__version__)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
