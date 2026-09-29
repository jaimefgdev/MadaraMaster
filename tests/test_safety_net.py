"""The test sandbox itself must hold: no devices, no writes outside tmp, no TRIM."""

import os
import sys
from pathlib import Path

import pytest

import storage
import trim
import wiper_async
from conftest import GuardViolation


def test_trim_and_storage_detection_are_mocked(fake_trim, fake_storage):
    assert trim.send_trim is fake_trim
    assert wiper_async.send_trim is fake_trim
    assert storage.detect_storage_type is fake_storage
    assert wiper_async.detect_storage_type is fake_storage


@pytest.mark.parametrize("path", ["\\\\.\\PhysicalDrive0", "//./C:"])
def test_windows_device_paths_are_blocked(safety_net, path):
    with pytest.raises(GuardViolation):
        os.open(path, os.O_RDONLY)
    safety_net.violations.clear()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX device nodes")
def test_dev_nodes_are_blocked(safety_net):
    for path in ("/dev/null", "/dev/zero"):
        with pytest.raises(GuardViolation):
            os.open(path, os.O_RDONLY)
        with pytest.raises(GuardViolation):
            open(path, "rb")
    safety_net.violations.clear()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX device nodes")
def test_symlink_to_device_is_blocked(safety_net, tmp_path):
    link = tmp_path / "disk"
    link.symlink_to("/dev/null")
    with pytest.raises(GuardViolation):
        os.open(link, os.O_WRONLY)
    safety_net.violations.clear()


def test_writes_outside_sandbox_are_blocked(safety_net):
    outside = Path(__file__).resolve().parent / "must_not_be_created.txt"
    with pytest.raises(GuardViolation):
        open(outside, "w")
    with pytest.raises(GuardViolation):
        os.open(outside, os.O_WRONLY | os.O_CREAT)
    with pytest.raises(GuardViolation):
        os.remove(Path(__file__).resolve())
    assert not outside.exists()
    safety_net.violations.clear()


@pytest.mark.skipif(sys.platform == "win32", reason="fcntl is POSIX only")
def test_ioctl_is_blocked(safety_net, tmp_path):
    import fcntl

    fd = os.open(tmp_path, os.O_RDONLY)
    try:
        with pytest.raises(GuardViolation):
            fcntl.ioctl(fd, trim._FITRIM, bytearray(trim._FSTRIM_RANGE))
    finally:
        os.close(fd)
    safety_net.violations.clear()


def test_cwd_is_sandboxed(tmp_path):
    assert Path.cwd().resolve() == tmp_path.resolve()
