"""Point 8 — catastrophic targets are refused; directories need the name typed.

``find_danger`` is a pure check.  CLI tests replace the wipe engine with a
mock so that nothing is ever wiped here, and only use sandboxed paths.
"""

import os
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from madaramaster import cli as madara
from madaramaster.models import WipeSummary
from madaramaster.safety import find_danger


def test_filesystem_root_is_refused():
    root = os.path.abspath(os.sep)
    assert find_danger(root, protected=[], system_trees=[]) is not None


@pytest.fixture
def layout(tmp_path):
    home = tmp_path / "home" / "alice"
    (home / "docs").mkdir(parents=True)
    (home / "docs" / "cv.pdf").write_bytes(b"x")
    system = tmp_path / "sys"
    system.mkdir()
    (system / "passwd").write_bytes(b"root:x:0:0")
    return {"tmp": tmp_path, "home": home, "system": system}


def _check(path, layout, **kw):
    kw.setdefault("home", layout["home"])
    kw.setdefault("protected", [])
    kw.setdefault("system_trees", [layout["system"]])
    return find_danger(path, **kw)


def test_home_and_its_ancestors_are_refused(layout):
    assert _check(layout["home"], layout)
    assert _check(layout["home"].parent, layout)
    assert _check(layout["tmp"], layout)


def test_paths_inside_home_are_allowed(layout):
    assert _check(layout["home"] / "docs", layout) is None
    assert _check(layout["home"] / "docs" / "cv.pdf", layout) is None


def test_protected_locations_and_their_ancestors(layout):
    srv = layout["tmp"] / "srv"
    srv.mkdir()
    assert _check(srv, layout, protected=[srv])
    assert _check(srv / "inner", layout, protected=[srv]) is None


def test_system_trees_are_refused_including_contents(layout):
    assert _check(layout["system"], layout)
    assert _check(layout["system"] / "passwd", layout)


def test_mount_points_are_refused(layout, monkeypatch):
    mnt = layout["home"] / "docs"
    real_ismount = os.path.ismount
    monkeypatch.setattr(
        os.path,
        "ismount",
        lambda p: os.path.normcase(os.path.abspath(p)) == os.path.normcase(str(mnt))
        or real_ismount(p),
    )
    assert _check(mnt, layout)


def test_resolved_path_is_checked_for_directories(layout):
    link = layout["tmp"] / "innocent"
    try:
        os.symlink(layout["system"], link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    # A symlink target is only unlinked, never followed, so the link itself is fine…
    assert _check(link, layout) is None
    # …but a path *through* it resolves into the system tree.
    assert _check(link / "passwd", layout)


# ── CLI ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def engine(monkeypatch):
    fake = mock.AsyncMock(return_value=WipeSummary(total_files=1, files_wiped=1))
    monkeypatch.setattr(madara, "async_wipe_logic", fake)
    return fake


def test_cli_refuses_home_even_with_confirm(layout, monkeypatch, engine):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: layout["home"]))
    res = CliRunner().invoke(madara.app, ["wipe", str(layout["home"]), "-y"])
    assert res.exit_code == 2, res.output
    engine.assert_not_called()
    assert (layout["home"] / "docs" / "cv.pdf").exists()


def test_cli_allow_dangerous_target_flag(layout, monkeypatch, engine):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: layout["home"]))
    res = CliRunner().invoke(
        madara.app, ["wipe", str(layout["home"]), "-y", "--allow-dangerous-target"]
    )
    assert res.exit_code == 0, res.output
    engine.assert_called_once()


def test_cli_directory_requires_typing_its_name(tmp_path, engine):
    target = tmp_path / "project"
    target.mkdir()
    (target / "a.txt").write_bytes(b"x")

    res = CliRunner().invoke(madara.app, ["wipe", str(target)], input="y\n")
    assert res.exit_code == 0, res.output
    engine.assert_not_called()

    res = CliRunner().invoke(madara.app, ["wipe", str(target)], input="project\n")
    assert res.exit_code == 0, res.output
    engine.assert_called_once()


def test_cli_single_file_keeps_yes_no_prompt(tmp_path, engine):
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    res = CliRunner().invoke(madara.app, ["wipe", str(f)], input="n\n")
    assert res.exit_code == 0
    engine.assert_not_called()
    res = CliRunner().invoke(madara.app, ["wipe", str(f)], input="y\n")
    engine.assert_called_once()
