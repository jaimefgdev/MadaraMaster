#!/usr/bin/env python3
# Motor asíncrono de borrado
# jaimefg1888
#
# Mitigaciones forenses de bajo nivel:
#   1. Destrucción de metadatos de inodo (MFT / ext4 Journal)
#      — MAC times → epoch 0 + renombrado múltiple con UUIDs de longitud
#        variable para machacar registros de nombre en la MFT/Journal.
#   2. Direct I/O (bypass de la caché de páginas del SO)
#      — Linux : os.O_DIRECT | os.O_SYNC con buffers mmap alineados a 4 096 B
#        (dirección, longitud y offset alineados).
#      — Windows: FILE_FLAG_WRITE_THROUGH | FILE_FLAG_NO_BUFFERING vía
#        ctypes + msvcrt.open_osfhandle.
#      — Fallback automático a I/O normal si el FS rechaza O_DIRECT.
#   3. Destrucción de Slack Space y Alternate Data Streams
#      — Slack Space: cada pase cubre el fichero redondeado al clúster
#        (ceil(st_size / 4096) * 4096), sobrescribiendo la cola del último
#        clúster en su sitio.
#      — ADS (Windows únicamente): enumera con FindFirstStreamW /
#        FindNextStreamW y machaca cada flujo antes de borrar el archivo.
#
# Salvaguardas: los enlaces simbólicos/junctions nunca se siguen (solo se
# elimina el enlace), los ficheros no regulares se omiten y los ficheros
# con varios enlaces duros se rechazan salvo que se pida explícitamente.

from __future__ import annotations

import asyncio
import ctypes
import errno
import hashlib
import math
import mmap
import os
import platform
import secrets
import stat
import string
import sys
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

import aiofiles

from .audit import AuditLogger
from .safety import is_link_like
from .storage import SanitizationStandard, StorageType, detect_storage_type

# ─── Alignment constants ─────────────────────────────────────────────────────
_SECTOR_SIZE = 4096  # Required alignment for O_DIRECT / NO_BUFFERING
_CLUSTER_SIZE = 4096  # Default cluster size used for slack-space calculation

# ─── Windows flags ───────────────────────────────────────────────────────────
_FILE_FLAG_WRITE_THROUGH = 0x80000000
_FILE_FLAG_NO_BUFFERING = 0x20000000
_GENERIC_WRITE = 0x40000000
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_INVALID_HANDLE_VALUE: int = ctypes.c_void_p(-1).value


# ══════════════════════════════════════════════════════════════════════════════
# Generic helpers
# ══════════════════════════════════════════════════════════════════════════════


def _ensure_writable(path: Path) -> None:
    """Remove the read-only flag from *path* if set.

    Silently ignores errors (e.g. immutable flag set by ``chattr +i``).

    Args:
        path: File whose permissions should be checked.
    """
    try:
        mode = path.stat().st_mode
        if not (mode & stat.S_IWRITE):
            os.chmod(path, mode | stat.S_IWRITE)
    except OSError:
        pass


def _aligned_size(n: int, alignment: int = _SECTOR_SIZE) -> int:
    """Round *n* up to the nearest multiple of *alignment*.

    Args:
        n: Value to round up.
        alignment: Alignment boundary.

    Returns:
        Smallest multiple of *alignment* that is ≥ *n*.
    """
    return math.ceil(n / alignment) * alignment


def _random_name(length: int) -> str:
    """Generate a random lowercase-alphanumeric name of *length* characters.

    Uses :mod:`secrets` (a CSPRNG) and adds no telltale suffix such as
    ``.tmp``, so the renamed entry does not reveal that it was wiped.

    Args:
        length: Number of characters.

    Returns:
        A string such as ``"a3kfzq19wxbm"``.
    """
    chars = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


# ══════════════════════════════════════════════════════════════════════════════
# 1. Inode-metadata destruction  (MFT / ext4 Journal)
# ══════════════════════════════════════════════════════════════════════════════


def _destroy_metadata(path: Path) -> Path:
    """Erase the file's forensic footprint in the filesystem journal / MFT.

    Performs two operations:

    1. **Timestamp zeroing** — sets ``atime`` and ``mtime`` to Unix epoch 0.
       Most forensic tools (Autopsy, Sleuth Kit) rely on MAC times to
       reconstruct file activity; zeroing them removes this evidence.

    2. **Multi-rename** — renames the file 3–5 times using random names
       with the same length as the original name (at least 8 characters),
       generated with :mod:`secrets`.  Each rename overwrites a
       directory-entry record in the ext4 journal or an MFT file-name
       attribute on NTFS, making the original filename harder to recover;
       keeping the length lets the new name reuse the same entry slot.
       After each rename the timestamps are zeroed again because some
       filesystems update ``ctime`` on ``rename(2)``.

    Args:
        path: Path to the file whose metadata should be destroyed.

    Returns:
        The final path of the file after all renames.  May equal *path* if
        every rename attempt failed.
    """
    try:
        os.utime(path, times=(0, 0))
    except OSError:
        pass

    current = path
    n_renames = 3 + secrets.randbelow(3)
    dir_parent = path.parent
    length = max(8, len(path.name))

    for _ in range(n_renames):
        new_name = dir_parent / _random_name(length)
        if new_name.exists():
            continue
        try:
            current.rename(new_name)
            try:
                os.utime(new_name, times=(0, 0))
            except OSError:
                pass
            current = new_name
        except OSError:
            break  # Leave the file in its current location if rename fails

    return current


# ══════════════════════════════════════════════════════════════════════════════
# 2. Direct I/O  — OS page-cache bypass
# ══════════════════════════════════════════════════════════════════════════════

_O_NOFOLLOW: int = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY: int = getattr(os, "O_BINARY", 0)


def _write_all(fd: int, buf: bytes | memoryview) -> None:
    """Write *buf* completely to *fd*, retrying short writes.

    Raises:
        OSError: if ``write(2)`` reports that zero bytes were written.
    """
    view = memoryview(buf)
    while len(view):
        n = os.write(fd, view)
        if n <= 0:
            raise OSError(errno.EIO, "write() returned 0 bytes")
        view = view[n:]


def _check_identity(fd: int, expected: os.stat_result) -> None:
    """Make sure *fd* refers to the regular file that was ``lstat``-ed before.

    Closes the window in which a file could be swapped for a symlink or a
    different file between the safety checks and the ``open`` call.

    Raises:
        OSError: if the opened file is not the expected one.
    """
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or (st.st_dev, st.st_ino) != (
        expected.st_dev,
        expected.st_ino,
    ):
        raise OSError(errno.ESTALE, "the file changed between the checks and the open")


class _DirectIOContext:
    """Async write context that bypasses the OS page cache.

    ``O_DIRECT`` / ``FILE_FLAG_NO_BUFFERING`` require the *memory address*,
    the length and the file offset of every write to be sector-aligned.
    Python ``bytes`` objects are not aligned in memory, so in direct mode
    every write is copied into a page-aligned anonymous ``mmap`` buffer
    and padded to a multiple of :data:`_SECTOR_SIZE`.

    If the kernel still rejects a direct write (``EINVAL``), the file is
    reopened in buffered mode at the same offset and the write is retried,
    so a wipe never fails just because Direct I/O is unavailable.

    All blocking calls are dispatched to a thread pool via
    ``asyncio.to_thread`` to avoid stalling the event loop.

    Attributes:
        direct: ``True`` while writes bypass the page cache.
        closed: ``True`` after :meth:`close` has been called.
    """

    def __init__(
        self, fd: int, direct: bool, path: Path, identity: os.stat_result
    ) -> None:
        self._fd = fd
        self._path = path
        self._identity = identity
        self._buf: Optional[mmap.mmap] = None
        self.direct = direct
        self.closed = False

    # ── synchronous helpers (run in a worker thread) ──────────────────────

    def _write_aligned(self, data: bytes) -> None:
        size = _aligned_size(len(data))
        if self._buf is None or len(self._buf) < size:
            if self._buf is not None:
                self._buf.close()
            self._buf = mmap.mmap(-1, size)  # page-aligned anonymous memory
        chunk = memoryview(self._buf)[:size]
        try:
            chunk[: len(data)] = data
            if size > len(data):
                chunk[len(data) :] = bytes(size - len(data))
            _write_all(self._fd, chunk)
        finally:
            chunk.release()

    def _fallback_to_buffered(self) -> None:
        pos = os.lseek(self._fd, 0, os.SEEK_CUR)
        os.close(self._fd)
        self._fd = os.open(str(self._path), os.O_WRONLY | _O_BINARY | _O_NOFOLLOW)
        try:
            _check_identity(self._fd, self._identity)
            os.lseek(self._fd, pos, os.SEEK_SET)
        except BaseException:
            os.close(self._fd)
            self.closed = True
            raise
        self.direct = False

    def _write_sync(self, data: bytes) -> int:
        if self.direct:
            try:
                self._write_aligned(data)
                return len(data)
            except OSError as exc:
                if exc.errno not in (errno.EINVAL, errno.EOPNOTSUPP):
                    raise
                self._fallback_to_buffered()
        _write_all(self._fd, data)
        return len(data)

    def _close_sync(self) -> None:
        try:
            os.close(self._fd)
        finally:
            if self._buf is not None:
                self._buf.close()
                self._buf = None

    # ── async interface ───────────────────────────────────────────────────

    async def seek(self, offset: int) -> None:
        await asyncio.to_thread(os.lseek, self._fd, offset, os.SEEK_SET)

    async def write(self, data: bytes) -> int:
        """Write all of *data*; returns ``len(data)`` or raises ``OSError``."""
        return await asyncio.to_thread(self._write_sync, data)

    async def flush(self) -> None:
        await asyncio.to_thread(os.fsync, self._fd)

    def fileno(self) -> int:
        return self._fd

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            await asyncio.to_thread(self._close_sync)

    async def __aenter__(self) -> "_DirectIOContext":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


def _open_direct_linux(path: Path) -> tuple[int, bool]:
    """Open *path* with ``O_DIRECT | O_SYNC | O_NOFOLLOW`` on Linux.

    ``O_DIRECT`` bypasses the page cache and ``O_SYNC`` makes each
    ``write(2)`` block until the data reaches stable storage.  If the
    filesystem rejects ``O_DIRECT`` (tmpfs on older kernels, some FUSE and
    network filesystems return ``EINVAL``), the file is opened buffered and
    ``direct=False`` is returned.  ``O_NOFOLLOW`` makes the open fail on a
    symlink instead of following it.

    Returns:
        A ``(fd, direct)`` tuple.
    """
    base = os.O_WRONLY | _O_NOFOLLOW
    o_direct: int = getattr(os, "O_DIRECT", 0)
    if o_direct:
        try:
            return os.open(str(path), base | os.O_SYNC | o_direct), True
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.EOPNOTSUPP):
                raise
    return os.open(str(path), base), False


def _open_direct_windows(path: Path) -> tuple[int, bool]:
    """Open *path* with ``FILE_FLAG_WRITE_THROUGH | FILE_FLAG_NO_BUFFERING``.

    ``FILE_FLAG_OPEN_REPARSE_POINT`` prevents following a symlink or
    junction.  The Win32 ``HANDLE`` is converted to a CRT file descriptor
    via ``msvcrt.open_osfhandle`` so the rest of the code can use standard
    ``os.write`` / ``os.lseek`` calls.  Falls back to a plain buffered
    descriptor if ``CreateFileW`` fails.

    Returns:
        A ``(fd, direct)`` tuple.
    """
    import msvcrt

    k32 = ctypes.windll.kernel32
    create_file = k32.CreateFileW
    create_file.restype = ctypes.c_void_p  # HANDLE: avoid 32-bit truncation
    handle = create_file(
        str(path),
        _GENERIC_WRITE,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_WRITE_THROUGH | _FILE_FLAG_NO_BUFFERING | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle is None or handle == _INVALID_HANDLE_VALUE:
        return os.open(str(path), os.O_WRONLY | _O_BINARY), False
    try:
        return msvcrt.open_osfhandle(handle, os.O_WRONLY | _O_BINARY), True
    except OSError:
        k32.CloseHandle(ctypes.c_void_p(handle))
        raise


async def _open_direct(path: Path, identity: os.stat_result) -> _DirectIOContext:
    """Open *path* for writing with Direct I/O where supported.

    The opened descriptor is checked against *identity* (the ``lstat``
    result taken during the safety checks) so a file swapped in the
    meantime is never written.

    Args:
        path: File to open for writing.
        identity: ``os.lstat`` result of the file that passed the checks.

    Returns:
        An async context manager ready for writing.
    """

    def _open_sync() -> tuple[int, bool]:
        sys_name = platform.system().lower()
        if sys_name == "linux":
            fd, direct = _open_direct_linux(path)
        elif sys_name == "windows":
            fd, direct = _open_direct_windows(path)
        else:
            # macOS has no O_DIRECT; F_NOCACHE is not used yet.
            fd, direct = os.open(str(path), os.O_WRONLY | _O_NOFOLLOW), False
        try:
            _check_identity(fd, identity)
        except BaseException:
            os.close(fd)
            raise
        return fd, direct

    fd, direct = await asyncio.to_thread(_open_sync)
    return _DirectIOContext(fd, direct, path, identity)


# ══════════════════════════════════════════════════════════════════════════════
# 3a. Slack Space
# ══════════════════════════════════════════════════════════════════════════════


def _pass_length(file_size: int) -> int:
    """Number of bytes each overwrite pass writes for a file of *file_size*.

    The file is rounded up to a whole cluster (:data:`_CLUSTER_SIZE`).
    Writing the tail of the last cluster in place overwrites its slack
    space — the bytes between EOF and the cluster boundary that may hold
    residue of older files — with the same pattern as the rest of the
    pass.  It also keeps every direct write sector-aligned.

    Args:
        file_size: Logical size of the file in bytes.

    Returns:
        ``file_size`` rounded up to a multiple of :data:`_CLUSTER_SIZE`.
    """
    return _aligned_size(file_size, _CLUSTER_SIZE)


# ══════════════════════════════════════════════════════════════════════════════
# 3b. Alternate Data Streams (Windows only)
# ══════════════════════════════════════════════════════════════════════════════


def _enumerate_ads_windows(path: Path) -> list[str]:
    """Return the names of all Alternate Data Streams attached to *path*.

    Uses the ``FindFirstStreamW`` / ``FindNextStreamW`` Win32 API (available
    since Windows Vista) to enumerate streams without any external dependency.
    The default data stream ``::$DATA`` is excluded from the result.

    Returns an empty list on non-Windows platforms or when the API is
    unavailable (e.g. on ReFS with streams disabled).

    Args:
        path: File whose ADS should be enumerated.

    Returns:
        A list of stream name strings such as ``[":thumbnail:$DATA"]``.
    """
    if sys.platform != "win32":
        return []

    BUF_CHARS = 296
    # WIN32_FIND_STREAM_DATA layout:
    #   LARGE_INTEGER StreamSize  (8 bytes)
    #   WCHAR cStreamName[296]    (592 bytes)

    class WIN32_FIND_STREAM_DATA(ctypes.Structure):
        _fields_ = [
            ("StreamSize", ctypes.c_int64),
            ("cStreamName", ctypes.c_wchar * BUF_CHARS),
        ]

    # Private kernel32 instance with explicit prototypes: without a
    # ``restype`` ctypes truncates the 64-bit find handle (a pointer) to a
    # 32-bit int and the next call crashes with an access violation.
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        find_first = k32.FindFirstStreamW
        find_next = k32.FindNextStreamW
        find_close = k32.FindClose
    except (OSError, AttributeError):
        return []

    find_first.restype = ctypes.c_void_p
    find_first.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    find_next.restype = ctypes.c_int
    find_next.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    find_close.restype = ctypes.c_int
    find_close.argtypes = [ctypes.c_void_p]

    data = WIN32_FIND_STREAM_DATA()
    handle = find_first(str(path), 0, ctypes.byref(data), 0)

    if handle is None or handle == _INVALID_HANDLE_VALUE:
        return []

    ads_names: list[str] = []
    try:
        while True:
            name = data.cStreamName
            if name and name != "::$DATA":
                ads_names.append(name)
            if not find_next(handle, ctypes.byref(data)):
                break
    finally:
        find_close(handle)

    return ads_names


async def _wipe_ads_windows(path: Path, buffer_size: int) -> None:
    """Overwrite and delete every Alternate Data Stream of *path*.

    ADS are enumerated before touching the main stream because
    ``FindFirstStreamW`` requires the file to still exist.  Each stream is
    overwritten with random bytes, fsynced, and then removed.

    This is a no-op on non-Windows platforms.

    Args:
        path: File whose ADS should be wiped.
        buffer_size: Maximum chunk size for random-data writes.
    """
    if sys.platform != "win32":
        return

    ads_list = await asyncio.to_thread(_enumerate_ads_windows, path)
    for stream_name in ads_list:
        ads_path_str = f"{path}{stream_name}"
        try:
            ads_size = os.path.getsize(ads_path_str)
        except OSError:
            continue

        if ads_size <= 0:
            try:
                os.remove(ads_path_str)
            except OSError:
                pass
            continue

        try:
            async with aiofiles.open(ads_path_str, "rb+") as ads_f:
                remaining = ads_size
                while remaining > 0:
                    chunk = min(remaining, buffer_size)
                    data = await asyncio.to_thread(os.urandom, chunk)
                    await ads_f.write(data)
                    remaining -= chunk
                await ads_f.flush()
                await asyncio.to_thread(os.fsync, ads_f.fileno())
        except OSError:
            pass

        try:
            os.remove(ads_path_str)
        except OSError:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# Main engine
# ══════════════════════════════════════════════════════════════════════════════

ProgressCallbackType = Optional[
    Callable[
        [Path, int, int, int],
        Coroutine[Any, Any, None] | None,
    ]
]


class AsyncWiper:
    """Asynchronous secure-erase engine.

    Combines Direct I/O, multi-pass overwriting, slack-space wiping, ADS
    destruction (Windows) and inode-metadata scrubbing into a single
    ``await``-able call.  TRIM is not sent per file: the caller decides
    whether to send it once for the whole batch (``madara wipe --trim``).

    Args:
        audit_logger: Optional :class:`~audit.AuditLogger` instance.
            Defaults to a logger writing to :func:`audit.default_log_path`.
            Pass :class:`audit.NullAuditLogger` to disable logging.
        hash_before: Record the SHA-256 of each file's contents in the
            audit log before wiping it.  Off by default: the digest lets
            anyone with the log confirm what the file contained, and it
            costs a full extra read of every file.
    """

    def __init__(
        self,
        audit_logger: Optional[AuditLogger] = None,
        hash_before: bool = False,
    ) -> None:
        self.audit = audit_logger if audit_logger is not None else AuditLogger()
        self.hash_before = hash_before
        self.BUFFER_HDD = 10 * 1024 * 1024  # 10 MB
        self.BUFFER_SSD = 50 * 1024 * 1024  # 50 MB
        self._storage_cache: dict[int, StorageType] = {}

    def storage_type_for(self, path: Path) -> StorageType:
        """Detected storage type of the device holding *path* (cached per device)."""
        try:
            dev = os.lstat(path).st_dev
        except OSError:
            return detect_storage_type(path)
        if dev not in self._storage_cache:
            self._storage_cache[dev] = detect_storage_type(path)
        return self._storage_cache[dev]

    def plan(self, path: Path, standard: SanitizationStandard) -> list[str]:
        """Return the pass patterns that :meth:`wipe_file` will use for *path*.

        Lets the UI show the real number of passes before wiping starts.
        """
        return self._get_passes_config(self.storage_type_for(path), standard)

    async def wipe_file(
        self,
        path: Path,
        standard: SanitizationStandard = SanitizationStandard.NIST_CLEAR,
        verify: bool = False,
        progress_callback: ProgressCallbackType = None,
        allow_hardlinks: bool = False,
    ) -> dict[str, Any]:
        """Securely erase a single file.

        Execution order:

        1. Safety checks on ``lstat``: a symlink or junction is unlinked
           without being followed; anything that is not a regular file is
           refused; a file with several hard links is refused unless
           *allow_hardlinks* is set.
        2. ADS enumeration and wiping (Windows only).
        3. Open the file with Direct I/O (falls back if unsupported) and
           check that the descriptor is the file that passed step 1.
        4. Overwrite with the pass sequence dictated by *standard* and the
           detected storage type.  Every pass covers the file rounded up
           to a whole cluster, which also overwrites the slack space.
        5. Optionally verify: re-read the file and compare it with the
           SHA-256 of what the last pass wrote.  On mismatch the file is
           **not** deleted.
        6. Destroy inode metadata (timestamps + multi-rename) and delete.
           If the delete fails the operation is reported as failed with
           the file's current path.
        7. Write an audit-log record.

        Args:
            path: Absolute path to the file to wipe.
            standard: Sanitization standard that controls the number of
                passes for HDDs.
            verify: Re-read and compare the file after the last pass.
                Always on for :attr:`SanitizationStandard.NIST_PURGE`.
            progress_callback: Optional async or sync callable with
                signature ``(path, pass_index, bytes_written, file_size)``.
            allow_hardlinks: Wipe files with more than one hard link.
                Overwriting such a file also destroys the data seen
                through its other names.

        Returns:
            A dictionary with the following keys:

            * ``success`` (bool)
            * ``passes_completed`` (int)
            * ``verified`` (bool | None)
            * ``duration`` (float) — seconds
            * ``strategy`` (str)
            * ``error`` (str | None)
            * ``storage_type`` (str) — detected storage type
            * ``direct_io`` (bool)
            * ``ads_wiped`` (int)
            * ``slack_wiped`` (bool)
            * ``final_path`` (str | None) — where the file still is when
              it could not be deleted
        """
        result: dict[str, Any] = {
            "success": False,
            "passes_completed": 0,
            "verified": False,
            "duration": 0.0,
            "strategy": "Unknown",
            "error": None,
            "storage_type": None,
            "direct_io": False,
            "ads_wiped": 0,
            "slack_wiped": False,
            "final_path": None,
        }

        path = Path(path)
        sha256_before: Optional[str] = None
        file_size_for_audit = 0
        verify = verify or standard == SanitizationStandard.NIST_PURGE

        try:
            try:
                st = path.lstat()
            except FileNotFoundError:
                raise FileNotFoundError(f"File not found: {path}") from None

            # ── 1. Safety checks ──────────────────────────────────────────
            if is_link_like(st):
                # Never follow a link: overwriting it would destroy its target.
                await asyncio.to_thread(os.unlink, path)
                result["strategy"] = "Link (removed without following it)"
                result["success"] = True
                self._audit(path, 0, sha256_before, standard, result)
                return result

            if not stat.S_ISREG(st.st_mode):
                raise ValueError(f"Not a regular file, skipped: {path}")

            if st.st_nlink > 1 and not allow_hardlinks:
                raise ValueError(
                    f"The file has {st.st_nlink} hard links; overwriting it would also "
                    "destroy the data seen through the other names. "
                    "Use --allow-hardlinks to force it."
                )

            file_size_for_audit = st.st_size
            _ensure_writable(path)
            storage_type = self.storage_type_for(path)
            result["storage_type"] = storage_type.value

            if storage_type in (StorageType.SSD, StorageType.NVME):
                strategy_name = "SSD/NVMe"
                buffer_size = self.BUFFER_SSD
            else:
                strategy_name = "HDD"
                buffer_size = self.BUFFER_HDD

            result["strategy"] = f"{strategy_name} ({standard.value})"

            if self.hash_before:
                sha256_before = await self._calculate_sha256(path)
            passes_config = self._get_passes_config(storage_type, standard)
            passes_done = 0
            start_time = time.time()

            # ── 2. ADS: enumerate and destroy before touching the main
            #        stream, while FindFirstStreamW can still find them.
            if sys.platform == "win32":
                ads_before = await asyncio.to_thread(_enumerate_ads_windows, path)
                await _wipe_ads_windows(path, buffer_size)
                result["ads_wiped"] = len(ads_before)

            # ── 3. Open with Direct I/O ───────────────────────────────────
            ctx = await _open_direct(path, st)
            result["direct_io"] = ctx.direct

            # ── 4. Overwrite passes (slack space included) ────────────────
            file_size = file_size_for_audit
            pass_len = _pass_length(file_size)
            last_digest: Optional[str] = None
            try:
                for pass_idx, pattern_type in enumerate(passes_config, 1):
                    await ctx.seek(0)
                    is_last = pass_idx == len(passes_config)
                    hasher = hashlib.sha256() if verify and is_last else None
                    written = 0

                    while written < pass_len:
                        chunk_len = min(pass_len - written, buffer_size)
                        data = await self._generate_pattern(pattern_type, chunk_len)
                        if hasher is not None and written < file_size:
                            hasher.update(memoryview(data)[: file_size - written])
                        await ctx.write(data)
                        written += chunk_len
                        await self._report_progress(
                            progress_callback, path, pass_idx, min(written, file_size), file_size
                        )

                    await ctx.flush()
                    passes_done += 1
                    if hasher is not None:
                        last_digest = hasher.hexdigest()

                result["slack_wiped"] = passes_done > 0 and pass_len > 0
                result["direct_io"] = ctx.direct
            finally:
                # Always close the descriptor, even on mid-pass I/O errors.
                await ctx.close()

            result["duration"] = time.time() - start_time
            result["passes_completed"] = passes_done

            # ── 5. Verification ───────────────────────────────────────────
            if verify:
                verified = await self._verify_written(path, file_size, last_digest)
                result["verified"] = verified
                if not verified:
                    raise _VerificationFailed(
                        "Verification failed: the data read back does not match the "
                        f"last pass. The file was NOT deleted: {path}"
                    )
            else:
                result["verified"] = None

            # ── 6. Metadata destruction + unlink ─────────────────────────
            current_path = path
            try:
                current_path = await asyncio.to_thread(_destroy_metadata, path)
                await asyncio.to_thread(current_path.unlink)
            except OSError as exc:
                result["final_path"] = str(current_path)
                raise OSError(
                    f"Overwritten but NOT deleted; the file is still at {current_path}: {exc}"
                ) from exc

            result["success"] = True

        except Exception as exc:
            result["error"] = str(exc)
            result["success"] = False

        self._audit(path, file_size_for_audit, sha256_before, standard, result)
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _audit(
        self,
        path: Path,
        file_size: int,
        sha256_before: Optional[str],
        standard: SanitizationStandard,
        result: dict[str, Any],
    ) -> None:
        self.audit.log_wipe_operation(path, file_size, sha256_before, standard.value, result)

    @staticmethod
    async def _report_progress(
        callback: ProgressCallbackType,
        path: Path,
        pass_idx: int,
        bytes_done: int,
        file_size: int,
    ) -> None:
        if not callback:
            return
        ret = callback(path, pass_idx, bytes_done, file_size)
        if asyncio.iscoroutine(ret):
            await ret

    def _get_passes_config(
        self,
        storage_type: StorageType,
        standard: SanitizationStandard,
    ) -> list[str]:
        """Return the ordered list of pass patterns for the given parameters.

        Args:
            storage_type: Detected storage technology.
            standard: Requested sanitization level.

        Returns:
            A list of pattern identifiers: ``"zeros"``, ``"ones"``,
            ``"random"``.
        """
        if storage_type in (StorageType.SSD, StorageType.NVME):
            return ["random"]
        if standard == SanitizationStandard.NIST_CLEAR:
            return ["zeros"]
        return ["zeros", "ones", "random"]

    async def _generate_pattern(self, pattern_type: str, size: int) -> bytes:
        """Generate a buffer of *size* bytes for an overwrite pass.

        Args:
            pattern_type: One of ``"zeros"``, ``"ones"``, or ``"random"``.
            size: Number of bytes to generate.

        Returns:
            The pattern buffer.
        """
        if pattern_type == "zeros":
            return b"\x00" * size
        if pattern_type == "ones":
            return b"\xFF" * size
        return await asyncio.to_thread(os.urandom, size)

    async def _calculate_sha256(self, path: Path) -> str:
        """Compute the SHA-256 digest of *path* before wiping.

        Streamed in 1 MB chunks to keep memory usage bounded.

        Args:
            path: File to hash.

        Returns:
            Hex-encoded SHA-256 digest, or ``"hash_error"`` on failure.
        """
        sha256 = hashlib.sha256()
        try:
            async with aiofiles.open(path, "rb") as f:
                while chunk := await f.read(1024 * 1024):
                    sha256.update(chunk)
        except Exception:
            return "hash_error"
        return sha256.hexdigest()

    async def _verify_written(
        self,
        path: Path,
        file_size: int,
        expected_digest: Optional[str],
    ) -> bool:
        """Re-read the first *file_size* bytes and compare with the last pass.

        The comparison is exact: the SHA-256 of what the last pass wrote
        over the file's logical range is compared with the SHA-256 of what
        is read back.  On Linux the page cache for the file is dropped first
        (``POSIX_FADV_DONTNEED``) so the data comes from the device.

        Args:
            path: File to verify (still present on disk).
            file_size: Original logical size of the file.
            expected_digest: Digest recorded while writing the last pass.

        Returns:
            ``True`` if the contents match, ``False`` otherwise.
        """
        if file_size == 0:
            return True
        if expected_digest is None:
            return False

        def _read_sync() -> bool:
            fd = os.open(str(path), os.O_RDONLY | _O_BINARY | _O_NOFOLLOW)
            try:
                if hasattr(os, "posix_fadvise"):
                    try:
                        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
                    except OSError:
                        pass
                sha256 = hashlib.sha256()
                remaining = file_size
                while remaining > 0:
                    chunk = os.read(fd, min(remaining, 1024 * 1024))
                    if not chunk:
                        return False
                    sha256.update(chunk)
                    remaining -= len(chunk)
                return sha256.hexdigest() == expected_digest
            finally:
                os.close(fd)

        try:
            return await asyncio.to_thread(_read_sync)
        except OSError:
            return False


class _VerificationFailed(Exception):
    """The re-read contents did not match the last overwrite pass."""
