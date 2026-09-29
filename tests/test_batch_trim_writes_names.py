"""Points 14, 15 and 16 — complete writes (sync engine), one TRIM per batch,
CSPRNG names without a telltale suffix."""

import errno
import os
import random
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import madara
import wiper as sync_wiper
import wiper_async
from storage import StorageType


# ── Point 14: sync engine writes everything ──────────────────────────────────


def test_sync_engine_completes_short_writes(tmp_path, monkeypatch):
    f = tmp_path / "f.bin"
    f.write_bytes(os.urandom(10_000))
    real_write = os.write
    really_written = []

    def short_write(fd, buf):
        n = real_write(fd, bytes(buf[:1000]))
        really_written.append(n)
        return n

    monkeypatch.setattr(os, "write", short_write)
    res = sync_wiper.wipe_file(str(f))
    assert res.success, res.error
    assert sum(really_written) == 3 * 10_000, "short writes left part of the file untouched"
    assert not f.exists()


def test_sync_engine_zero_write_is_an_error(tmp_path, monkeypatch):
    f = tmp_path / "f.bin"
    f.write_bytes(os.urandom(10_000))
    monkeypatch.setattr(os, "write", lambda fd, buf: 0)
    res = sync_wiper.wipe_file(str(f))
    assert not res.success
    assert f.exists()


def test_async_write_all_zero_is_an_error(monkeypatch):
    monkeypatch.setattr(os, "write", lambda fd, buf: 0)
    with pytest.raises(OSError) as exc:
        wiper_async._write_all(1, b"x")
    assert exc.value.errno == errno.EIO


# ── Point 15: one TRIM per filesystem, only when asked ───────────────────────


def _files(tmp_path, n, sub="d"):
    d = tmp_path / sub
    d.mkdir(exist_ok=True)
    out = []
    for i in range(n):
        f = d / f"f{i}.bin"
        f.write_bytes(os.urandom(100))
        out.append(str(f))
    return out


async def test_trim_is_sent_once_per_filesystem(tmp_path, fake_storage, fake_trim):
    fake_storage.return_value = StorageType.SSD
    fake_trim.return_value = True
    files = _files(tmp_path, 3, "a") + _files(tmp_path, 2, "b")
    summary = await madara.async_wipe_logic(files, trim=True)
    assert summary.files_wiped == 5
    assert fake_trim.call_count == 1  # both dirs live on the same filesystem
    assert summary.trims_sent == 1


async def test_no_trim_without_flag(tmp_path, fake_storage, fake_trim):
    fake_storage.return_value = StorageType.NVME
    summary = await madara.async_wipe_logic(_files(tmp_path, 3))
    assert summary.files_wiped == 3
    fake_trim.assert_not_called()


async def test_no_trim_for_hdd(tmp_path, fake_storage, fake_trim):
    fake_storage.return_value = StorageType.HDD
    await madara.async_wipe_logic(_files(tmp_path, 2), trim=True)
    fake_trim.assert_not_called()


async def test_no_trim_when_nothing_was_wiped(tmp_path, fake_storage, fake_trim):
    fake_storage.return_value = StorageType.SSD
    missing = str(tmp_path / "missing.bin")
    summary = await madara.async_wipe_logic([missing], trim=True)
    assert summary.files_failed == 1
    fake_trim.assert_not_called()


def test_cli_trim_flag(tmp_path, fake_storage, fake_trim):
    fake_storage.return_value = StorageType.SSD
    d = tmp_path / "proj"
    d.mkdir()
    for i in range(3):
        (d / f"{i}.bin").write_bytes(b"x")
    res = CliRunner().invoke(madara.app, ["wipe", str(d), "-y", "--trim"])
    assert res.exit_code == 0, res.output
    assert fake_trim.call_count == 1


# ── Point 16: names ──────────────────────────────────────────────────────────


@pytest.fixture
def no_random_module(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the non-cryptographic random module must not be used")

    for name in ("choice", "choices", "randint", "randrange", "random"):
        monkeypatch.setattr(random, name, boom)


@pytest.mark.parametrize("name, length", [("a.txt", 8), ("quarterly_report_final.pdf", 26)])
def test_async_renames_keep_length_and_have_no_suffix(tmp_path, no_random_module, name, length):
    f = tmp_path / name
    f.write_bytes(b"x")
    final = wiper_async._destroy_metadata(f)
    assert final != f and final.exists()
    assert len(final.name) == length
    assert not final.name.endswith(".tmp")
    assert final.name.isalnum()


def test_sync_rename_keeps_length_and_has_no_suffix(tmp_path, no_random_module):
    f = tmp_path / "quarterly_report_final.pdf"
    f.write_bytes(b"x")
    final = Path(sync_wiper._scrub_metadata(str(f)))
    assert final != f and final.exists()
    assert len(final.name) == len(f.name)
    assert not final.name.endswith(".tmp")


def test_random_names_are_unpredictable():
    names = {wiper_async._random_name(16) for _ in range(200)}
    assert len(names) == 200


# ── storage.py Windows prototypes ────────────────────────────────────────────


@pytest.mark.skipif(sys.platform != "win32", reason="Windows API prototypes")
def test_storage_kernel32_prototypes():
    """Loads kernel32 and inspects prototypes only; no handle is opened."""
    from ctypes import wintypes

    from conftest import REAL_STORAGE_KERNEL32

    k32 = REAL_STORAGE_KERNEL32()
    assert k32.CreateFileW.restype is wintypes.HANDLE
    assert len(k32.CreateFileW.argtypes) == 7
    assert k32.DeviceIoControl.argtypes[0] is wintypes.HANDLE
    assert len(k32.DeviceIoControl.argtypes) == 8
    assert k32.CloseHandle.argtypes == [wintypes.HANDLE]
