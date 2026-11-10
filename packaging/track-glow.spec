# Build: uv run pyinstaller packaging/track-glow.spec --noconfirm  ->  dist/track-glow/
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "src" / "track_glow" / "__main__.py")],
    pathex=[str(root / "src")],
    # uvicorn picks its loop/protocol implementations by import string at runtime.
    hiddenimports=collect_submodules("uvicorn") + collect_submodules("track_glow"),
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="track-glow",
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, name="track-glow")
