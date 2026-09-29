# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build definition for the Windows executable.
#
#   pip install ".[build]"
#   pyinstaller MadaraMaster.spec --clean --noconfirm
#
# Output: dist/MadaraMaster.exe (single-file console application).
# The embedded manifest (madara.manifest) requests "asInvoker": the program
# runs with the user's own rights and never asks for elevation by itself.

import re
from pathlib import Path

ROOT = Path(SPECPATH)  # noqa: F821 — provided by PyInstaller


def manifest_xml() -> str:
    """madara.manifest with {version} set from madaramaster.__version__."""
    init = (ROOT / "madaramaster" / "__init__.py").read_text(encoding="utf-8")
    version = re.search(r'__version__ = "([^"]+)"', init).group(1)
    parts = [p for p in re.split(r"[.\-+]", version) if p.isdigit()][:4]
    numeric = ".".join(parts + ["0"] * (4 - len(parts)))
    template = (ROOT / "madara.manifest").read_text(encoding="utf-8")
    return template.replace("{version}", numeric)


a = Analysis(
    [str(ROOT / "madara.py")],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MadaraMaster",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    manifest=manifest_xml(),
    uac_admin=False,
)
