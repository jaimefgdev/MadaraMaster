"""Point 1 — Direct I/O must actually work (aligned buffers, EINVAL fallback)."""

import ctypes
import errno
import os
import sys

import pytest

import wiper_async
from storage import SanitizationStandard, StorageType

_O_BINARY = getattr(os, "O_BINARY", 0)


def _supports_o_direct(directory) -> bool:
    o_direct = getattr(os, "O_DIRECT", 0)
    if not o_direct or not sys.platform.startswith("linux"):
        return False
    probe = directory / "probe"
    probe.write_bytes(b"\0" * 4096)
    try:
        fd = os.open(probe, os.O_WRONLY | o_direct)
    except OSError:
        return False
    os.close(fd)
    probe.unlink()
    return True


def _address(buf) -> int:
    return ctypes.addressof(ctypes.c_char.from_buffer(buf))


def test_direct_writes_use_aligned_memory_length_and_offset(tmp_path, monkeypatch):
    target = tmp_path / "f.bin"
    target.write_bytes(b"x" * 10_000)
    st = target.lstat()
    fd = os.open(target, os.O_WRONLY | _O_BINARY)
    ctx = wiper_async._DirectIOContext(fd, True, target, st)

    seen = []
    real_write = os.write

    def spy_write(fd_, buf):
        if isinstance(buf, memoryview):
            seen.append((_address(buf) % 4096, len(buf) % 4096, os.lseek(fd_, 0, os.SEEK_CUR) % 4096))
        return real_write(fd_, buf)

    monkeypatch.setattr(os, "write", spy_write)
    try:
        ctx._write_sync(b"a" * 5000)  # not a multiple of the sector size
        ctx._write_sync(b"b" * 8192)
    finally:
        ctx._close_sync()

    assert seen == [(0, 0, 0), (0, 0, 0)]


def test_zero_length_write_is_an_error(monkeypatch):
    monkeypatch.setattr(os, "write", lambda fd, buf: 0)
    with pytest.raises(OSError):
        wiper_async._write_all(123, b"data")


def test_short_writes_are_completed(monkeypatch):
    chunks = []

    def short_write(fd, buf):
        n = min(3, len(buf))
        chunks.append(bytes(buf[:n]))
        return n

    monkeypatch.setattr(os, "write", short_write)
    wiper_async._write_all(123, b"abcdefgh")
    assert b"".join(chunks) == b"abcdefgh"


async def test_einval_on_direct_write_falls_back_to_buffered(
    tmp_path, monkeypatch, wiper, fake_storage
):
    fake_storage.return_value = StorageType.HDD
    target = tmp_path / "secret.bin"
    target.write_bytes(os.urandom(10_000))

    monkeypatch.setattr(wiper_async.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        wiper_async,
        "_open_direct_linux",
        lambda p: (os.open(p, os.O_WRONLY | _O_BINARY), True),
    )
    real_write = os.write

    def einval_on_aligned(fd, buf):
        if isinstance(buf, memoryview) and buf.obj is not None and "mmap" in type(buf.obj).__name__:
            raise OSError(errno.EINVAL, "Invalid argument")
        return real_write(fd, buf)

    monkeypatch.setattr(os, "write", einval_on_aligned)

    result = await wiper.wipe_file(target, SanitizationStandard.NIST_PURGE, verify=True)

    assert result["success"], result["error"]
    assert result["direct_io"] is False
    assert result["verified"] is True
    assert not target.exists()


@pytest.mark.parametrize("size", [0, 1, 100, 4096, 10_000, 3 * 1024 * 1024 + 7])
async def test_each_pass_covers_the_last_cluster(tmp_path, monkeypatch, wiper, size):
    target = tmp_path / "f.bin"
    target.write_bytes(os.urandom(size))

    lengths = []
    real = wiper_async._DirectIOContext._write_sync

    def spy(self, data):
        lengths.append(len(data))
        return real(self, data)

    monkeypatch.setattr(wiper_async._DirectIOContext, "_write_sync", spy)
    result = await wiper.wipe_file(target, SanitizationStandard.NIST_PURGE)

    assert result["success"], result["error"]
    cluster_rounded = -(-size // 4096) * 4096
    assert sum(lengths) == 3 * cluster_rounded
    assert result["slack_wiped"] is (size > 0)
    assert not target.exists()


async def test_real_o_direct_wipe_succeeds(tmp_path, wiper, fake_storage):
    """Regression: every wipe failed with EINVAL on ext4 (unaligned buffers)."""
    if not _supports_o_direct(tmp_path):
        pytest.skip("filesystem does not support O_DIRECT")
    fake_storage.return_value = StorageType.HDD
    for size in (100, 4096, 70_000):
        target = tmp_path / f"secret_{size}.bin"
        target.write_bytes(os.urandom(size))
        result = await wiper.wipe_file(target, SanitizationStandard.NIST_PURGE, verify=True)
        assert result["success"], result["error"]
        assert result["direct_io"] is True
        assert result["passes_completed"] == 3
        assert not target.exists()
