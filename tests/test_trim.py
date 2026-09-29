"""Point 7 — no raw TRIM on Windows; TRIM is only sent for SSD/NVMe."""

import os
from unittest import mock

import pytest

import trim
from conftest import REAL_SEND_TRIM
from storage import StorageType


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


@pytest.mark.parametrize(
    "storage_type, expected_calls",
    [(StorageType.SSD, 1), (StorageType.NVME, 1), (StorageType.HDD, 0), (StorageType.UNKNOWN, 0)],
)
async def test_engine_only_trims_flash(tmp_path, wiper, fake_storage, fake_trim, storage_type, expected_calls):
    fake_storage.return_value = storage_type
    target = tmp_path / "f.bin"
    target.write_bytes(os.urandom(100))
    result = await wiper.wipe_file(target)
    assert result["success"], result["error"]
    assert fake_trim.call_count == expected_calls
