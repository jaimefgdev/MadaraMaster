"""Detect situations where a file-level wipe cannot remove every copy.

MadaraMaster overwrites files in place.  Some storage setups keep old data
somewhere the overwrite never reaches; this module spots the common ones so
the CLI can warn *before* anything is wiped.  Detection is best effort and
strictly read-only: it parses mount tables, reads environment variables and
asks the OS for the volume's filesystem name.  It never opens a device and
never raises — an unknown answer simply produces no warning.
"""

from __future__ import annotations

import os
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Optional


class Residue(str, Enum):
    """A reason why copies of the data may survive a file-level wipe."""

    COW_FS = "cow_fs"
    NETWORK = "network"
    CLOUD_SYNC = "cloud_sync"
    DATA_JOURNAL = "data_journal"


# Copy-on-write / log-structured filesystems: overwrites go to new blocks.
COW_FILESYSTEMS = frozenset(
    {"btrfs", "zfs", "apfs", "refs", "f2fs", "nilfs2", "bcachefs", "jffs2", "ubifs"}
)

# The data lives on another machine (with its own snapshots and caches).
NETWORK_FILESYSTEMS = frozenset(
    {
        "nfs", "nfs4", "cifs", "smb", "smb2", "smb3", "smbfs", "afpfs", "webdav",
        "davfs", "fuse.sshfs", "sshfs", "fuse.rclone", "9p", "afs", "ceph",
        "glusterfs", "fuse.glusterfs",
    }
)

# Folder names used by sync clients (compared case-insensitively).
_CLOUD_DIR_NAMES = frozenset(
    {
        "dropbox", "google drive", "googledrive", "my drive", "icloud drive",
        "iclouddrive", "mobile documents", "cloudstorage", "pcloud drive",
        "nextcloud", "owncloud", "megasync",
    }
)
_CLOUD_ENV_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def _is_within(child: str, parent: str) -> bool:
    child, parent = _norm(child), _norm(parent)
    if child == parent:
        return True
    return child.startswith(parent.rstrip(os.sep) + os.sep)


# ─── Cloud sync ──────────────────────────────────────────────────────────────


def is_cloud_synced(path: str, environ: Optional[dict[str, str]] = None) -> bool:
    """Return True if *path* sits inside a folder managed by a sync client."""
    env = os.environ if environ is None else environ
    for var in _CLOUD_ENV_VARS:
        root = env.get(var)
        if root and _is_within(path, root):
            return True
    for part in Path(path).parts:
        name = part.strip().casefold()
        if name in _CLOUD_DIR_NAMES or name == "onedrive" or name.startswith("onedrive - "):
            return True
    return False


# ─── Mount tables ────────────────────────────────────────────────────────────


def _unescape_mount(field: str) -> str:
    """Decode the octal escapes (``\\040`` = space) used in /proc mount tables."""
    out, i = [], 0
    while i < len(field):
        if field[i] == "\\" and i + 3 < len(field) and field[i + 1 : i + 4].isdigit():
            out.append(chr(int(field[i + 1 : i + 4], 8)))
            i += 4
        else:
            out.append(field[i])
            i += 1
    return "".join(out)


def parse_mountinfo(text: str, path: str) -> Optional[tuple[str, set[str]]]:
    """Find the filesystem type and mount options for *path* in /proc/self/mountinfo.

    Returns ``(fstype, options)`` for the longest matching mount point, or None.
    """
    best: Optional[tuple[int, str, set[str]]] = None
    for line in text.splitlines():
        if " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        lf, rf = left.split(), right.split()
        if len(lf) < 6 or len(rf) < 1:
            continue
        mount_point = _unescape_mount(lf[4])
        if not _is_within(path, mount_point):
            continue
        options = set(lf[5].split(","))
        if len(rf) >= 3:
            options |= set(rf[2].split(","))
        if best is None or len(mount_point) >= best[0]:
            best = (len(mount_point), rf[0].lower(), options)
    return (best[1], best[2]) if best else None


def parse_bsd_mount(text: str, path: str) -> Optional[tuple[str, set[str]]]:
    """Same as :func:`parse_mountinfo` for the output of macOS/BSD ``mount``.

    Lines look like ``/dev/disk3s1 on /System/Volumes/Data (apfs, local, journaled)``.
    """
    best: Optional[tuple[int, str, set[str]]] = None
    for line in text.splitlines():
        if " on " not in line or not line.rstrip().endswith(")"):
            continue
        rest = line.split(" on ", 1)[1]
        idx = rest.rfind(" (")
        if idx < 0:
            continue
        mount_point = rest[:idx]
        fields = [f.strip() for f in rest[idx + 2 : -1].split(",")]
        if not fields or not _is_within(path, mount_point):
            continue
        if best is None or len(mount_point) >= best[0]:
            best = (len(mount_point), fields[0].lower(), set(fields[1:]))
    return (best[1], best[2]) if best else None


def _filesystem_linux(path: str) -> Optional[tuple[str, set[str]]]:
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as fh:
            return parse_mountinfo(fh.read(), path)
    except OSError:
        return None


def _filesystem_macos(path: str) -> Optional[tuple[str, set[str]]]:
    try:
        out = subprocess.run(
            ["/sbin/mount"], capture_output=True, text=True, timeout=5, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_bsd_mount(out, path)


def _filesystem_windows(path: str) -> Optional[tuple[str, set[str]]]:
    """Return ``(fs_name, {"remote"} if network drive)`` using the Win32 API."""
    if path.startswith(("\\\\", "//")):
        return ("unc", {"remote"})
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        k32.GetVolumePathNameW.restype = wintypes.BOOL
        k32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        k32.GetDriveTypeW.restype = wintypes.UINT
        k32.GetVolumeInformationW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR, wintypes.DWORD,
        ]
        k32.GetVolumeInformationW.restype = wintypes.BOOL

        root = ctypes.create_unicode_buffer(261)
        if not k32.GetVolumePathNameW(os.path.abspath(path), root, 261):
            return None
        options: set[str] = set()
        if k32.GetDriveTypeW(root.value) == 4:  # DRIVE_REMOTE
            options.add("remote")
        fs_name = ctypes.create_unicode_buffer(261)
        if not k32.GetVolumeInformationW(
            root.value, None, 0, None, None, None, fs_name, 261
        ):
            return ("unknown", options) if options else None
        return (fs_name.value.lower(), options)
    except (OSError, AttributeError, ValueError):
        return None


def filesystem_info(path: str) -> Optional[tuple[str, set[str]]]:
    """Return ``(filesystem type, mount options)`` for *path*, or None if unknown."""
    path = os.path.abspath(path)
    if sys.platform.startswith("linux"):
        return _filesystem_linux(path)
    if sys.platform == "darwin":
        return _filesystem_macos(path)
    if sys.platform == "win32":
        return _filesystem_windows(path)
    return None


# ─── Public entry point ──────────────────────────────────────────────────────


def risks_from_filesystem(fs: Optional[tuple[str, set[str]]]) -> list[Residue]:
    """Translate a ``(fstype, options)`` pair into residue risks."""
    if not fs:
        return []
    fstype, options = fs
    risks: list[Residue] = []
    if fstype in COW_FILESYSTEMS:
        risks.append(Residue.COW_FS)
    if fstype in NETWORK_FILESYSTEMS or "remote" in options or fstype == "unc":
        risks.append(Residue.NETWORK)
    if fstype in ("ext3", "ext4") and "data=journal" in options:
        risks.append(Residue.DATA_JOURNAL)
    return risks


def detect_residue_risks(path: Path) -> list[Residue]:
    """Return the reasons why copies of *path* may survive a file-level wipe.

    Never raises; returns an empty list when nothing is detected or the
    platform cannot be queried.
    """
    try:
        p = os.path.abspath(str(path))
        risks = risks_from_filesystem(filesystem_info(p))
        if is_cloud_synced(p):
            risks.append(Residue.CLOUD_SYNC)
        return risks
    except Exception:  # noqa: BLE001 - a warning helper must never break a wipe
        return []
