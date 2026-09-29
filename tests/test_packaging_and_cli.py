"""Points 18 and 20 — packaging, single version, CLI options and i18n.

No real registry, device or file outside tmp is touched: the Windows
registry is replaced by a fake ``winreg`` module and subprocesses only
print help/version.
"""

import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

import madaramaster
from madaramaster import cli

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def english():
    cli.current_lang = "EN"
    yield
    cli.current_lang = "EN"


def _invoke(*args, env=None):
    return CliRunner().invoke(cli.app, list(args), env=env)


# ── Point 18: packaging ──────────────────────────────────────────────────────


def test_package_has_no_generic_top_level_modules():
    for name in ("audit", "storage", "trim", "utils", "wiper", "wiper_async", "safety"):
        assert not (ROOT / f"{name}.py").exists(), f"{name}.py must live inside madaramaster/"


def test_pyproject_declares_console_script_and_bounded_dependencies():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'madara = "madaramaster.cli:main"' in text
    deps = re.search(r"^dependencies = \[(.*?)\]", text, flags=re.S | re.M).group(1)
    specs = re.findall(r'"([^"]+)"', deps)
    assert specs, "no dependencies found"
    for spec in specs:
        assert ">=" in spec and "<" in spec.replace("<=", ""), f"unbounded dependency: {spec}"


def _built_manifest() -> str:
    """Run the manifest generation of MadaraMaster.spec (without PyInstaller)."""
    spec = (ROOT / "MadaraMaster.spec").read_text(encoding="utf-8")
    namespace = {"SPECPATH": str(ROOT)}
    exec(spec[: spec.index("a = Analysis(")], namespace)  # noqa: S102 — our own spec
    return namespace["manifest_xml"]()


def test_built_manifest_is_a_valid_application_manifest():
    """Regression: without assemblyIdentity/@version the .exe failed to start
    ("side-by-side configuration is incorrect")."""
    import xml.etree.ElementTree as ET

    ns = {"asm1": "urn:schemas-microsoft-com:asm.v1", "asm3": "urn:schemas-microsoft-com:asm.v3"}
    root = ET.fromstring(_built_manifest().encode("utf-8"))
    identity = root.find("asm1:assemblyIdentity", ns)
    assert identity is not None
    assert identity.get("type") == "win32"
    assert identity.get("name")
    version = identity.get("version")
    assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version), version
    assert version.startswith(madaramaster.__version__)
    level = root.find(".//asm3:requestedExecutionLevel", ns)
    assert level.get("level") == "asInvoker"


def test_spec_is_versioned_and_does_not_require_admin():
    spec = (ROOT / "MadaraMaster.spec").read_text(encoding="utf-8")
    assert "manifest=manifest_xml()" in spec
    assert "uac_admin=False" in spec
    assert "*.spec" not in (ROOT / ".gitignore").read_text(encoding="utf-8")
    manifest = (ROOT / "madara.manifest").read_text(encoding="utf-8")
    assert 'level="asInvoker"' in manifest
    assert 'level="requireAdministrator"' not in manifest


@pytest.mark.parametrize(
    "argv",
    [
        [sys.executable, "-m", "madaramaster", "--help"],
        [sys.executable, str(ROOT / "madara.py"), "--help"],
        [sys.executable, "-m", "madaramaster", "version"],
    ],
)
def test_entry_points_run(argv, tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    res = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=env)
    assert res.returncode == 0, res.stderr
    assert "MadaraMaster" in res.stdout or "madara" in res.stdout


def test_redirected_output_with_legacy_encoding_does_not_crash(tmp_path):
    """Regression: piping the output on Windows (cp1252) raised UnicodeEncodeError."""
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="cp1252")
    res = subprocess.run(
        [sys.executable, "-m", "madaramaster", "version"], capture_output=True, env=env
    )
    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
    assert madaramaster.__version__.encode() in res.stdout


def test_context_menu_command_for_frozen_and_source(monkeypatch):
    monkeypatch.setattr(sys, "executable", r"C:\Tools\MadaraMaster.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert cli._context_menu_command() == r'"C:\Tools\MadaraMaster.exe" wipe "%1"'

    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Python312\python.exe")
    assert cli._context_menu_command() == r'"C:\Python312\python.exe" -m madaramaster wipe "%1"'


class _FakeKey:
    def __init__(self, store, root, path):
        self.store, self.root, self.path = store, root, path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_winreg():
    store = {}
    mod = types.SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        HKEY_CLASSES_ROOT="HKCR",
        REG_SZ=1,
        store=store,
    )
    mod.CreateKey = lambda root, path: _FakeKey(store, root, path)
    mod.SetValueEx = lambda key, name, _r, _t, value: store.__setitem__(
        (key.root, key.path, name), value
    )
    return mod


def test_install_right_click_uses_current_user_hive(monkeypatch):
    fake = _fake_winreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Tools\MadaraMaster.exe")

    res = _invoke("install-right-click")

    assert res.exit_code == 0, res.output
    roots = {root for root, _, _ in fake.store}
    assert roots == {"HKCU"}, "must not write to HKEY_CLASSES_ROOT (needs admin)"
    cmd = fake.store[("HKCU", r"Software\Classes\*\shell\MadaraMaster\command", "")]
    assert cmd == r'"C:\Tools\MadaraMaster.exe" wipe "%1"'


def test_install_right_click_refuses_off_windows(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    res = _invoke("install-right-click")
    assert res.exit_code == 1


# ── Point 20: single version, options, i18n ─────────────────────────────────


def test_version_comes_from_one_place():
    res = _invoke("version")
    assert res.exit_code == 0
    assert f"v{madaramaster.__version__}" in res.output
    for path in (ROOT / "madaramaster").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "4.0.0" not in text and "v6.0" not in text, path.name


def test_standard_is_an_enum(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    assert _invoke("wipe", str(f), "--dry-run", "-s", "PURGE").exit_code == 0
    bad = _invoke("wipe", str(f), "--dry-run", "-s", "gutmann")
    assert bad.exit_code == 2
    assert f.exists()


def test_short_v_is_no_longer_verify(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    res = _invoke("wipe", str(f), "--dry-run", "-v")
    assert res.exit_code == 2
    assert f.exists()


def test_languages_have_the_same_keys():
    assert set(cli.LANG["EN"]) == set(cli.LANG["ES"])


@pytest.mark.parametrize(
    "args, env",
    [(["--lang", "es"], None), ([], {"MADARA_LANG": "es"})],
)
def test_spanish_interface_from_the_cli(tmp_path, args, env):
    res = _invoke(*args, "wipe", str(tmp_path / "missing.txt"), env=env)
    assert res.exit_code == 1
    assert "Objetivo no encontrado" in res.output


def test_english_is_the_default(tmp_path):
    res = _invoke("wipe", str(tmp_path / "missing.txt"))
    assert "Target not found" in res.output


def test_no_hardcoded_spanish_outside_the_translation_table():
    source = (ROOT / "madaramaster" / "cli.py").read_text(encoding="utf-8")
    start = source.index("LANG: dict[str, dict[str, str]] = {")
    end = source.index("current_lang: str =")
    outside = source[:start] + source[end:]
    for phrase in ("Interrumpido", "Estándar inválido", "Error durante", "El disco quedará",
                   "Saltar confirmación", "Menú contextual"):
        assert phrase not in outside, phrase
