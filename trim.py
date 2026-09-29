#!/usr/bin/env python3
# Módulo TRIM — hook post-borrado para forzar el GC del controlador SSD/NVMe
# jaimefg1888
#
# Linux  → ioctl FITRIM sobre el directorio padre (sin subprocess).
#           Requiere CAP_SYS_ADMIN; falla silenciosamente si no hay permisos.
#
# Windows → no-op.  Enviar DSM Trim en bruto sobre el handle del volumen es
#           peligroso (un rango mal construido descartaría datos vivos).
#           Windows ya reenvía TRIM al borrar y con la optimización
#           programada de unidades (Optimize-Volume -ReTrim).
#
# macOS   → no-op.  El sistema de archivos APFS gestiona el TRIM de forma
#           transparente; no hay API pública sin IOKit/PyObjC.

from __future__ import annotations

import logging
import os
import platform
import struct
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def send_trim(path: Path) -> bool:
    """Send a TRIM/Discard command to the storage controller for *path*.

    Only Linux (``FITRIM``) is implemented; on Windows and macOS this is a
    deliberate no-op that returns ``False``.  Never raises:
    any error is logged at DEBUG level and ``False`` is returned so callers
    can treat TRIM as a best-effort optimisation rather than a hard
    requirement.

    Args:
        path: A path on the filesystem whose free space should be trimmed.
            Typically the parent directory of the file that was just deleted.

    Returns:
        ``True`` if the TRIM command was issued successfully, ``False``
        otherwise.
    """
    system = platform.system().lower()
    try:
        if system == "linux":
            return _trim_linux(path)
        # Windows and macOS: intentionally a no-op (see module header).
    except Exception as exc:
        log.debug("TRIM: excepción ignorada en %s: %s", system, exc)
    return False


# ════════════════════════════════════════════════════════════════
# LINUX — ioctl FITRIM
# ════════════════════════════════════════════════════════════════
#
# FITRIM = _IOWR('X', 121, struct fstrim_range)
#
# struct fstrim_range { __u64 start; __u64 len; __u64 minlen; }  → 24 bytes
#
# The macro expands to:
#   ((_IOC_READ | _IOC_WRITE) << 30) | ('X' << 8) | 121 | (24 << 16)
#   = (3 << 30) | (0x58 << 8) | 0x79 | (24 << 16)
#   = 0xC0185879
#
# We open the *parent directory* with O_RDONLY | O_DIRECTORY because
# FITRIM operates on a mounted filesystem, not on an individual file.
# Submitting the ioctl against the directory fd instructs the kernel to
# issue DISCARD commands for all free extents on that volume.
# ════════════════════════════════════════════════════════════════

_FITRIM: int = (
    (3 << 30)  # _IOC_READ | _IOC_WRITE
    | (0x58 << 8)  # ord('X')
    | 121  # nr
    | (struct.calcsize("QQQ") << 16)  # sizeof(struct fstrim_range) = 24
)
# struct fstrim_range: start=0, len=UINT64_MAX, minlen=0 (trim everything)
_FSTRIM_RANGE: bytes = struct.pack("QQQ", 0, (1 << 64) - 1, 0)


def _trim_linux(path: Path) -> bool:
    """Issue a ``FITRIM`` ioctl on the filesystem that contains *path*.

    Opens the parent directory with ``O_RDONLY | O_DIRECTORY`` and calls
    ``fcntl.ioctl(FITRIM, ...)`` to ask the kernel to emit ``DISCARD``
    (trim) commands for all free blocks on the underlying block device.

    ``CAP_SYS_ADMIN`` is required.  On consumer systems without that
    capability, the call returns ``EPERM``; the function logs a debug
    message and returns ``False`` rather than raising.

    As an alternative to running as root, the filesystem can be mounted
    with the ``discard`` option (continuous TRIM) or the system-wide
    ``fstrim.timer`` systemd unit can be used.

    Args:
        path: Any path on the target filesystem.

    Returns:
        ``True`` on success, ``False`` on any error.
    """
    if sys.platform == "win32":
        return False

    try:
        import fcntl
    except ImportError:
        return False

    parent = path.parent if path.is_file() else path
    if not parent.exists():
        parent = path.parent

    try:
        fd = os.open(str(parent), os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        log.debug("TRIM Linux: no se pudo abrir %s: %s", parent, exc)
        return False

    try:
        buf = bytearray(_FSTRIM_RANGE)
        fcntl.ioctl(fd, _FITRIM, buf)
        trimmed = struct.unpack("QQQ", buf)[1]
        log.debug("TRIM Linux: %.1f MB liberados en %s", trimmed / 1024 / 1024, parent)
        return True
    except PermissionError:
        log.debug(
            "TRIM Linux: FITRIM denegado en %s — se requiere CAP_SYS_ADMIN.  "
            "Considera montar con 'discard' o ejecutar como root.",
            parent,
        )
        return False
    except OSError as exc:
        log.debug("TRIM Linux: FITRIM falló en %s: %s", parent, exc)
        return False
    finally:
        os.close(fd)
