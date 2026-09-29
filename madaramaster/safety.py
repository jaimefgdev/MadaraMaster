#!/usr/bin/env python3
# Salvaguardas de MadaraMaster: enlaces y objetivos peligrosos
# jaimefg1888

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Iterable, Optional

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# Targets that may never be wiped, nor any directory that contains them.
_POSIX_PROTECTED = (
    "/home",
    "/Users",
    "/root",
    "/var",
    "/opt",
    "/srv",
    "/mnt",
    "/media",
    "/Volumes",
    "/Applications",
)

# Trees whose contents may never be wiped (system files).
_POSIX_SYSTEM_TREES = (
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/lib32",
    "/lib64",
    "/libx32",
    "/proc",
    "/run",
    "/sbin",
    "/sys",
    "/usr",
    "/System",
    "/Library",
    "/private/etc",
    "/private/var/db",
)


def is_link_like(st: os.stat_result) -> bool:
    """Return ``True`` for symlinks and Windows reparse points (junctions).

    Args:
        st: Result of ``os.lstat`` / ``DirEntry.stat(follow_symlinks=False)``.
    """
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _windows_protected() -> tuple[list[str], list[str]]:
    env = os.environ
    exact = [env.get("SystemDrive", "C:") + "\\Users"]
    trees = [
        env.get("SystemRoot", r"C:\Windows"),
        env.get("ProgramFiles", r"C:\Program Files"),
        env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        env.get("ProgramData", r"C:\ProgramData"),
    ]
    return exact, trees


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def _is_within(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:  # different drives on Windows
        return False


def find_danger(
    target: str | os.PathLike[str],
    *,
    home: Optional[str | os.PathLike[str]] = None,
    protected: Optional[Iterable[str]] = None,
    system_trees: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Explain why wiping *target* would be catastrophic, or return ``None``.

    Rejected targets:

    * a filesystem root (``/``, ``C:\\``) or a mount point;
    * the user's home directory, or any directory that contains it or
      another protected location (``/home``, ``/var``, ``C:\\Users`` …);
    * anything inside a system tree (``/etc``, ``/usr``, ``C:\\Windows`` …).

    The check runs on the literal absolute path and, unless *target* is a
    symlink (which is only unlinked, never followed), on its resolved path.

    Args:
        target: Path the user asked to wipe.
        home: Override for the home directory (testing).
        protected: Override for the protected-locations list (testing).
        system_trees: Override for the system-trees list (testing).

    Returns:
        A human-readable reason, or ``None`` if the target looks safe.
    """
    raw = os.fspath(target)
    candidates = [_norm(raw)]
    if not os.path.islink(raw):
        real = os.path.normcase(os.path.realpath(raw))
        if real not in candidates:
            candidates.append(real)

    home_dir = _norm(os.fspath(home) if home is not None else str(Path.home()))
    if protected is None or system_trees is None:
        if sys.platform == "win32":
            default_protected, default_trees = _windows_protected()
        else:
            default_protected, default_trees = list(_POSIX_PROTECTED), list(_POSIX_SYSTEM_TREES)
        protected = default_protected if protected is None else protected
        system_trees = default_trees if system_trees is None else system_trees

    protected_n = [_norm(p) for p in protected] + [home_dir]
    trees_n = [_norm(p) for p in system_trees]

    for cand in candidates:
        if os.path.dirname(cand) == cand:
            return f"{cand} is a filesystem root"
        if os.path.isdir(cand) and os.path.ismount(cand):
            return f"{cand} is a mount point"
        for p in protected_n:
            if _is_within(p, cand):
                return f"{cand} is or contains a protected location ({p})"
        for t in trees_n:
            if _is_within(cand, t):
                return f"{cand} is inside a system directory ({t})"
    return None


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
