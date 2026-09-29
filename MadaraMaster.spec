# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build definition for the Windows executable.
#
#   pip install ".[build]"
#   pyinstaller MadaraMaster.spec --clean --noconfirm
#
# Output: dist/MadaraMaster.exe (single-file console application).
# The embedded manifest (madara.manifest) requests "asInvoker": the program
# runs with the user's own rights and never asks for elevation by itself.

a = Analysis(
    ["madara.py"],
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
    manifest="madara.manifest",
    uac_admin=False,
)
