"""Points 2 and 3 — links are never followed, hard links are not destroyed silently."""

import asyncio
import os
from pathlib import Path

import pytest

import wiper as sync_wiper
import wiper_async
from storage import SanitizationStandard


def _symlink(link, target, target_is_directory=False):
    try:
        os.symlink(target, link, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:  # Windows without privilege
        pytest.skip(f"symlinks not available: {exc}")


@pytest.fixture
def outside(tmp_path):
    d = tmp_path / "outside"
    d.mkdir()
    f = d / "important.txt"
    f.write_bytes(b"KEEP ME " * 100)
    return f


async def test_symlink_in_directory_does_not_touch_its_target(tmp_path, outside, wiper):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "real.txt").write_bytes(b"secret")
    _symlink(victim / "link", outside)

    entries = sync_wiper.collect_files(str(victim))
    assert sorted(os.path.basename(e) for e in entries) == ["link", "real.txt"]

    for e in entries:
        result = await wiper.wipe_file(Path(e))
        assert result["success"], result["error"]

    assert outside.read_bytes() == b"KEEP ME " * 100
    assert not os.path.lexists(victim / "link")
    assert not (victim / "real.txt").exists()


async def test_symlink_to_directory_is_not_descended(tmp_path, outside, wiper):
    victim = tmp_path / "victim"
    victim.mkdir()
    _symlink(victim / "dirlink", outside.parent, target_is_directory=True)

    entries = sync_wiper.collect_files(str(victim))
    assert entries == [str(victim / "dirlink")]

    result = await wiper.wipe_file(Path(entries[0]))
    assert result["success"], result["error"]
    assert outside.read_bytes() == b"KEEP ME " * 100
    assert not os.path.lexists(victim / "dirlink")


def test_top_level_symlink_is_returned_alone(tmp_path, outside):
    link = tmp_path / "link_to_dir"
    _symlink(link, outside.parent, target_is_directory=True)
    assert sync_wiper.collect_files(str(link)) == [str(link)]


def test_sync_engine_does_not_follow_symlinks(tmp_path, outside):
    link = tmp_path / "link"
    _symlink(link, outside)
    res = sync_wiper.wipe_file(str(link))
    assert res.success, res.error
    assert outside.read_bytes() == b"KEEP ME " * 100
    assert not os.path.lexists(link)


def test_sync_wipe_directory_does_not_follow_symlinks(tmp_path, outside):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "a.txt").write_bytes(b"secret")
    _symlink(victim / "link", outside)
    _symlink(victim / "dirlink", outside.parent, target_is_directory=True)

    summary = sync_wiper.wipe_directory(str(victim))
    assert summary.files_failed == 0, summary.errors
    assert outside.read_bytes() == b"KEEP ME " * 100
    assert not victim.exists()


async def test_file_swapped_after_checks_is_not_written(tmp_path):
    target = tmp_path / "f.bin"
    target.write_bytes(b"original")
    st = target.lstat()

    other = tmp_path / "other.bin"
    other.write_bytes(b"someone else's data")
    os.replace(other, target)  # swap in a different inode

    with pytest.raises(OSError):
        await wiper_async._open_direct(target, st)
    assert target.read_bytes() == b"someone else's data"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFOs")
async def test_fifo_is_skipped_without_blocking(tmp_path, wiper):
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    result = await asyncio.wait_for(wiper.wipe_file(fifo), timeout=10)
    assert not result["success"]
    assert "regular" in result["error"]
    assert os.path.lexists(fifo)


def _hardlink(src, dst):
    try:
        os.link(src, dst)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"hard links not available: {exc}")


async def test_hardlinked_file_is_refused_by_default(tmp_path, wiper):
    a = tmp_path / "a.txt"
    a.write_bytes(b"SHARED DATA")
    _hardlink(a, tmp_path / "b.txt")

    result = await wiper.wipe_file(a)

    assert not result["success"]
    assert "enlaces duros" in result["error"]
    assert a.read_bytes() == b"SHARED DATA"
    assert (tmp_path / "b.txt").read_bytes() == b"SHARED DATA"


async def test_hardlinked_file_is_wiped_when_allowed(tmp_path, wiper):
    a = tmp_path / "a.txt"
    a.write_bytes(b"SHARED DATA")
    _hardlink(a, tmp_path / "b.txt")

    result = await wiper.wipe_file(a, SanitizationStandard.NIST_CLEAR, allow_hardlinks=True)

    assert result["success"], result["error"]
    assert not a.exists()
    assert b"SHARED DATA" not in (tmp_path / "b.txt").read_bytes()


def test_sync_engine_refuses_hardlinks(tmp_path):
    a = tmp_path / "a.txt"
    a.write_bytes(b"SHARED DATA")
    _hardlink(a, tmp_path / "b.txt")
    res = sync_wiper.wipe_file(str(a))
    assert not res.success
    assert (tmp_path / "b.txt").read_bytes() == b"SHARED DATA"


def test_cli_allow_hardlinks_flag(tmp_path, audit_path):
    from typer.testing import CliRunner

    import madara

    victim = tmp_path / "victim"
    victim.mkdir()
    a = victim / "a.txt"
    a.write_bytes(b"SHARED DATA")
    _hardlink(a, tmp_path / "b.txt")

    runner = CliRunner()
    args = ["wipe", str(a), "-y", "-l", str(audit_path)]

    res = runner.invoke(madara.app, args)
    assert res.exception is None or isinstance(res.exception, SystemExit), res.output
    assert a.exists(), res.output

    res = runner.invoke(madara.app, args + ["--allow-hardlinks"])
    assert res.exception is None or isinstance(res.exception, SystemExit), res.output
    assert not a.exists(), res.output
