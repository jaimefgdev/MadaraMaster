"""Points 9 and 10 — interactive input parsing and the shared wipe flow.

The engine is either mocked or runs on files inside ``tmp_path`` only.
"""

import os
from pathlib import Path
from unittest import mock

import pytest

import madara
from wiper import WipeSummary


@pytest.fixture(autouse=True)
def english():
    madara.current_lang = "EN"
    yield
    madara.current_lang = "EN"


# ── Point 9: parsing ─────────────────────────────────────────────────────────


def test_unquoted_path_with_spaces_is_one_path(tmp_path):
    (tmp_path / "My Documents").mkdir()
    f = tmp_path / "My Documents" / "secret.pdf"
    f.write_bytes(b"x")
    (tmp_path / "My").mkdir()  # a decoy that the old parser would have queued

    assert madara._parse_input_line(str(f)) == [str(f)]


def test_apostrophe_in_name(tmp_path):
    f = tmp_path / "it's mine.txt"
    f.write_bytes(b"x")
    assert madara._parse_input_line(str(f)) == [str(f)]
    assert madara._parse_input_line(f'"{f}"') == [str(f)]


def test_several_quoted_paths(tmp_path):
    a = tmp_path / "a b.txt"
    b = tmp_path / "c d.txt"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    assert madara._parse_input_line(f'"{a}" "{b}"') == [str(a), str(b)]


@pytest.mark.skipif(os.name == "nt", reason="backslash escapes are POSIX-only")
def test_backslash_escaped_spaces_from_drag_and_drop(tmp_path):
    a = tmp_path / "a b.txt"
    b = tmp_path / "c.txt"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    line = str(a).replace(" ", "\\ ") + " " + str(b)
    assert madara._parse_input_line(line) == [str(a), str(b)]


def test_unbalanced_quote_does_not_crash(tmp_path):
    assert madara._parse_input_line('"unterminated path') == ["\"unterminated path"]


def test_empty_line():
    assert madara._parse_input_line("   ") == []


# ── Point 10: interactive session ────────────────────────────────────────────


def _run_session(monkeypatch, lines):
    it = iter(lines)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    madara.interactive_session()


@pytest.fixture
def engine(monkeypatch):
    fake = mock.AsyncMock(return_value=WipeSummary(total_files=1, files_wiped=1))
    monkeypatch.setattr(madara, "async_wipe_logic", fake)
    return fake


def test_directory_is_expanded_not_passed_as_is(tmp_path, monkeypatch, engine):
    d = tmp_path / "My Dir"
    d.mkdir()
    (d / "a.txt").write_bytes(b"a")
    (d / "sub").mkdir()
    (d / "sub" / "b.txt").write_bytes(b"b")

    _run_session(monkeypatch, [str(d), "", "WIPE", "exit"])

    engine.assert_called_once()
    files = engine.call_args.args[0]
    assert sorted(os.path.relpath(f, d) for f in files) == ["a.txt", os.path.join("sub", "b.txt")]


def test_directory_is_really_wiped_and_removed(tmp_path, monkeypatch):
    d = tmp_path / "project"
    d.mkdir()
    (d / "a.txt").write_bytes(os.urandom(100))
    (d / "sub").mkdir()
    (d / "sub" / "b.txt").write_bytes(os.urandom(100))

    _run_session(monkeypatch, [str(d), "", "WIPE", "exit"])

    assert not d.exists()


def test_directory_needs_the_confirmation_word(tmp_path, monkeypatch, engine):
    d = tmp_path / "project"
    d.mkdir()
    (d / "a.txt").write_bytes(b"a")

    _run_session(monkeypatch, [str(d), "", "y"])

    engine.assert_not_called()
    assert (d / "a.txt").exists()


def test_force_suffix_no_longer_skips_confirmation(tmp_path, monkeypatch, engine):
    f = tmp_path / "a.txt"
    f.write_bytes(b"a")

    _run_session(monkeypatch, [f"{f} --force", "", "n"])

    engine.assert_not_called()


def test_single_file_with_yes(tmp_path, monkeypatch, engine):
    f = tmp_path / "a.txt"
    f.write_bytes(b"a")
    _run_session(monkeypatch, [str(f), "", "y", "exit"])
    engine.assert_called_once()
    assert engine.call_args.args[0] == [str(f)]


def test_protected_target_is_refused(tmp_path, monkeypatch, engine):
    home = tmp_path / "home" / "alice"
    home.mkdir(parents=True)
    (home / "cv.pdf").write_bytes(b"x")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    _run_session(monkeypatch, [str(home), ""])

    engine.assert_not_called()
    assert (home / "cv.pdf").exists()


def test_symlink_in_queued_directory_is_not_followed(tmp_path, monkeypatch, engine):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"KEEP")
    d = tmp_path / "victim"
    d.mkdir()
    try:
        (d / "link").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")

    _run_session(monkeypatch, [str(d), "", "WIPE", "exit"])

    assert engine.call_args.args[0] == [str(d / "link")]


def test_exit_keyword(monkeypatch, engine):
    _run_session(monkeypatch, ["exit"])
    engine.assert_not_called()
