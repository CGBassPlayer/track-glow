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
    assert "**/__pycache__" in lines


def test_dockerfile_runs_headless_as_non_root_with_config_volume():
    text = (ROOT / "Dockerfile").read_text()
    assert "USER trackglow" in text
    assert "TRACK_GLOW_CONFIG=/config/settings.json" in text
    assert 'CMD ["track-glow", "--headless"]' in text
    assert "--no-dev" in text and "desktop" not in text


def test_compose_uses_host_network_and_config_volume():
    text = (ROOT / "compose.yaml").read_text()
    assert "network_mode: host" in text and "config:/config" in text
    assert "./config" not in text, "bind mounts aren't writable by the container user"


def test_windows_build_smoke_tests_headless_and_desktop():
    text = (ROOT / "packaging" / "build-windows.ps1").read_text()
    assert "--frozen" in text and "--headless" in text
    assert "QT_QPA_PLATFORM" in text and "/api/health" in text


def test_macos_build_checks_os_version_and_smoke_tests():
    text = (ROOT / "packaging" / "build-macos.sh").read_text()
    assert "-ge 14" in text and "/api/health" in text and "--frozen" in text
    assert "QT_QPA_PLATFORM" in text


def test_pyinstaller_spec_builds_console_app_from_main():
    text = (ROOT / "packaging" / "track-glow.spec").read_text()
    assert '"__main__.py"' in text and "console=True" in text
    assert 'collect_submodules("uvicorn")' in text
