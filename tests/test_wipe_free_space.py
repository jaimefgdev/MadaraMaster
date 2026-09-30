"""Point 6 — the fill file is always removed, even on Ctrl+C or cancellation.

The disk is never actually filled: ``aiofiles.open`` is replaced by a fake
whose ``write`` only counts bytes and raises on a scripted call.
"""

import asyncio
import errno
from pathlib import Path

import pytest

from madaramaster import cli as madara
from madaramaster import free_space


class _FakeFill:
    """Stands in for the unbuffered fill file; creates a real (empty) file."""

    def __init__(self, path, script):
        self._path = Path(path)
        self._script = list(script)
        self._fh = None

    async def __aenter__(self):
        self._fh = open(self._path, "wb")
        return self

    async def __aexit__(self, *exc):
        self._fh.close()

    async def write(self, data):
        action = self._script.pop(0) if self._script else OSError(errno.ENOSPC, "full")
        if isinstance(action, BaseException) or (
            isinstance(action, type) and issubclass(action, BaseException)
        ):
            raise action
        return len(data) if action == "ok" else action

    def fileno(self):
        return self._fh.fileno()


@pytest.fixture
def fake_fill(monkeypatch):
    state = {}

    def install(*script):
        def fake_open(path, mode="r", **kwargs):
            assert kwargs.get("buffering") == 0
            state["path"] = Path(path)
            return _FakeFill(path, script)

        monkeypatch.setattr(free_space.aiofiles, "open", fake_open)
        return state

    return install


def _enospc():
    return OSError(errno.ENOSPC, "No space left on device")


async def test_fill_until_enospc_then_removes_file(tmp_path, fake_fill, fake_trim):
    state = fake_fill("ok", "ok", "ok", _enospc(), "ok", _enospc())
    result = await madara._async_wipe_free_space(tmp_path)

    assert result["success"], result["error"]
    assert result["bytes_written"] == 3 * madara._FILL_CHUNK_LARGE + madara._FILL_CHUNK_SMALL
    assert not state["path"].exists()
    fake_trim.assert_called_once()


async def test_no_trim_is_honoured(tmp_path, fake_fill, fake_trim):
    fake_fill("ok", _enospc(), _enospc())
    result = await madara._async_wipe_free_space(tmp_path, trim=False)
    assert result["success"]
    fake_trim.assert_not_called()


async def test_short_write_is_counted_exactly(tmp_path, fake_fill):
    fake_fill(1000, _enospc(), _enospc())
    result = await madara._async_wipe_free_space(tmp_path)
    assert result["bytes_written"] == 1000


@pytest.mark.parametrize("interrupt", [asyncio.CancelledError, KeyboardInterrupt])
async def test_interrupt_removes_fill_file(tmp_path, fake_fill, fake_trim, interrupt):
    state = fake_fill("ok", "ok", interrupt)
    with pytest.raises(interrupt):
        await madara._async_wipe_free_space(tmp_path)
    assert not state["path"].exists(), "fill file left behind would keep the disk full"
    fake_trim.assert_not_called()


async def test_io_error_removes_fill_file(tmp_path, fake_fill, fake_trim):
    state = fake_fill("ok", OSError(errno.EIO, "I/O error"))
    result = await madara._async_wipe_free_space(tmp_path)
    assert result["success"] is False
    assert "I/O error" in result["error"]
    assert not state["path"].exists()
    fake_trim.assert_not_called()


async def test_cleanup_failure_is_not_success(tmp_path, fake_fill, monkeypatch, fake_trim):
    state = fake_fill("ok", _enospc(), _enospc())
    real_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self.name.startswith(".mdrmfill_"):
            raise PermissionError("simulated")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    result = await madara._async_wipe_free_space(tmp_path)

    assert result["success"] is False
    assert str(state["path"]) in result["error"]
    fake_trim.assert_not_called()
