"""Console output: banner, prompts, summary, live dashboard and warnings."""

import collections
import os
import time
from pathlib import Path
from typing import Optional

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from . import __version__, residue
from .i18n import CONFIRM_YES, T
from .models import WipeSummary, WipeTelemetry
from .utils import format_bytes

console = Console()

# ─── ASCII banner ─────────────────────────────────────────────────────────────
BANNER = """
 ███╗   ███╗ █████╗ ██████╗  █████╗ ██████╗  █████╗
 ████╗ ████║██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔══██╗
 ██╔████╔██║███████║██║  ██║███████║██████╔╝███████║
 ██║╚██╔╝██║██╔══██║██║  ██║██╔══██║██╔══██╗██╔══██║
 ██║ ╚═╝ ██║██║  ██║██████╔╝██║  ██║██║  ██║██║  ██║
 ╚═╝     ╚═╝╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝
       ███╗   ███╗ █████╗ ███████╗████████╗███████╗██████╗
       ████╗ ████║██╔══██╗██╔════╝╚══██╔══╝██╔════╝██╔══██╗
       ██╔████╔██║███████║███████╗   ██║   █████╗  ██████╔╝
       ██║╚██╔╝██║██╔══██║╚════██║   ██║   ██╔══╝  ██╔══██╗
       ██║ ╚═╝ ██║██║  ██║███████║   ██║   ███████╗██║  ██║
       ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═╝

   MadaraMaster v{version} • Created by jaimefg1888
"""


def _lsize(path: str) -> int:
    """Size of *path* without following symlinks (0 if it vanished)."""
    try:
        return os.lstat(path).st_size
    except OSError:
        return 0


# ─── UI helpers ──────────────────────────────────────────────────────────────


def confirm_action() -> bool:
    """Prompt the user for a yes/no confirmation and return the result."""
    answer = input(T("confirm_msg")).lower().strip()
    return answer in CONFIRM_YES


def print_banner() -> None:
    """Render the ASCII art banner panel to the console."""
    console.print(
        Panel(
            Align.center(Text(BANNER.replace("{version}", __version__), style="bold red")),
            border_style="bright_cyan",
            box=box.DOUBLE_EDGE,
            subtitle=f"[dim]{T('banner_subtitle', version=__version__)}[/]",
        )
    )


def select_language() -> str:
    """Interactively prompt the user to select a display language.

    Returns:
        ``"EN"`` or ``"ES"``.
    """
    while True:
        choice = input("Select Language / Seleccione Idioma [1: EN | 2: ES]: ").strip()
        if choice in ("", "1"):
            return "EN"
        if choice == "2":
            return "ES"


def print_summary(summary: WipeSummary) -> None:
    """Render the post-wipe statistics table and result panel to the console."""
    table = Table(
        title=f"[bold bright_cyan]{T('summary_title')}[/]",
        box=box.DOUBLE_EDGE,
        border_style="bright_cyan",
        padding=(0, 2),
        show_lines=True,
    )
    table.add_column(T("metric"), style="bold white", min_width=25)
    table.add_column(T("value"), style="bold", min_width=20, justify="right")

    ok_style = "bright_green" if summary.files_wiped > 0 else "dim"
    fail_style = "bright_red" if summary.files_failed > 0 else "bright_green"

    table.add_row(T("total_targeted"), f"[cyan]{summary.total_files}[/]")
    table.add_row(T("files_wiped_ok"), f"[{ok_style}]{summary.files_wiped}[/]")
    table.add_row(T("files_failed"), f"[{fail_style}]{summary.files_failed}[/]")
    table.add_row("─" * 25, "─" * 20)

    total = summary.total_bytes_overwritten
    table.add_row(
        T("total_overwritten"),
        f"[bright_yellow]{total:,}[/] [dim]({format_bytes(total)})[/]",
    )
    table.add_row(T("effective_written"), f"[bright_yellow]{format_bytes(total)}[/]")
    table.add_row("─" * 25, "─" * 20)
    table.add_row(T("total_duration"), f"[bright_magenta]{summary.total_duration:.3f}s[/]")

    if total > 0 and summary.total_duration > 0:
        speed = total / summary.total_duration
        table.add_row(T("avg_speed"), f"[dim]{format_bytes(speed)}/s[/]")
    if summary.trims_sent:
        table.add_row(T("trims_sent"), f"[dim]{summary.trims_sent}[/]")

    console.print()
    console.print(table)

    if summary.errors:
        content = "\n".join(f"[red]✗[/] {err}" for err in summary.errors[:20])
        if len(summary.errors) > 20:
            content += f"\n[dim]{T('more_errors', n=len(summary.errors) - 20)}[/]"
        console.print()
        console.print(
            Panel(
                content,
                title=f"[bold red]{T('errors_title')}[/]",
                border_style="red",
                box=box.ROUNDED,
            )
        )

    console.print()
    if summary.files_failed == 0 and summary.files_wiped > 0:
        key = "all_sanitized_one" if summary.files_wiped == 1 else "all_sanitized_many"
        console.print(
            Panel(
                Align.center(Text(T(key, n=summary.files_wiped), style="bold bright_green")),
                border_style="bright_green",
                box=box.DOUBLE_EDGE,
                padding=(1, 4),
            )
        )
    elif summary.files_wiped > 0:
        console.print(
            Panel(
                Align.center(
                    Text(
                        T("partial_wipe", wiped=summary.files_wiped, failed=summary.files_failed),
                        style="bold bright_yellow",
                    )
                ),
                border_style="yellow",
                box=box.DOUBLE_EDGE,
                padding=(1, 4),
            )
        )
    else:
        console.print(
            Panel(
                Align.center(Text(T("no_files_wiped"), style="bold bright_red")),
                border_style="red",
                box=box.DOUBLE_EDGE,
                padding=(1, 4),
            )
        )


# ─── Speed tracker ───────────────────────────────────────────────────────────


class SpeedTracker:
    """Rolling-window write-speed estimator.

    Maintains a deque of ``(timestamp, bytes_written)`` samples and returns
    the average throughput over the last *window_seconds* seconds.

    Args:
        window_seconds: Width of the sliding measurement window.
    """

    def __init__(self, window_seconds: float = 2.0) -> None:
        self._window = window_seconds
        self._samples: collections.deque[tuple[float, int]] = collections.deque()

    def record(self, bytes_written: int, timestamp: Optional[float] = None) -> None:
        """Append a measurement sample and evict stale entries.

        Args:
            bytes_written: Cumulative bytes written so far in the current pass.
            timestamp: Sample timestamp; defaults to ``time.time()``.
        """
        ts = timestamp or time.time()
        self._samples.append((ts, bytes_written))
        cutoff = ts - self._window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def get_speed(self) -> float:
        """Return the estimated write speed in bytes per second.

        Returns:
            Bytes per second, or ``0.0`` if fewer than two samples are
            available.
        """
        if len(self._samples) < 2:
            return 0.0
        oldest_ts, oldest_bytes = self._samples[0]
        newest_ts, newest_bytes = self._samples[-1]
        dt = newest_ts - oldest_ts
        return (newest_bytes - oldest_bytes) / dt if dt > 0 else 0.0


# ─── Live dashboard ──────────────────────────────────────────────────────────


def _build_dashboard(
    telemetry: WipeTelemetry,
    speed_tracker: SpeedTracker,
    file_index: int,
    total_files: int,
) -> Panel:
    """Construct the Rich live-dashboard renderable.

    Called on every refresh tick; must not raise exceptions because any
    error inside a ``Live`` context will tear down the entire render loop.

    Args:
        telemetry: Current wipe progress snapshot.
        speed_tracker: Rolling speed estimator.
        file_index: 1-based index of the file currently being wiped.
        total_files: Total number of files in the batch.

    Returns:
        A Rich :class:`~rich.panel.Panel` ready for display.
    """
    header = Text(T("dash_header", version=__version__), style="bold bright_cyan")

    basename = os.path.basename(telemetry.current_file) if telemetry.current_file else "—"
    display_name = basename[:45] + "…" if len(basename) > 45 else basename

    if telemetry.batch_complete:
        status_text = T("dash_done")
    elif telemetry.finished:
        status_text = T("dash_scrubbing")
    elif telemetry.current_pass > 0:
        idx = telemetry.current_pass
        patterns = telemetry.pass_patterns
        pattern = T(f"pat_{patterns[idx - 1]}") if 0 < idx <= len(patterns) else "…"
        status_text = T("dash_pass", i=idx, n=telemetry.total_passes, pattern=pattern)
    else:
        status_text = T("starting")

    info_table = Table(box=None, show_header=False, padding=(0, 2), expand=True)
    info_table.add_column("Key", style="bold white", ratio=1)
    info_table.add_column("Value", style="bright_white", ratio=3)
    info_table.add_row(T("dash_file"), f"[bright_yellow]{display_name}[/]")
    info_table.add_row(T("dash_algorithm"), f"[dim]{telemetry.algorithm or '—'}[/]")
    info_table.add_row(T("dash_status"), f"[bright_cyan]{status_text}[/]")
    if total_files > 1:
        info_table.add_row(
            T("dash_file_counter"), f"[bright_magenta]{file_index}/{total_files}[/]"
        )

    progress_pct = telemetry.global_progress * 100
    speed = speed_tracker.get_speed()

    bar = ProgressBar(
        total=100,
        completed=progress_pct,
        width=40,
        complete_style="bright_green" if progress_pct < 100 else "green",
        finished_style="bold green",
    )

    metrics_table = Table(box=None, show_header=False, padding=(0, 2), expand=True)
    metrics_table.add_column("Icon", style="bold", width=22)
    metrics_table.add_column("Data", ratio=3)
    metrics_table.add_row(
        T("dash_progress"),
        Group(bar, Text(f" {progress_pct:.1f}%", style="bold bright_green")),
    )
    metrics_table.add_row(
        T("dash_speed"),
        Text(
            f"{format_bytes(int(speed))}/s" if speed > 0 else "—",
            style="bold bright_yellow",
        ),
    )
    metrics_table.add_row(
        T("dash_written"),
        Text(
            f"{format_bytes(telemetry.written_bytes)} / {format_bytes(telemetry.target_bytes)}",
            style="bold bright_magenta",
        ),
    )

    inner = Group(
        Align.center(header),
        Text(""),
        Panel(info_table, border_style="dim cyan", box=box.ROUNDED, padding=(0, 1)),
        Text(""),
        Panel(metrics_table, border_style="dim cyan", box=box.ROUNDED, padding=(0, 1)),
    )
    return Panel(inner, border_style="bright_cyan", box=box.HEAVY, padding=(1, 2))


def _print_residue_warning(targets: list[str]) -> None:
    """Warn when copies of the targets may survive a file-level wipe.

    Args:
        targets: Paths (files or directories) about to be wiped.
    """
    found: list[residue.Residue] = []
    for target in targets:
        for risk in residue.detect_residue_risks(Path(target)):
            if risk not in found:
                found.append(risk)
    if not found:
        return
    lines = [f"[bold yellow]{T('residue_title')}[/]", ""]
    # Let Rich wrap each reason to the terminal width.
    lines += [f"• {T('residue_' + risk.value).replace(chr(10), ' ')}" for risk in found]
    lines += ["", f"[dim]{T('residue_hint')}[/]"]
    console.print()
    console.print(Panel("\n".join(lines), border_style="yellow", box=box.ROUNDED, padding=(1, 2)))
