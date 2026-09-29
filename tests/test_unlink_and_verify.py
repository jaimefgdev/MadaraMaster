"""Points 4 and 5 — failures are reported as failures; failed verification keeps the file."""

import json
import os
from pathlib import Path

import pytest

from storage import SanitizationStandard, StorageType


def _audit_records(audit_path):
    return [json.loads(line) for line in audit_path.read_text().splitlines()]


async def test_unlink_failure_is_reported_as_failure(tmp_path, monkeypatch, wiper, audit_path):
    target = tmp_path / "locked.bin"
    target.write_bytes(os.urandom(5000))

    real_unlink = Path.unlink

    def failing_unlink(self, *args, **kwargs):
        if self.parent == tmp_path and self.suffix == ".tmp":
            raise PermissionError("simulated: file is locked")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    result = await wiper.wipe_file(target)

    assert result["success"] is False
    leftover = Path(result["final_path"])
    assert leftover.exists()
    assert str(leftover) in result["error"]
    assert "NO eliminado" in result["error"]

    record = _audit_records(audit_path)[-1]
    assert record["success"] is False
    assert record["final_path"] == str(leftover)


@pytest.mark.parametrize(
    "storage_type, standard",
    [
        (StorageType.HDD, SanitizationStandard.NIST_CLEAR),  # zeros
        (StorageType.HDD, SanitizationStandard.NIST_PURGE),  # zeros, ones, random
        (StorageType.SSD, SanitizationStandard.NIST_CLEAR),  # random
    ],
)
@pytest.mark.parametrize("size", [1, 100, 4095, 4096, 10_000])
async def test_verify_passes_on_unaligned_files(
    tmp_path, wiper, fake_storage, storage_type, standard, size
):
    """Regression: slack-space data made --verify fail on files not cluster-aligned."""
    fake_storage.return_value = storage_type
    target = tmp_path / "small.bin"
    target.write_bytes(os.urandom(size))

    result = await wiper.wipe_file(target, standard, verify=True)

    assert result["success"], result["error"]
    assert result["verified"] is True
    assert not target.exists()


async def test_failed_verification_keeps_the_file(tmp_path, monkeypatch, wiper, audit_path):
    target = tmp_path / "secret.bin"
    target.write_bytes(os.urandom(10_000))

    real_read = os.read

    def corrupted_read(fd, n):
        data = real_read(fd, n)
        return bytes([data[0] ^ 0xFF]) + data[1:] if data else data

    monkeypatch.setattr(os, "read", corrupted_read)

    result = await wiper.wipe_file(target, SanitizationStandard.NIST_PURGE, verify=True)

    assert result["success"] is False
    assert result["verified"] is False
    assert "NO se ha eliminado" in result["error"]
    assert target.exists(), "a file that failed verification must not be deleted"
    assert _audit_records(audit_path)[-1]["success"] is False


async def test_verify_disabled_reports_none(tmp_path, wiper):
    target = tmp_path / "f.bin"
    target.write_bytes(b"x" * 10)
    result = await wiper.wipe_file(target)
    assert result["success"], result["error"]
    assert result["verified"] is None
