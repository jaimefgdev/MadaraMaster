"""Free-space wipe engine: fill with zeros until ENOSPC, then remove the fill file."""

import asyncio
import errno
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import aiofiles

from .i18n import T
from .trim import send_trim

# ─── Wipe-free-space chunk sizes ─────────────────────────────────────────────
_FILL_CHUNK_LARGE = 64 * 1024 * 1024
_FILL_CHUNK_SMALL = 4 * 1024
_ZEROS_LARGE = b"\x00" * _FILL_CHUNK_LARGE
_ZEROS_SMALL = b"\x00" * _FILL_CHUNK_SMALL


# ─── wipe-free-space ─────────────────────────────────────────────────────────


async def _async_wipe_free_space(
    target_dir: Path,
    update_fn: Optional[object] = None,
    trim: bool = True,
) -> dict[str, object]:
    """Fill all free space on the filesystem with zeros to defeat wear-leveling.

    Writes zeros to a temporary file in *target_dir* until the filesystem
    reports ``ENOSPC``, then fsyncs, removes the file, and dispatches a
    TRIM command for SSD/NVMe devices.

    Phase 1 uses 64 MB chunks for throughput; Phase 2 uses 4 KB chunks to
    cover the final partial cluster.

    Args:
        target_dir: Directory on the target filesystem.
        update_fn: Optional callable ``(bytes_written, chunk_index)`` that
            the live dashboard wires to a progress display.
        trim: Send TRIM after removing the fill file.

    The fill file is removed in a ``finally`` block, so it is deleted on
    errors, ``Ctrl+C`` and task cancellation too.  ``success`` is ``True``
    only if the fill completed **and** the fill file was removed.

    Returns:
        Result dict with keys ``success``, ``bytes_written``, ``duration``,
        ``trim_sent``, and ``error``.
    """
    result: dict[str, object] = {
        "success": False,
        "bytes_written": 0,
        "duration": 0.0,
        "trim_sent": False,
        "error": None,
    }

    tmp_name = f".mdrmfill_{uuid.uuid4().hex}.tmp"
    tmp_path = target_dir / tmp_name
    start = time.time()
    total_bw = 0
    chunk_idx = 0
    removed = False

    try:
        # Unbuffered: ENOSPC surfaces on write() itself instead of being
        # deferred to flush()/close(), and short writes are counted exactly.
        async with aiofiles.open(tmp_path, "wb", buffering=0) as f:
            # Phase 1 — 64 MB blocks until ENOSPC; Phase 2 — 4 KB blocks to
            # cover the final partial cluster.
            for block in (_ZEROS_LARGE, _ZEROS_SMALL):
                while True:
                    try:
                        n = await f.write(block)
                    except OSError as exc:
                        if exc.errno != errno.ENOSPC:
                            raise
                        break
                    if not n:
                        break
                    total_bw += n
                    chunk_idx += 1
                    if update_fn:
                        update_fn(total_bw, chunk_idx)

            # Phase 3 — commit to physical media
            await asyncio.to_thread(os.fsync, f.fileno())

    except Exception as exc:
        result["error"] = str(exc)

    finally:
        # Runs on errors, Ctrl+C and task cancellation alike: never leave
        # the disk full.
        try:
            tmp_path.unlink(missing_ok=True)
            removed = True
        except OSError as exc:
            cleanup_error = f"{T('wfs_cleanup_failed')} {tmp_path} ({exc})"
            result["error"] = (
                f"{result['error']}; {cleanup_error}" if result["error"] else cleanup_error
            )

    result["bytes_written"] = total_bw
    if result["error"] is None and removed:
        if trim:
            result["trim_sent"] = await asyncio.to_thread(send_trim, target_dir)
        result["success"] = True
    result["duration"] = time.time() - start
    return result
