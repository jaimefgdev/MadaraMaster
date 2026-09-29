"""Point 7 — no raw TRIM on Windows; TRIM is only sent for SSD/NVMe."""

import os
from unittest import mock

import pytest
from conftest import REAL_SEND_TRIM

from madaramaster import trim
from madaramaster.storage import StorageType


def test_windows_trim_code_is_gone():
    for name in (
        "_trim_windows",
        "_open_volume_write_handle_windows",
        "_issue_trim_ioctl",
        "_IOCTL_STORAGE_MANAGE_DATA_SET_ATTRIBUTES",
    ):
        assert not hasattr(trim, name), name


@pytest.mark.parametrize("system", ["Windows", "Darwin", "FreeBSD"])
def test_send_trim_is_a_noop_off_linux(monkeypatch, tmp_path, system):
    monkeypatch.setattr(trim.platform, "system", lambda: system)
    linux = mock.Mock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(trim, "_trim_linux", linux)
    assert REAL_SEND_TRIM(tmp_path) is False
    linux.assert_not_called()


def test_send_trim_dispatches_on_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(trim.platform, "system", lambda: "Linux")
    linux = mock.Mock(return_value=True)
    monkeypatch.setattr(trim, "_trim_linux", linux)
    assert REAL_SEND_TRIM(tmp_path) is True
    linux.assert_called_once_with(tmp_path)


@pytest.mark.parametrize("storage_type", list(StorageType))
async def test_engine_never_trims_per_file(tmp_path, wiper, fake_storage, fake_trim, storage_type):
    fake_storage.return_value = storage_type
    target = tmp_path / "f.bin"
    target.write_bytes(os.urandom(100))
    result = await wiper.wipe_file(target)
    assert result["success"], result["error"]
    assert result["storage_type"] == storage_type.value
    fake_trim.assert_not_called()
