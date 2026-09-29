"""Test-suite safety net for MadaraMaster.

MadaraMaster destroys data.  Every test in this suite runs under an
autouse fixture that:

* replaces ``send_trim`` and ``detect_storage_type`` with mocks, so no
  TRIM/ioctl is ever sent and no sysfs/IOCTL/diskutil query is made;
* blocks ``storage._kernel32`` (the Windows volume-IOCTL entry point);
* blocks any attempt to open a device (``/dev/*``, block/char nodes,
  ``\\\\.\\`` / ``\\\\?\\GLOBALROOT`` paths) and any ``fcntl.ioctl`` call —
  the null device is the only exception;
* redirects the default audit-log location into ``tmp_path``;
* refuses every write, rename, unlink, chmod or utime outside pytest's
  temporary directory;
* changes the working directory to the test's ``tmp_path``.

A blocked operation raises :class:`GuardViolation`, which derives from
``BaseException`` so that the broad ``except Exception`` blocks in the
engine cannot swallow it, and the test is failed on teardown as well.
"""

from __future__ import annotations

import builtins
import io
import os
import pathlib
import stat
import sys
from typing import Any
from unittest import mock

import aiofiles.threadpool
import pytest

from madaramaster import audit, residue, storage, trim
from madaramaster import cli as madara
from madaramaster import engine as wiper_async
from madaramaster.storage import StorageType

REAL_SEND_TRIM = trim.send_trim
REAL_STORAGE_KERNEL32 = storage._kernel32
REAL_DEFAULT_LOG_PATH = audit.default_log_path


class GuardViolation(BaseException):
    """Raised when code under test tries to touch something outside the sandbox."""


_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_WIN_DEVICE_PREFIXES = ("\\\\.\\", "//./", "\\\\?\\globalroot", "//?/globalroot")


# The null device is harmless and is opened by the stdlib itself (e.g.
# ``subprocess`` with ``DEVNULL``, used by ``platform.system()`` on Windows).
_NULL_DEVICES = {
    os.path.normcase(p)
    for p in (os.devnull, os.path.realpath(os.devnull), "\\\\.\\nul", "/dev/null")
}


def _is_device_path(path: Any) -> bool:
    if isinstance(path, int):
        return False
    s = os.fsdecode(os.fspath(path))
    if os.path.normcase(s) in _NULL_DEVICES:
        return False
    if s.lower().startswith(_WIN_DEVICE_PREFIXES):
        return True
    real = os.path.realpath(s)
    if os.path.normcase(real) in _NULL_DEVICES:
        return False
    if real == "/dev" or real.startswith("/dev/"):
        return True
    try:
        mode = os.stat(real).st_mode
    except OSError:
        return False
    return stat.S_ISBLK(mode) or stat.S_ISCHR(mode)


class _Guard:
    def __init__(self, allowed_root: pathlib.Path) -> None:
        self.allowed_root = os.path.normcase(os.path.realpath(allowed_root))
        self.violations: list[str] = []

    def _fail(self, msg: str) -> None:
        self.violations.append(msg)
        raise GuardViolation(msg)

    def check_device(self, path: Any, op: str) -> None:
        if _is_device_path(path):
            self._fail(f"{op}: device access blocked: {path!r}")

    def check_sandbox(self, path: Any, op: str, follow: bool = True) -> None:
        """Fail unless *path* lies inside the sandbox.

        With ``follow=False`` (unlink, rename, rmdir) the last component is
        not resolved, because those operations act on a symlink itself and
        never on its target.
        """
        if isinstance(path, int):
            return
        if os.path.normcase(os.fsdecode(os.fspath(path))) in _NULL_DEVICES:
            return
        s = os.path.abspath(os.fsdecode(os.fspath(path)))
        if follow:
            self.check_device(s, op)
            real = os.path.realpath(s)
        else:
            real = os.path.join(os.path.realpath(os.path.dirname(s)), os.path.basename(s))
        real = os.path.normcase(real)
        try:
            inside = os.path.commonpath([real, self.allowed_root]) == self.allowed_root
        except ValueError:  # different drives on Windows
            inside = False
        if not inside:
            self._fail(f"{op}: outside sandbox blocked: {path!r}")


@pytest.fixture(scope="session")
def _sandbox_root(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    return tmp_path_factory.getbasetemp()


@pytest.fixture(autouse=True)
def safety_net(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    _sandbox_root: pathlib.Path,
):
    guard = _Guard(_sandbox_root)

    # ── Never TRIM, never probe real hardware ────────────────────────────
    fake_trim = mock.Mock(name="send_trim", return_value=False)
    for mod in (trim, madara):
        monkeypatch.setattr(mod, "send_trim", fake_trim)

    fake_storage = mock.Mock(name="detect_storage_type", return_value=StorageType.HDD)
    for mod in (storage, wiper_async):
        monkeypatch.setattr(mod, "detect_storage_type", fake_storage)

    # Residue detection reads mount tables / volume info: keep it silent by
    # default so output stays deterministic; tests that need it patch it.
    fake_residue = mock.Mock(name="detect_residue_risks", return_value=[])
    monkeypatch.setattr(residue, "detect_residue_risks", fake_residue)

    # storage.py talks to volume handles through its own kernel32 instance,
    # which the CreateFileW guard below cannot see: block it outright.
    def blocked_kernel32():
        guard._fail("storage._kernel32 blocked: volume/device IOCTLs are not allowed in tests")

    monkeypatch.setattr(storage, "_kernel32", blocked_kernel32)

    # The default audit log lives in the user's profile: keep it in tmp.
    sandbox_log = tmp_path / "_default_state" / "audit.jsonl"
    for mod in (audit, madara):
        monkeypatch.setattr(mod, "default_log_path", lambda: sandbox_log)

    # ── File-system guards ───────────────────────────────────────────────
    real_os_open = os.open

    def guarded_os_open(path, flags, *args, **kwargs):
        if flags & _WRITE_FLAGS:
            guard.check_sandbox(path, "os.open(write)")
        else:
            guard.check_device(path, "os.open(read)")
        return real_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_os_open)

    def wrap_open(real_open):
        def guarded_open(file, mode="r", *args, **kwargs):
            if any(c in mode for c in "wax+"):
                guard.check_sandbox(file, f"open({mode})")
            else:
                guard.check_device(file, f"open({mode})")
            return real_open(file, mode, *args, **kwargs)

        return guarded_open

    monkeypatch.setattr(builtins, "open", wrap_open(builtins.open))
    monkeypatch.setattr(io, "open", wrap_open(io.open))
    monkeypatch.setattr(
        aiofiles.threadpool, "sync_open", wrap_open(aiofiles.threadpool.sync_open)
    )

    def wrap_path_op(name, real_fn, n_paths=1, follow=True):
        def guarded(*args, **kwargs):
            for p in args[:n_paths]:
                guard.check_sandbox(p, f"os.{name}", follow=follow)
            return real_fn(*args, **kwargs)

        return guarded

    guarded_fns: dict[str, Any] = {}
    for name, n, follow in (
        ("remove", 1, False),
        ("unlink", 1, False),
        ("rmdir", 1, False),
        ("rename", 2, False),
        ("replace", 2, False),
        ("chmod", 1, True),
        ("utime", 1, True),
        ("truncate", 1, True),
    ):
        real_fn = getattr(os, name, None)
        if real_fn is None:
            continue
        guarded_fns[name] = wrap_path_op(name, real_fn, n, follow)
        monkeypatch.setattr(os, name, guarded_fns[name])

    # Python 3.10's pathlib binds os functions at import time via an accessor.
    accessor = getattr(pathlib, "_NormalAccessor", None)
    if accessor is not None:
        for name, fn in guarded_fns.items():
            if hasattr(accessor, name):
                monkeypatch.setattr(accessor, name, staticmethod(fn))

    # ── No ioctls at all ─────────────────────────────────────────────────
    try:
        import fcntl
    except ImportError:
        fcntl = None
    if fcntl is not None:

        def blocked_ioctl(*args, **kwargs):
            guard._fail(f"fcntl.ioctl blocked: {args!r}")

        monkeypatch.setattr(fcntl, "ioctl", blocked_ioctl)

    # ── Windows: guard CreateFileW (volume / device handles) ─────────────
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.windll.kernel32
        real_create = k32.CreateFileW
        real_create.restype = ctypes.c_void_p
        generic_write = 0x40000000

        def guarded_create(path, access, *args):
            if access & generic_write:
                guard.check_sandbox(path, "CreateFileW(write)")
            else:
                guard.check_device(path, "CreateFileW(read)")
            return real_create(path, access, *args)

        monkeypatch.setattr(k32, "CreateFileW", guarded_create)

    monkeypatch.chdir(tmp_path)

    yield guard

    if guard.violations:
        pytest.fail("Safety guard violations:\n" + "\n".join(guard.violations))


@pytest.fixture
def fake_trim() -> mock.Mock:
    return madara.send_trim


@pytest.fixture
def fake_storage() -> mock.Mock:
    return wiper_async.detect_storage_type


@pytest.fixture
def fake_residue() -> mock.Mock:
    return residue.detect_residue_risks


@pytest.fixture
def audit_path(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "audit.jsonl"


@pytest.fixture
def wiper(audit_path: pathlib.Path) -> wiper_async.AsyncWiper:
    from madaramaster.audit import AuditLogger

    return wiper_async.AsyncWiper(AuditLogger(audit_path))
