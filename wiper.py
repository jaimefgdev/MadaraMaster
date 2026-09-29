#!/usr/bin/env python3
# Motor de borrado síncrono — DoD 5220.22-M
# jaimefg1888
#
# Tres pases:
#   1. Ceros    (\x00)
#   2. Unos     (\xFF)
#   3. Aleatorio (os.urandom)
#
# Antes de eliminar: renombra el fichero y resetea timestamps para que las
# herramientas de carving no encuentren el inodo original.

import errno
import os
import secrets
import stat
import string
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from safety import is_link_like

CHUNK_SIZE = 256 * 1024  # 256 KB — reduces syscall overhead on large files
DOD_PASSES = 3


@dataclass
class WipeResult:
    filepath: str
    success: bool
    file_size: int = 0
    bytes_written: int = 0
    error: str = ""
    duration: float = 0.0


@dataclass
class WipeSummary:
    total_files: int = 0
    files_wiped: int = 0
    files_failed: int = 0
    total_bytes_overwritten: int = 0
    total_duration: float = 0.0
    errors: list[str] = field(default_factory=list)
    results: list[WipeResult] = field(default_factory=list)
    trims_sent: int = 0


@dataclass
class WipeTelemetry:
    """Real-time snapshot consumed by the Rich dashboard in ``madara.py``.

    All fields are updated in-place so the dashboard can read the latest
    state without any shared-memory primitives.
    """

    start_time: float = 0.0
    current_pass: int = 0
    total_passes: int = DOD_PASSES
    bytes_written_total: int = 0
    bytes_written_current_pass: int = 0
    file_size: int = 0
    current_file: str = ""
    finished: bool = False
    pass_patterns: list[str] = field(default_factory=list)
    algorithm: str = ""

    @property
    def total_target_bytes(self) -> int:
        return self.file_size * self.total_passes

    @property
    def global_progress(self) -> float:
        target = self.total_target_bytes
        if target <= 0:
            return 1.0
        return min(self.bytes_written_total / target, 1.0)


ProgressCallback = Optional[Callable[[str, int, int, int], None]]


def _overwrite_pass(
    fd: int,
    file_size: int,
    pass_number: int,
    filepath: str,
    progress_callback: ProgressCallback = None,
) -> int:
    """Write one overwrite pass to an already-open file descriptor.

    Seeks to the beginning of the file, then writes *file_size* bytes in
    chunks of :data:`CHUNK_SIZE`, calling ``os.fsync`` at the end to force
    the data to physical media.

    Args:
        fd: Open file descriptor with write access.
        file_size: Number of bytes to overwrite.
        pass_number: 1 = zeros, 2 = ones, 3 = random.
        filepath: Path string passed verbatim to *progress_callback*.
        progress_callback: Optional four-argument callable
            ``(filepath, pass_number, bytes_written, file_size)``.

    Returns:
        Total bytes written in this pass.
    """
    os.lseek(fd, 0, os.SEEK_SET)
    bytes_written = 0
    remaining = file_size

    while remaining > 0:
        chunk_len = min(CHUNK_SIZE, remaining)
        if pass_number == 1:
            data = b"\x00" * chunk_len
        elif pass_number == 2:
            data = b"\xFF" * chunk_len
        else:
            data = os.urandom(chunk_len)

        _write_all(fd, data)
        bytes_written += chunk_len
        remaining -= chunk_len

        if progress_callback:
            progress_callback(filepath, pass_number, bytes_written, file_size)

    os.fsync(fd)
    return bytes_written


def _write_all(fd: int, data: bytes) -> None:
    """Write *data* completely, retrying short writes.

    Raises:
        OSError: if ``write(2)`` reports that zero bytes were written.
    """
    view = memoryview(data)
    while len(view):
        n = os.write(fd, view)
        if n <= 0:
            raise OSError(errno.EIO, "write() devolvió 0 bytes")
        view = view[n:]


def _scrub_metadata(filepath: str) -> str:
    """Overwrite the file's timestamps and rename it to obstruct forensic recovery.

    Sets ``atime`` and ``mtime`` to Unix epoch 0 so that tools such as
    Autopsy / Sleuth Kit cannot use timestamps to reconstruct the file's
    history.  Then renames the file to a random name (generated with
    :mod:`secrets`, same length as the original, no ``.tmp`` suffix) to
    overwrite the directory entry.

    Args:
        filepath: Absolute path to the file to scrub.

    Returns:
        The new path after renaming (may equal *filepath* if the rename
        failed).
    """
    try:
        os.utime(filepath, (0, 0))
    except OSError:
        pass

    directory = os.path.dirname(filepath) or "."
    chars = string.ascii_lowercase + string.digits
    length = max(8, len(os.path.basename(filepath)))
    random_name = "".join(secrets.choice(chars) for _ in range(length))
    new_path = os.path.join(directory, random_name)

    try:
        os.rename(filepath, new_path)
        return new_path
    except OSError:
        return filepath


def _ensure_writable(filepath: str) -> None:
    """Remove the read-only flag from *filepath* if it is set.

    A no-op if the file is already writable or if ``chmod`` fails (e.g.
    due to an immutable flag set by ``chattr +i``).

    Args:
        filepath: Path to the file to make writable.
    """
    try:
        mode = os.stat(filepath).st_mode
        if not (mode & stat.S_IWRITE):
            os.chmod(filepath, mode | stat.S_IWRITE)
    except OSError:
        pass


def wipe_file(
    filepath: str,
    progress_callback: ProgressCallback = None,
) -> WipeResult:
    """Securely overwrite and delete a single file using DoD 5220.22-M.

    The file is overwritten in three passes (zeros → ones → random),
    fsynced after each pass, then renamed and deleted.  The file descriptor
    is always closed in a ``finally`` block, even when I/O errors occur
    mid-pass.

    Args:
        filepath: Path to the file to wipe.
        progress_callback: Optional progress callback; see
            :data:`ProgressCallback`.

    Returns:
        A :class:`WipeResult` describing the outcome.
    """
    start_time = time.time()
    filepath = os.path.abspath(filepath)

    try:
        st = os.lstat(filepath)
    except OSError:
        return WipeResult(
            filepath=filepath,
            success=False,
            error=f"Archivo no encontrado: {filepath}",
        )

    if is_link_like(st):
        # Never follow a link: overwriting it would destroy the target.
        try:
            os.unlink(filepath)
        except OSError as exc:
            return WipeResult(filepath=filepath, success=False, error=str(exc))
        return WipeResult(filepath=filepath, success=True, duration=time.time() - start_time)

    if not stat.S_ISREG(st.st_mode):
        return WipeResult(
            filepath=filepath,
            success=False,
            error=f"No es un fichero regular: {filepath}",
        )

    if st.st_nlink > 1:
        return WipeResult(
            filepath=filepath,
            success=False,
            error=f"El fichero tiene {st.st_nlink} enlaces duros: {filepath}",
        )

    _ensure_writable(filepath)

    try:
        file_size = os.path.getsize(filepath)
        total_bytes_written = 0

        if file_size == 0:
            final_path = _scrub_metadata(filepath)
            os.remove(final_path)
            return WipeResult(
                filepath=filepath,
                success=True,
                file_size=0,
                duration=time.time() - start_time,
            )

        flags = os.O_WRONLY | (os.O_BINARY if sys.platform == "win32" else 0)
        fd = os.open(filepath, flags)

        try:
            for pass_num in range(1, DOD_PASSES + 1):
                total_bytes_written += _overwrite_pass(
                    fd, file_size, pass_num, filepath, progress_callback
                )
        finally:
            os.close(fd)

        final_path = _scrub_metadata(filepath)
        os.remove(final_path)

        return WipeResult(
            filepath=filepath,
            success=True,
            file_size=file_size,
            bytes_written=total_bytes_written,
            duration=time.time() - start_time,
        )

    except PermissionError as exc:
        return WipeResult(
            filepath=filepath,
            success=False,
            error=f"Permiso denegado: {exc}",
            duration=time.time() - start_time,
        )
    except OSError as exc:
        return WipeResult(
            filepath=filepath,
            success=False,
            error=f"Error del sistema: {exc}",
            duration=time.time() - start_time,
        )
    except Exception as exc:
        return WipeResult(
            filepath=filepath,
            success=False,
            error=f"Error inesperado: {exc}",
            duration=time.time() - start_time,
        )


def wipe_directory(
    dirpath: str,
    progress_callback: ProgressCallback = None,
) -> WipeSummary:
    """Recursively wipe every file inside *dirpath* and then remove the tree.

    Files are wiped bottom-up so that each file's parent directory still
    exists when the wipe call is made.  Empty directories are pruned after
    all files have been processed; any directory that cannot be removed (e.g.
    due to remaining locked files) is silently skipped.

    Args:
        dirpath: Root directory to wipe.
        progress_callback: Optional progress callback forwarded to each
            :func:`wipe_file` call.

    Returns:
        A :class:`WipeSummary` aggregating results for all processed files.
    """
    summary = WipeSummary()
    start_time = time.time()
    dirpath = os.path.abspath(dirpath)

    if os.path.islink(dirpath) or not os.path.isdir(dirpath):
        summary.errors.append(f"Directorio no encontrado: {dirpath}")
        return summary

    all_files = collect_files(dirpath)
    summary.total_files = len(all_files)

    for filepath in all_files:
        result = wipe_file(filepath, progress_callback)
        summary.results.append(result)
        if result.success:
            summary.files_wiped += 1
            summary.total_bytes_overwritten += result.bytes_written
        else:
            summary.files_failed += 1
            summary.errors.append(f"{result.filepath}: {result.error}")

    for root, dirs, _ in os.walk(dirpath, topdown=False):
        for dirname in dirs:
            try:
                os.rmdir(os.path.join(root, dirname))
            except OSError:
                pass
    try:
        os.rmdir(dirpath)
    except OSError:
        pass

    summary.total_duration = time.time() - start_time
    return summary


def collect_files(target: str) -> list[str]:
    """Return a flat list of every entry to wipe under *target*.

    Links (symlinks and Windows junctions) are **never followed**: a link
    is returned as an entry of its own so the engine unlinks it without
    touching its target.  A link given as *target* is returned alone.
    Non-regular files (FIFOs, sockets, device nodes) are returned too so
    the engine can report and skip them.

    Args:
        target: A path to a single file or a directory root.

    Returns:
        A list of absolute paths, children before parents.  Empty if
        *target* does not exist.
    """
    target = os.path.abspath(target)
    try:
        st = os.lstat(target)
    except OSError:
        return []
    if is_link_like(st) or not stat.S_ISDIR(st.st_mode):
        return [target]

    found: list[str] = []

    def _walk(directory: str) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            try:
                est = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if not is_link_like(est) and stat.S_ISDIR(est.st_mode):
                _walk(entry.path)
            else:
                found.append(entry.path)

    _walk(target)
    return found
