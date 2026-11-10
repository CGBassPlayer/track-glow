from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_dockerignore_is_allow_list_without_secrets():
    lines = [
        line.strip()
        for line in (ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert lines[0] == "*"
    allowed = {line[1:] for line in lines if line.startswith("!")}
    assert allowed == {"pyproject.toml", "uv.lock", "README.md", "src"}


def test_dockerfile_runs_headless_as_non_root_with_config_volume():
    text = (ROOT / "Dockerfile").read_text()
    assert "USER trackglow" in text
    assert "TRACK_GLOW_CONFIG=/config/settings.json" in text
    assert 'CMD ["track-glow", "--headless"]' in text
    assert "--no-dev" in text and "desktop" not in text


def test_compose_uses_host_network_and_config_volume():
    text = (ROOT / "compose.yaml").read_text()
    assert "network_mode: host" in text and "./config:/config" in text


def test_pyinstaller_spec_builds_console_app_from_main():
    text = (ROOT / "packaging" / "track-glow.spec").read_text()
    assert '"__main__.py"' in text and "console=True" in text
    assert 'collect_submodules("uvicorn")' in text
