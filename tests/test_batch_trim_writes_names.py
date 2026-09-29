"""Points 14, 15 and 16 — complete writes, one TRIM per batch,
CSPRNG names without a telltale suffix."""

import errno
import os
import random
import sys

import pytest
from typer.testing import CliRunner

from madaramaster import cli as madara
from madaramaster import engine as wiper_async
from madaramaster.storage import StorageType

# ── Point 14: a zero-byte write is an error ──────────────────────────────────




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
