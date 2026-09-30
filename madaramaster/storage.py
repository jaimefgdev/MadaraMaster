#!/usr/bin/env python3
# Detección de tipo de almacenamiento — sin subprocess, sin dependencias extras
# jaimefgdev
#
# Linux  → sysfs kernel interface (/sys/class/block, /sys/block)
#           st_dev  (major:minor) mapea a un nodo en /sys/class/block/{dev}/dev
#           rotational=0  → SSD/NVMe;  rotational=1  → HDD
#
# Windows → ctypes + DeviceIoControl
#           IOCTL_STORAGE_QUERY_PROPERTY con StorageDeviceSeekPenaltyProperty:
#             IncursSeekPenalty=False → SSD/NVMe
#           IOCTL_STORAGE_QUERY_PROPERTY con StorageDeviceProperty:
#             BusType=0x11 (BusTypeNvme) → NVMe
#
# macOS   → diskutil info (subprocess — no hay API pública ctypes sin IOKit/PyObjC)

from __future__ import annotations

import ctypes
import os
import platform
import re
import subprocess
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Optional

# ────────────────────────────────────────────────────────────────
# Enums y clases de estrategia
# ────────────────────────────────────────────────────────────────


class StorageType(Enum):
    HDD = "hdd"
    SSD = "ssd"
    NVME = "nvme"
    NETWORK = "network"
    UNKNOWN = "unknown"


class SanitizationStandard(Enum):
    NIST_CLEAR = "clear"
    NIST_PURGE = "purge"
    DOD_LEGACY = "dod"


class WipeStrategy(ABC):
    @abstractmethod
    def get_passes(self, standard: SanitizationStandard) -> int: ...

    @abstractmethod
    def get_description(self) -> str: ...


class HDDWipeStrategy(WipeStrategy):
    def get_passes(self, standard: SanitizationStandard) -> int:
        return (
            3
            if standard in (SanitizationStandard.NIST_PURGE, SanitizationStandard.DOD_LEGACY)
            else 1
        )

    def get_description(self) -> str:
        return "HDD: classic magnetic overwrite (zeros → ones → random)"


class SSDWipeStrategy(WipeStrategy):
    def get_passes(self, standard: SanitizationStandard) -> int:  # noqa: ARG002
        # NIST SP 800-88 Rev. 1 §2.4: a single cryptographic-random overwrite
        # is sufficient for NAND flash because the underlying wear-levelling
        # controller prevents precise block targeting.
        return 1

    def get_description(self) -> str:
        return "SSD/NVMe: single cryptographic-random pass"


class NVMeWipeStrategy(SSDWipeStrategy):
    def get_description(self) -> str:
        return "NVMe: single cryptographic-random pass"


def get_strategy(storage_type: StorageType) -> WipeStrategy:
    """Return the appropriate :class:`WipeStrategy` for a given storage type.

    Args:
        storage_type: The detected storage type.

    Returns:
        A concrete :class:`WipeStrategy` instance.
    """
    if storage_type == StorageType.HDD:
        return HDDWipeStrategy()
    if storage_type == StorageType.NVME:
        return NVMeWipeStrategy()
    return SSDWipeStrategy()


# ────────────────────────────────────────────────────────────────
# Dispatcher principal
# ────────────────────────────────────────────────────────────────


def detect_storage_type(path: Path) -> StorageType:
    """Detect the underlying storage technology for the device hosting *path*.

    Dispatches to a platform-specific implementation.  All errors are
    swallowed and result in :attr:`StorageType.UNKNOWN` so that callers can
    always fall back to a safe wipe strategy.

    Args:
        path: Any file-system path on the target volume.

    Returns:
        The detected :class:`StorageType`, or ``UNKNOWN`` if detection fails.
    """
    system = platform.system().lower()
    try:
        if system == "linux":
            return _detect_linux(path)
        if system == "windows":
            return _detect_windows(path)
        if system == "darwin":
            return _detect_macos(path)
    except Exception:
        pass
    return StorageType.UNKNOWN


# ════════════════════════════════════════════════════════════════
# LINUX — sysfs puro, sin subprocess
# ════════════════════════════════════════════════════════════════


def _detect_linux(path: Path) -> StorageType:
    dev_name = _resolve_dev_name_linux(path)
    if not dev_name:
        return StorageType.UNKNOWN

    base = _get_base_device_linux(dev_name)
    rotational = Path(f"/sys/block/{base}/queue/rotational")
    if not rotational.exists():
        return StorageType.UNKNOWN

    try:
        is_rotational = rotational.read_text(encoding="ascii").strip() == "1"
    except OSError:
        return StorageType.UNKNOWN

    if is_rotational:
        return StorageType.HDD
    return StorageType.NVME if "nvme" in base else StorageType.SSD


def _resolve_dev_name_linux(path: Path) -> Optional[str]:
    """Map a filesystem path to a block-device name via sysfs without forking.

    Uses ``os.stat()`` to obtain the ``st_dev`` field (major:minor pair) and
    then scans ``/sys/class/block/*/dev`` entries for a match.  This avoids
    any subprocess calls and works correctly inside containers that still
    expose sysfs.

    Args:
        path: Any path on the target filesystem.

    Returns:
        The block-device name (e.g. ``"sda3"``, ``"nvme0n1p1"``), or
        ``None`` if the device cannot be resolved.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None

    target_maj = os.major(st.st_dev)
    target_min = os.minor(st.st_dev)

    block_dir = Path("/sys/class/block")
    if not block_dir.exists():
        return None

    try:
        entries = list(block_dir.iterdir())
    except OSError:
        return None

    for entry in entries:
        dev_file = entry / "dev"
        try:
            raw = dev_file.read_text(encoding="ascii").strip()
            maj_s, min_s = raw.split(":")
            if int(maj_s) == target_maj and int(min_s) == target_min:
                return entry.name
        except (OSError, ValueError):
            continue

    return None


def _get_base_device_linux(dev_name: str) -> str:
    """Strip the partition suffix to obtain the base block device name.

    Examples::

        sda3       → sda
        nvme0n1p1  → nvme0n1
        mmcblk0p2  → mmcblk0

    The function tries ``p\\d+$`` first (NVMe / eMMC partitions) then
    ``\\d+$`` (SATA/SCSI).  The result is accepted only when the base device
    exists in ``/sys/block/`` to prevent false positives on names that happen
    to end with digits.

    Args:
        dev_name: Raw device name from ``/sys/class/block``.

    Returns:
        The base device name, or *dev_name* unchanged if no valid base
        is found.
    """
    for pattern in (r"p\d+$", r"\d+$"):
        candidate = re.sub(pattern, "", dev_name)
        if candidate != dev_name and Path(f"/sys/block/{candidate}").exists():
            return candidate
    return dev_name


# ════════════════════════════════════════════════════════════════
# WINDOWS — ctypes + DeviceIoControl
# ════════════════════════════════════════════════════════════════
#
# Two IOCTL_STORAGE_QUERY_PROPERTY queries are issued:
#   1) StorageDeviceSeekPenaltyProperty (7) → IncursSeekPenalty
#      False  →  SSD or NVMe
#      True   →  HDD
#   2) StorageDeviceProperty (0) → BusType
#      0x11 (BusTypeNvme)  →  NVMe
# ════════════════════════════════════════════════════════════════

# CTL_CODE(FILE_DEVICE_MASS_STORAGE=0x2d, 0x500, METHOD_BUFFERED=0, FILE_ANY_ACCESS=0)
_IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400

_StorageDeviceProperty = 0
_StorageDeviceSeekPenaltyProperty = 7
_PropertyStandardQuery = 0

_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_BusTypeNvme = 0x11


class _STORAGE_PROPERTY_QUERY(ctypes.Structure):
    _fields_ = [
        ("PropertyId", ctypes.c_uint32),
        ("QueryType", ctypes.c_uint32),
        ("AdditionalParameters", ctypes.c_uint8),
    ]


class _DEVICE_SEEK_PENALTY_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_uint32),
        ("Size", ctypes.c_uint32),
        ("IncursSeekPenalty", ctypes.c_bool),
    ]


class _STORAGE_DEVICE_DESCRIPTOR_HEADER(ctypes.Structure):
    """Partial descriptor used only to read the BusType field.

    The full ``STORAGE_DEVICE_DESCRIPTOR`` has variable-length string data
    at the end; we only need BusType to differentiate NVMe from SATA-SSD,
    so we map just the fixed-size header portion.
    """

    _fields_ = [
        ("Version", ctypes.c_uint32),
        ("Size", ctypes.c_uint32),
        ("DeviceType", ctypes.c_uint8),
        ("DeviceTypeModifier", ctypes.c_uint8),
        ("RemovableMedia", ctypes.c_bool),
        ("CommandQueueing", ctypes.c_bool),
        ("VendorIdOffset", ctypes.c_uint32),
        ("ProductIdOffset", ctypes.c_uint32),
        ("ProductRevisionOffset", ctypes.c_uint32),
        ("SerialNumberOffset", ctypes.c_uint32),
        ("BusType", ctypes.c_uint32),
    ]


_K32 = None


def _kernel32():
    """Private ``kernel32`` instance with explicit prototypes.

    Without ``restype`` / ``argtypes`` ctypes assumes ``int`` everywhere:
    64-bit handles are truncated to 32 bits and pointers are passed with
    the wrong width.  A private ``WinDLL`` keeps these prototypes from
    leaking into other users of ``ctypes.windll.kernel32``.
    """
    global _K32
    if _K32 is None:
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetVolumePathNameW.restype = wintypes.BOOL
        k32.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        k32.DeviceIoControl.restype = wintypes.BOOL
        k32.DeviceIoControl.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        k32.CloseHandle.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        _K32 = k32
    return _K32


def _detect_windows(path: Path) -> StorageType:
    try:
        import ctypes.wintypes  # noqa: F401 — imported for side-effects
    except ImportError:
        return StorageType.UNKNOWN

    handle = _open_volume_handle_windows(path)
    if handle == _INVALID_HANDLE_VALUE or handle is None:
        return StorageType.UNKNOWN

    try:
        is_flash = _query_seek_penalty(handle)
        if is_flash is None:
            return StorageType.UNKNOWN
        if not is_flash:
            return StorageType.HDD
        # Flash media → distinguish NVMe from SATA-SSD by BusType.
        bus = _query_bus_type(handle)
        return StorageType.NVME if bus == _BusTypeNvme else StorageType.SSD
    finally:
        _kernel32().CloseHandle(handle)


def _open_volume_handle_windows(path: Path) -> Optional[int]:
    """Open a read-only handle to the logical volume that contains *path*.

    ``GENERIC_READ`` access (with no ``dwDesiredAccess`` flags) is sufficient
    for ``IOCTL_STORAGE_QUERY_PROPERTY`` — write access is not needed and
    would trigger UAC prompts on standard user accounts.

    Args:
        path: Any path on the target volume.

    Returns:
        A valid Win32 ``HANDLE`` cast to ``int``, or ``None`` on failure.
    """
    try:
        k32 = _kernel32()
        vol_buf = ctypes.create_unicode_buffer(260)
        if not k32.GetVolumePathNameW(str(path), vol_buf, 260):
            return None

        # "C:\\" → "\\.\C:"
        drive = vol_buf.value.rstrip("\\")
        unc_path = f"\\\\.\\{drive}"

        handle = k32.CreateFileW(
            unc_path,
            0,  # no desired access needed for query IOCTLs
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle is None or handle == _INVALID_HANDLE_VALUE:
            return None
        return handle
    except Exception:
        return None


def _query_seek_penalty(handle: int) -> Optional[bool]:
    """Query whether the device incurs a seek penalty (i.e., is flash).

    ``StorageDeviceSeekPenaltyProperty`` returns a
    ``DEVICE_SEEK_PENALTY_DESCRIPTOR`` whose ``IncursSeekPenalty`` field is
    ``False`` for SSD/NVMe and ``True`` for spinning HDDs.

    Args:
        handle: An open Win32 handle to the storage volume.

    Returns:
        ``True`` if the device is flash (no seek penalty), ``False`` if it is
        a spinning disk, or ``None`` if the IOCTL call fails.
    """
    query = _STORAGE_PROPERTY_QUERY()
    query.PropertyId = _StorageDeviceSeekPenaltyProperty
    query.QueryType = _PropertyStandardQuery

    desc = _DEVICE_SEEK_PENALTY_DESCRIPTOR()
    bytes_returned = ctypes.wintypes.DWORD(0)

    ok = _kernel32().DeviceIoControl(
        handle,
        _IOCTL_STORAGE_QUERY_PROPERTY,
        ctypes.byref(query),
        ctypes.sizeof(query),
        ctypes.byref(desc),
        ctypes.sizeof(desc),
        ctypes.byref(bytes_returned),
        None,
    )
    if not ok:
        return None
    return not desc.IncursSeekPenalty


def _query_bus_type(handle: int) -> Optional[int]:
    """Return the bus-type code for the device (``0x11`` == NVMe).

    Allocates a 1 KB output buffer for the variable-length
    ``STORAGE_DEVICE_DESCRIPTOR`` and reads only the fixed header portion.

    Args:
        handle: An open Win32 handle to the storage volume.

    Returns:
        The integer ``BusType`` field, or ``None`` if the IOCTL fails.
    """
    query = _STORAGE_PROPERTY_QUERY()
    query.PropertyId = _StorageDeviceProperty
    query.QueryType = _PropertyStandardQuery

    buf_size = 1024
    buf = ctypes.create_string_buffer(buf_size)
    bytes_ret = ctypes.wintypes.DWORD(0)

    ok = _kernel32().DeviceIoControl(
        handle,
        _IOCTL_STORAGE_QUERY_PROPERTY,
        ctypes.byref(query),
        ctypes.sizeof(query),
        buf,
        buf_size,
        ctypes.byref(bytes_ret),
        None,
    )
    if not ok or bytes_ret.value < ctypes.sizeof(_STORAGE_DEVICE_DESCRIPTOR_HEADER):
        return None

    header = _STORAGE_DEVICE_DESCRIPTOR_HEADER.from_buffer_copy(
        buf.raw[: ctypes.sizeof(_STORAGE_DEVICE_DESCRIPTOR_HEADER)]
    )
    return header.BusType


# ════════════════════════════════════════════════════════════════
# macOS — subprocess diskutil
# ════════════════════════════════════════════════════════════════
# There is no public ctypes-accessible API for storage properties on macOS
# without linking against IOKit (which requires PyObjC or cffi).
# ``diskutil info`` is the only portable option available to pure Python.


def _detect_macos(path: Path) -> StorageType:
    try:
        out = subprocess.check_output(
            ["diskutil", "info", str(path)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return StorageType.UNKNOWN

    if re.search(r"Solid State:\s+Yes", out, re.IGNORECASE):
        if re.search(r"(Protocol:\s+PCI-Express|NVMe)", out, re.IGNORECASE):
            return StorageType.NVME
        return StorageType.SSD

    if re.search(r"Solid State:\s+No", out, re.IGNORECASE):
        return StorageType.HDD

    return StorageType.UNKNOWN
