FROM ghcr.io/astral-sh/uv:0.9.7 AS uv

FROM python:3.13-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim
RUN useradd --system --create-home --uid 10001 trackglow \
    && mkdir /config && chown trackglow /config
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    TRACK_GLOW_CONFIG=/config/settings.json \
    PYTHONUNBUFFERED=1
USER trackglow
VOLUME /config
EXPOSE 8780
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8780/api/health', timeout=4)"]
CMD ["track-glow", "--headless"]
