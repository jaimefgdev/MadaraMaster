"""Shared wipe flow: target expansion, the dashboard-driven batch, cleanup."""

import asyncio
import os
import time
from pathlib import Path
from typing import Optional

from rich.live import Live

from . import ui
from .audit import AuditLogger, NullAuditLogger
from .engine import AsyncWiper
from .i18n import T
from .models import WipeResult, WipeSummary, WipeTelemetry
from .safety import collect_files, find_danger
from .storage import SanitizationStandard
from .trim import send_trim
from .ui import SpeedTracker, _build_dashboard

# How long the dashboard stays on screen at 100 % before the summary replaces
# it; without a pause the last repaint is erased as soon as it is drawn.
FINAL_HOLD_SECONDS = 0.6

# ─── Async wipe orchestration ─────────────────────────────────────────────────

_FLASH_TYPES = ("ssd", "nvme")


def _expand_targets(
    targets: list[str], allow_dangerous: bool = False
) -> tuple[list[str], list[str], list[str]]:
    """Turn user targets into the flat list of entries to wipe.

    Shared by the ``wipe`` command and the interactive session so both
    apply the same rules: protected targets are refused, links are never
    followed (see :func:`madaramaster.safety.collect_files`) and every directory target
    is remembered so it can be removed once emptied.

    Args:
        targets: Paths as given by the user.
        allow_dangerous: Accept protected targets (``--allow-dangerous-target``).

    Returns:
        ``(files, directories, errors)``: entries to wipe (deduplicated,
        in order), directory targets to remove afterwards, and one message
        per rejected target.
    """
    files: dict[str, None] = {}
    dirs: list[str] = []
    errors: list[str] = []
    for raw in targets:
        target = os.path.abspath(raw)
        if not os.path.lexists(target):
            errors.append(f"{T('target_not_found')} {target}")
            continue
        danger = find_danger(target)
        if danger and not allow_dangerous:
            errors.append(f"{T('dangerous_target')} {danger}")
            continue
        for f in collect_files(target):
            files.setdefault(f, None)
        if os.path.isdir(target) and not os.path.islink(target):
            dirs.append(target)
    return list(files), dirs, errors


def _remove_empty_dirs(dirs: list[str]) -> None:
    """Remove each directory tree bottom-up, skipping anything not empty."""
    for target in dirs:
        for root, subdirs, _ in os.walk(target, topdown=False):
            for d in subdirs:
                try:
                    os.rmdir(os.path.join(root, d))
                except OSError:
                    pass
        try:
            os.rmdir(target)
        except OSError:
            pass


async def async_wipe_logic(
    files: list[str],
    standard: SanitizationStandard = SanitizationStandard.NIST_CLEAR,
    verify: bool = False,
    log_path: Optional[str] = None,
    allow_hardlinks: bool = False,
    hash_before: bool = False,
    no_log: bool = False,
    trim: bool = False,
) -> WipeSummary:
    """Drive the async wipe engine for a list of files with a live dashboard.

    Args:
        files: Absolute paths of files to wipe.
        standard: Sanitization standard to apply.
        verify: When ``True``, re-read and compare each file after wiping
            (always on for ``purge``).
        log_path: Optional path to a custom audit-log file.
        allow_hardlinks: Also wipe files that have several hard links.
        hash_before: Record each file's SHA-256 in the audit log.
        no_log: Do not write an audit log at all.
        trim: After the batch, send one TRIM per filesystem that held a
            successfully wiped file on SSD/NVMe.

    Returns:
        A :class:`~madaramaster.models.WipeSummary` aggregating the results.
    """
    if no_log:
        audit_logger: AuditLogger = NullAuditLogger()
    elif log_path:
        audit_logger = AuditLogger(log_path=Path(log_path))
    else:
        audit_logger = AuditLogger()

    wiper = AsyncWiper(audit_logger=audit_logger, hash_before=hash_before)
    summary = WipeSummary()
    summary.total_files = len(files)
    start_time = time.time()
    trim_targets: dict[int, Path] = {}

    # Plan the whole batch first (storage detection is cached per device), so
    # the dashboard knows the total from its first frame.
    plans: list[tuple[int, list[str]]] = []
    for filepath in files:
        try:
            file_size = Path(filepath).lstat().st_size
        except OSError:
            file_size = 0
        try:
            patterns = wiper.plan(Path(filepath), standard)
        except Exception:
            patterns = []
        plans.append((file_size, patterns))

    telemetry = WipeTelemetry(
        batch_files=len(files),
        batch_total_bytes=sum(size * max(1, len(p)) for size, p in plans),
    )
    speed_tracker = SpeedTracker(window_seconds=2.0)

    with Live(
        _build_dashboard(telemetry, speed_tracker, 0, len(files)),
        console=ui.console,
        refresh_per_second=12,
        transient=True,
    ) as live:
        for file_idx, (filepath, (file_size, patterns)) in enumerate(
            zip(files, plans, strict=True), start=1
        ):
            file_path_obj = Path(filepath)

            telemetry.start_time = time.time()
            telemetry.current_pass = 0
            telemetry.total_passes = max(1, len(patterns))
            telemetry.pass_patterns = patterns
            telemetry.algorithm = T(
                "dash_algorithm_value", standard=standard.value, n=len(patterns)
            )
            telemetry.file_size = file_size
            telemetry.current_file = filepath
            telemetry.bytes_written_total = 0
            telemetry.bytes_written_current_pass = 0
            telemetry.finished = False
            speed_tracker = SpeedTracker(window_seconds=2.0)

            async def progress_callback(
                _path: Path,
                pass_num: int,
                bytes_in_pass: int,
                total: int,
                speed_tracker: SpeedTracker = speed_tracker,
                file_idx: int = file_idx,
                file_size: int = file_size,
            ) -> None:
                telemetry.current_pass = pass_num
                telemetry.bytes_written_current_pass = bytes_in_pass
                speed_tracker.record((pass_num - 1) * total + bytes_in_pass)
                # A pass covers the file rounded up to whole clusters (*total*),
                # so progress is measured as a fraction of each pass.
                fraction = bytes_in_pass / total if total > 0 else 1.0
                telemetry.bytes_written_total = int(file_size * (pass_num - 1 + fraction))
                live.update(_build_dashboard(telemetry, speed_tracker, file_idx, len(files)))

            result_dict = await wiper.wipe_file(
                file_path_obj,
                standard=standard,
                verify=verify,
                progress_callback=progress_callback,
                allow_hardlinks=allow_hardlinks,
            )

            w_res = WipeResult(
                filepath=filepath,
                success=result_dict.get("success", False),
                error=result_dict.get("error") or "",
                bytes_written=file_size * result_dict.get("passes_completed", 0),
            )
            summary.results.append(w_res)

            # The file is done (wiped or failed): move it into the batch totals.
            telemetry.batch_files_done += 1
            telemetry.batch_done_bytes += file_size * telemetry.total_passes
            telemetry.batch_written_bytes += w_res.bytes_written
            telemetry.bytes_written_total = 0

            if w_res.success:
                summary.files_wiped += 1
                summary.total_bytes_overwritten += w_res.bytes_written
                telemetry.finished = True
                live.update(_build_dashboard(telemetry, speed_tracker, file_idx, len(files)))
                if trim and result_dict.get("storage_type") in _FLASH_TYPES:
                    parent = file_path_obj.parent
                    try:
                        trim_targets.setdefault(os.stat(parent).st_dev, parent)
                    except OSError:
                        pass
            else:
                summary.files_failed += 1
                summary.errors.append(f"{filepath}: {w_res.error}")

        held = 0.0
        if files:
            telemetry.batch_complete = True
            live.update(
                _build_dashboard(telemetry, speed_tracker, len(files), len(files)), refresh=True
            )
            hold_start = time.time()
            await asyncio.sleep(FINAL_HOLD_SECONDS)
            held = time.time() - hold_start

    # One TRIM per filesystem for the whole batch, not one per file.
    for directory in trim_targets.values():
        if await asyncio.to_thread(send_trim, directory):
            summary.trims_sent += 1

    # The pause on the final frame is not part of the wipe.
    summary.total_duration = time.time() - start_time - held
    return summary
