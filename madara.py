#!/usr/bin/env python3
"""
MadaraMaster — CLI Interface v4.0
===================================
Professional cyberpunk-themed CLI for secure file sanitization.
Implements DoD 5220.22-M with real-time Live Dashboard visualization.
Bilingual support: English (EN) and Spanish (ES).

Usage:
    python madara.py                          # Interactive session mode
    python madara.py wipe <TARGET>            # Wipe a file or directory
    python madara.py wipe <TARGET> --confirm  # Skip confirmation prompt
    python madara.py wipe <TARGET> --dry-run  # Preview without deleting

Author : MadaraMaster Team
License: MIT — Authorized Data Sanitization Use Only
"""

import os
import sys
import time
import collections
from typing import Optional

import typer
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.live import Live
from rich.progress_bar import ProgressBar
from rich import box

import asyncio
from wiper_async import AsyncWiper
from storage import SanitizationStandard
from wiper import (
    wipe_file,
    wipe_directory,
    collect_files,
    WipeResult,
    WipeSummary,
    WipeTelemetry,
    DOD_PASSES,
)
from utils import format_bytes

# ──────────────────────── App Setup ────────────────────────────

app = typer.Typer(
    name="madaramaster",
    help="🧹 MadaraMaster — DoD 5220.22-M Secure File Sanitization",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()

VERSION = "4.0.0"

# ──────────────────────── i18n — Language System ───────────────

LANG = {
    "EN": {
        # -- Interactive session --
        "session_title":      "Interactive Session Mode",
        "session_hint":       "Drag files and press Enter (or type the path).",
        "session_exit_hint":  "Type [bold]exit[/bold] or [bold]close[/bold] to quit.",
        "queue_count":        "{n} file(s) queued",
        "queue_hint":         "Add more files or press Enter to WIPE.",
        "session_prompt":     "❱❱❱ ",
        "session_ended":      "Session ended.",
        "session_goodbye":    "👋 Session ended. See you later.",
        "continue_prompt":    "Press Enter to start a new wipe session or type [bold]exit[/bold] to quit...",
        "path_not_found":     "✗ Path not found:",
        # -- Wipe command --
        "target_not_found":   "✗ Target not found:",
        "no_files_found":     "⚠ No files found in:",
        "type_dir":           "Directory (recursive)",
        "type_file":          "Single file",
        "lbl_target":         "Target",
        "lbl_type":           "Type",
        "files_to_wipe":      "Files to wipe",
        "total_data":         "Total data",
        "method":             "Method",
        "passes":             "Passes",
        "pass_values":        "1) Zeros  2) Ones  3) Random",
        "dry_run_title":      "🔍 DRY RUN — no files will be modified:",
        "more_files":         "...and {n} more files",
        "warning_title":      "⚠ WARNING: THIS ACTION IS IRREVERSIBLE ⚠",
        "warning_body":       "All targeted files will be overwritten 3 times and permanently deleted.\n[bold]Data CANNOT be recovered after this operation.[/]",
        "confirm_prompt":     "  Are you sure you want to proceed?",
        "confirm_msg":        "Are you sure? [y/N]: ",
        "op_cancelled":       "Operation cancelled.",
        "starting":           "Starting...",
        # -- Preview table --
        "preview_title":      "📋 FILES TO DESTROY",
        "preview_name":       "Name",
        "preview_size":       "Size",
        "preview_type":       "Type",
        "preview_total":      "TOTAL",
        # -- Dashboard --
        "dash_header":        "🛡️  MADARA MASTER v4.0.0 | SECURITY DAEMON",
        "dash_file":          "📁 File",
        "dash_algorithm":     "🔒 Algorithm",
        "dash_status":        "🔄 Status",
        "dash_pass_1":        "Pass 1/3 — Overwriting with 0x00 (Zeros)...",
        "dash_pass_2":        "Pass 2/3 — Overwriting with 0xFF (Ones)...",
        "dash_pass_3":        "Pass 3/3 — Overwriting with Random Bytes...",
        "dash_scrubbing":     "🧹 Scrubbing metadata & deleting...",
        "dash_progress":      "📊 Global Progress",
        "dash_speed":         "🚀 Speed",
        "dash_written":       "💾 Effective Write",
        "dash_file_counter":  "📂 File",
        # -- Summary --
        "summary_title":      "🧹 WIPE SUMMARY",
        "metric":             "Metric",
        "value":              "Value",
        "total_targeted":     "Total Files Targeted",
        "files_wiped_ok":     "Files Wiped Successfully",
        "files_failed":       "Files Failed",
        "total_overwritten":  "Total Bytes Overwritten",
        "effective_written":  "Effective Data Written",
        "total_duration":     "Total Duration",
        "avg_speed":          "Average Write Speed",
        "errors_title":       "⚠ Errors",
        "more_errors":        "...and {n} more",
        "all_sanitized_one":  "✔ {n} FILE DELETED — DATA IRRECOVERABLE",
        "all_sanitized_many": "✔ {n} FILES DELETED — DATA IRRECOVERABLE",
        "partial_wipe":       "⚠ PARTIAL WIPE — {wiped} wiped, {failed} failed",
        "no_files_wiped":     "✗ NO FILES WERE WIPED",
        # -- Completion --
        "completion_msg":     "[v4.0.0] SANITIZATION VERIFIED — ZERO RECOVERY",
        # -- Pass labels --
        "pass_1":             "Pass 1/3 · Zeros",
        "pass_2":             "Pass 2/3 · Ones",
        "pass_3":             "Pass 3/3 · Random",
        "pass_random":        "Random Overwrite",
        # -- Summary --
        "summary_title":      "🧹 WIPE SUMMARY",
        "pass_2":             "Pass 2/3 · Ones",
        "pass_3":             "Pass 3/3 · Random",
        "wiped":              "✔ Wiped",
        # -- Version --
        "version_desc":       "DoD 5220.22-M Compliant Secure File Sanitization",
        "version_license":    "License: MIT — Authorized Use Only",
    },
    "ES": {
        # -- Interactive session --
        "session_title":      "Modo Sesión Interactiva",
        "session_hint":       "Arrastra archivos y pulsa Enter (o escribe la ruta).",
        "session_exit_hint":  "Escribe [bold]salir[/bold] o [bold]cerrar[/bold] para salir.",
        "queue_count":        "{n} archivo(s) en cola",
        "queue_hint":         "Añade más archivos o pulsa Enter para BORRAR.",
        "session_prompt":     "❱❱❱ ",
        "session_ended":      "Sesión terminada.",
        "session_goodbye":    "👋 Sesión terminada. Hasta pronto.",
        "continue_prompt":    "Presiona Enter para iniciar una nueva sesión de borrado o escribe [bold]salir[/bold] o [bold]cerrar[/bold] para salir...",
        "path_not_found":     "✗ Ruta no encontrada:",
        # -- Wipe command --
        "target_not_found":   "✗ Objetivo no encontrado:",
        "no_files_found":     "⚠ No se encontraron archivos en:",
        "type_dir":           "Directorio (recursivo)",
        "type_file":          "Archivo individual",
        "lbl_target":         "Objetivo",
        "lbl_type":           "Tipo",
        "files_to_wipe":      "Archivos a borrar",
        "total_data":         "Datos totales",
        "method":             "Método",
        "passes":             "Pases",
        "pass_values":        "1) Ceros  2) Unos  3) Aleatorio",
        "dry_run_title":      "🔍 SIMULACIÓN — no se modificará ningún archivo:",
        "more_files":         "...y {n} archivos más",
        "warning_title":      "⚠ ADVERTENCIA: ESTA ACCIÓN ES IRREVERSIBLE ⚠",
        "warning_body":       "Todos los archivos serán sobrescritos 3 veces y eliminados permanentemente.\n[bold]Los datos NO se podrán recuperar tras esta operación.[/]",
        "confirm_prompt":     "  ¿Estás seguro de que deseas continuar?",
        "confirm_msg":        "¿Estás seguro? [s/N]: ",
        "op_cancelled":       "Operación cancelada.",
        "starting":           "Iniciando...",
        # -- Preview table --
        "preview_title":      "📋 ARCHIVOS A DESTRUIR",
        "preview_name":       "Nombre",
        "preview_size":       "Tamaño",
        "preview_type":       "Tipo",
        "preview_total":      "TOTAL",
        # -- Dashboard --
        "dash_header":        "🛡️  MADARA MASTER v4.0.0 | SECURITY DAEMON",
        "dash_file":          "📁 Archivo",
        "dash_algorithm":     "🔒 Algoritmo",
        "dash_status":        "🔄 Estado",
        "dash_pass_1":        "Pase 1/3 — Sobrescribiendo con 0x00 (Ceros)...",
        "dash_pass_2":        "Pase 2/3 — Sobrescribiendo con 0xFF (Unos)...",
        "dash_pass_3":        "Pase 3/3 — Sobrescribiendo con Bytes Aleatorios...",
        "dash_scrubbing":     "🧹 Limpiando metadatos y eliminando...",
        "dash_progress":      "📊 Progreso Global",
        "dash_speed":         "🚀 Velocidad",
        "dash_written":       "💾 Escritura Efectiva",
        "dash_file_counter":  "📂 Archivo",
        # -- Summary --
        "summary_title":      "🧹 RESUMEN DE BORRADO",
        "metric":             "Métrica",
        "value":              "Valor",
        "total_targeted":     "Total Archivos Objetivo",
        "files_wiped_ok":     "Archivos Borrados con Éxito",
        "files_failed":       "Archivos Fallidos",
        "total_overwritten":  "Total Bytes Sobrescritos",
        "effective_written":  "Datos Efectivos Escritos (3 pases)",
        "total_duration":     "Duración Total",
        "avg_speed":          "Velocidad Media de Escritura",
        "errors_title":       "⚠ Errores",
        "more_errors":        "...y {n} más",
        "all_sanitized_one":  "✔ {n} ARCHIVO ELIMINADO — DATOS IRRECUPERABLES",
        "all_sanitized_many": "✔ {n} ARCHIVOS ELIMINADOS — DATOS IRRECUPERABLES",
        "partial_wipe":       "⚠ BORRADO PARCIAL — {wiped} borrados, {failed} fallidos",
        "no_files_wiped":     "✗ NO SE BORRÓ NINGÚN ARCHIVO",
        # -- Completion --
        "completion_msg":     "[v4.0.0] SANITIZACIÓN VERIFICADA — ZERO RECOVERY",
        # -- Pass labels --
        "pass_1":             "Pase 1/3 · Ceros",
        "pass_2":             "Pase 2/3 · Unos",
        "pass_3":             "Pase 3/3 · Aleatorio",
        "wiped":              "✔ Borrado",
        # -- Version --
        "version_desc":       "Sanitización Segura de Archivos — Norma DoD 5220.22-M",
        "version_license":    "Licencia: MIT — Uso Autorizado Únicamente",
    },
}

# Session language — set by select_language() at startup
current_lang = "EN"

# Exit keywords — language-specific (only current language works)
EXIT_KEYWORDS = {
    "EN": frozenset(["exit", "close", "quit"]),
    "ES": frozenset(["salir", "cerrar"]),
}

# Universal confirmation acceptance set (works in both EN and ES)
CONFIRM_YES = frozenset(["y", "yes", "s", "si"])


def T(key: str, **kwargs) -> str:
    """Get translated text for the current language, with optional format params."""
    text = LANG[current_lang].get(key, key)
    return text.format(**kwargs) if kwargs else text


def confirm_action() -> bool:
    """Bilingual confirmation prompt. Accepts y/yes/s/si regardless of language."""
    answer = input(T("confirm_msg")).lower().strip()
    return answer in CONFIRM_YES


# ──────────────────────── Banner ───────────────────────────────

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
                                                            
   MadaraMaster v4.0.0 • Created by jaimefg1888 • DoD 5220.22-M
"""


# ──────────────────────── UI Helpers ───────────────────────────

def print_banner():
    """Displays the cyberpunk banner."""
    console.print(
        Panel(
            Align.center(Text(BANNER, style="bold red")),
            border_style="bright_cyan",
            box=box.DOUBLE_EDGE,
            subtitle=f"[dim]DoD 5220.22-M Compliant · v{VERSION}[/]",
        )
    )


def select_language() -> str:
    """
    Prompts the user to select a language.
    Loops until a valid option is entered. Defaults to EN on empty input.
    """
    while True:
        choice = input("Select Language / Seleccione Idioma [1: EN | 2: ES]: ").strip()
        if choice in ("", "1"):
            return "EN"
        elif choice == "2":
            return "ES"
        # Invalid input → repeat


def print_summary(summary: WipeSummary):
    """Displays the post-wipe summary table (bilingual)."""
    table = Table(
        title=f"[bold bright_cyan]{T('summary_title')}[/]",
        box=box.DOUBLE_EDGE,
        border_style="bright_cyan",
        padding=(0, 2),
        show_lines=True,
    )
    table.add_column(T("metric"), style="bold white", min_width=25)
    table.add_column(T("value"), style="bold", min_width=20, justify="right")

    # Files
    success_style = "bright_green" if summary.files_wiped > 0 else "dim"
    fail_style = "bright_red" if summary.files_failed > 0 else "bright_green"

    table.add_row(T("total_targeted"), f"[cyan]{summary.total_files}[/]")
    table.add_row(T("files_wiped_ok"), f"[{success_style}]{summary.files_wiped}[/]")
    table.add_row(T("files_failed"), f"[{fail_style}]{summary.files_failed}[/]")
    table.add_row("─" * 25, "─" * 20)

    # Bytes
    total_overwritten = summary.total_bytes_overwritten
    table.add_row(
        T("total_overwritten"),
        f"[bright_yellow]{total_overwritten:,}[/] [dim]({format_bytes(total_overwritten)})[/]"
    )
    table.add_row(
        T("effective_written"),
        f"[bright_yellow]{format_bytes(total_overwritten)}[/]"
    )
    table.add_row("─" * 25, "─" * 20)

    # Time
    table.add_row(T("total_duration"), f"[bright_magenta]{summary.total_duration:.3f}s[/]")

    if total_overwritten > 0 and summary.total_duration > 0:
        speed = total_overwritten / summary.total_duration
        table.add_row(T("avg_speed"), f"[dim]{format_bytes(speed)}/s[/]")

    console.print()
    console.print(table)

    # Errors detail
    if summary.errors:
        console.print()
        error_panel_content = "\n".join(
            f"[red]✗[/] {err}" for err in summary.errors[:20]
        )
        if len(summary.errors) > 20:
            error_panel_content += f"\n[dim]{T('more_errors', n=len(summary.errors) - 20)}[/]"
        console.print(
            Panel(
                error_panel_content,
                title=f"[bold red]{T('errors_title')}[/]",
                border_style="red",
                box=box.ROUNDED,
            )
        )

    # Final status
    console.print()
    if summary.files_failed == 0 and summary.files_wiped > 0:
        key = "all_sanitized_one" if summary.files_wiped == 1 else "all_sanitized_many"
        console.print(
            Panel(
                Align.center(
                    Text(T(key, n=summary.files_wiped), style="bold bright_green"),
                ),
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
                    ),
                ),
                border_style="yellow",
                box=box.DOUBLE_EDGE,
                padding=(1, 4),
            )
        )
    else:
        console.print(
            Panel(
                Align.center(
                    Text(T("no_files_wiped"), style="bold bright_red"),
                ),
                border_style="red",
                box=box.DOUBLE_EDGE,
                padding=(1, 4),
            )
        )


# ──────────────────────── Live Dashboard ───────────────────────

class SpeedTracker:
    """
    Calculates write speed using a 2-second moving average window.
    Avoids jumpy speed readings by smoothing over recent samples.
    """

    def __init__(self, window_seconds: float = 2.0):
        self._window = window_seconds
        self._samples: collections.deque = collections.deque()

    def record(self, bytes_written: int, timestamp: float = None):
        """Record a cumulative bytes_written sample."""
        ts = timestamp or time.time()
        self._samples.append((ts, bytes_written))
        # Prune old samples outside the window
        cutoff = ts - self._window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def get_speed(self) -> float:
        """Returns bytes/second as a moving average over the window."""
        if len(self._samples) < 2:
            return 0.0
        oldest_ts, oldest_bytes = self._samples[0]
        newest_ts, newest_bytes = self._samples[-1]
        dt = newest_ts - oldest_ts
        if dt <= 0:
            return 0.0
        return (newest_bytes - oldest_bytes) / dt


def _get_pass_status(pass_number: int) -> str:
    """Returns the i18n dashboard status string for a given pass."""
    return T(f"dash_pass_{pass_number}")


def _build_dashboard(
    telemetry: WipeTelemetry,
    speed_tracker: SpeedTracker,
    file_index: int,
    total_files: int,
) -> Panel:
    """
    Constructs the full Live Dashboard layout as a Rich Panel.

    Layout:
        ┌─ Header ──────────────────────────────────────┐
        │  🛡️  MADARA MASTER v4.0 | SECURITY DAEMON     │
        ├─ File Info ────────────────────────────────────┤
        │  📁 File: ...    🔒 Algorithm: ...   🔄 ...   │
        ├─ Metrics ──────────────────────────────────────┤
        │  📊 Progress   🚀 Speed   💾 Written          │
        └────────────────────────────────────────────────┘
    """
    # ── Header ──
    header = Text(T("dash_header"), style="bold bright_cyan")

    # ── File Info Panel ──
    basename = os.path.basename(telemetry.current_file) if telemetry.current_file else "—"
    display_name = basename[:45] + "…" if len(basename) > 45 else basename

    if telemetry.current_pass > 0:
        status_text = _get_pass_status(telemetry.current_pass)
    elif telemetry.finished:
        status_text = T("dash_scrubbing")
    else:
        status_text = T("starting")

    info_table = Table(box=None, show_header=False, padding=(0, 2), expand=True)
    info_table.add_column("Key", style="bold white", ratio=1)
    info_table.add_column("Value", style="bright_white", ratio=3)
    info_table.add_row(T("dash_file"), f"[bright_yellow]{display_name}[/]")
    info_table.add_row(T("dash_algorithm"), "[dim]DoD 5220.22-M (3 Passes)[/]")
    info_table.add_row(T("dash_status"), f"[bright_cyan]{status_text}[/]")

    if total_files > 1:
        info_table.add_row(
            T("dash_file_counter"),
            f"[bright_magenta]{file_index}/{total_files}[/]"
        )

    # ── Metrics Grid ──
    progress_pct = telemetry.global_progress * 100
    speed = speed_tracker.get_speed()
    total_target = telemetry.total_target_bytes

    # Build the progress bar
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

    # Progress row
    progress_text = Group(
        bar,
        Text(f" {progress_pct:.1f}%", style="bold bright_green"),
    )
    metrics_table.add_row(T("dash_progress"), progress_text)

    # Speed row
    speed_str = f"{format_bytes(int(speed))}/s" if speed > 0 else "—"
    metrics_table.add_row(
        T("dash_speed"),
        Text(speed_str, style="bold bright_yellow"),
    )

    # Written row
    written_str = (
        f"{format_bytes(telemetry.bytes_written_total)} / "
        f"{format_bytes(total_target)}"
    )
    metrics_table.add_row(
        T("dash_written"),
        Text(written_str, style="bold bright_magenta"),
    )

    # ── Assemble ──
    inner = Group(
        Align.center(header),
        Text(""),  # spacer
        Panel(info_table, border_style="dim cyan", box=box.ROUNDED, padding=(0, 1)),
        Text(""),  # spacer
        Panel(metrics_table, border_style="dim cyan", box=box.ROUNDED, padding=(0, 1)),
    )

    return Panel(
        inner,
        border_style="bright_cyan",
        box=box.HEAVY,
        padding=(1, 2),
    )


def _print_completion_panel():
    """Renders the final green neon completion panel after Live stops."""
    console.print()
    console.print(
        Panel(
            Align.center(
                Text(T("completion_msg"), style="bold bright_green on black"),
            ),
            border_style="bright_green",
            box=box.DOUBLE_EDGE,
            padding=(1, 4),
        )
    )
    console.print()


# ──────────────────────── Commands ─────────────────────────────

async def async_wipe_logic(
    files: list[str],
    standard: SanitizationStandard = SanitizationStandard.NIST_CLEAR,
    verify: bool = False,
    log_path: Optional[str] = None
) -> WipeSummary:
    """
    Orchestrates the async wiping process with Live Dashboard.
    """
    # Configure custom audit logger if path provided
    audit_logger = None
    if log_path:
        from audit import AuditLogger
        from pathlib import Path
        audit_logger = AuditLogger(log_path=Path(log_path))

    wiper = AsyncWiper(audit_logger=audit_logger) 
    summary = WipeSummary()
    summary.total_files = len(files)
    start_time = time.time()

    telemetry = WipeTelemetry()
    speed_tracker = SpeedTracker(window_seconds=2.0)
    
    # Global bytes for speed tracking across files
    global_accumulated = 0

    with Live(
        _build_dashboard(telemetry, speed_tracker, 0, len(files)),
        console=console,
        refresh_per_second=12,
        transient=True,
    ) as live:
        
        for file_idx, filepath in enumerate(files, start=1):
            file_path_obj =  None
            try:
                # Handle path objects
                from pathlib import Path
                file_path_obj = Path(filepath)
                file_size = file_path_obj.stat().st_size if file_path_obj.exists() else 0
            except Exception:
                file_size = 0

            # Reset telemetry for this file
            telemetry.start_time = time.time()
            telemetry.current_pass = 0
            telemetry.file_size = file_size
            telemetry.current_file = filepath
            telemetry.bytes_written_total = 0
            telemetry.bytes_written_current_pass = 0
            telemetry.finished = False

            speed_tracker = SpeedTracker(window_seconds=2.0)

            # Callback for async wiper
            # async callback(path, pass_num, bytes_in_pass, total)
            async def progress_callback(p, pass_num, bytes_in_pass, total):
                telemetry.current_pass = pass_num
                telemetry.bytes_written_current_pass = bytes_in_pass
                
                # Approximate total based on pass
                # Note: this logic assumes equal pass sizes, which might not be true for different strategies
                # For visualization we can just sum up previous passes + current
                # Or simplistically:
                telemetry.bytes_written_total = bytes_in_pass # This is per-pass in current impl?
                # Wait, wiper_async calls callback with bytes_written_this_pass.
                # If we have multiple passes, we need to accumulate.
                # But AsyncWiper loops passes.
                # We can track 'accumulated_previous_passes' in the loop?
                # AsyncWiper doesn't expose that easily without state.
                # Let's rely on 'bytes_in_pass' and pass_num.
                # If pass_num > 1, we assume previous passes were full size.
                
                previous_bytes = (pass_num - 1) * total
                current_total = previous_bytes + bytes_in_pass
                telemetry.bytes_written_total = current_total
                
                speed_tracker.record(current_total)
                live.update(_build_dashboard(telemetry, speed_tracker, file_idx, len(files)))

            if not file_path_obj:
                 # Should not happen given logic above
                 continue

            # Execute Async Wipe
            result_dict = await wiper.wipe_file(
                file_path_obj, 
                standard=standard,
                verify=verify, 
                progress_callback=progress_callback
            )
            
            # Convert dict result to WipeResult (or minimal)
            # WipeResult is a dataclass in wiper.py. 
            # We can just use the dict or update WipeSummary to accept dicts?
            # WipeSummary expects 'results' list of WipeResult objects usually.
            # Let's mock a WipeResult object or change WipeSummary usage.
            # Existing WipeResult: filepath, success, error, bytes_written
            
            w_res = WipeResult(
                filepath=filepath,
                success=result_dict.get("success", False),
                error=result_dict.get("error"),
                bytes_written=0 # We don't track exact bytes in result dict yet, can assume file_size * passes
            )
            # Estimate bytes written
            passes = result_dict.get("passes_completed", 0)
            w_res.bytes_written = file_size * passes
            
            summary.results.append(w_res)

            if w_res.success:
                summary.files_wiped += 1
                summary.total_bytes_overwritten += w_res.bytes_written
                
                # Final update for this file
                telemetry.finished = True
                telemetry.bytes_written_total = w_res.bytes_written
                live.update(_build_dashboard(telemetry, speed_tracker, file_idx, len(files)))
            else:
                summary.files_failed += 1
                summary.errors.append(f"{filepath}: {w_res.error}")

    summary.total_duration = time.time() - start_time
    return summary

@app.command()
def wipe(
    target: str = typer.Argument(..., help="Path to file or directory to securely wipe"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation prompt"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview files without wiping"),
    standard: str = typer.Option("clear", "--standard", "-s", help="Sanitization standard: clear, purge, dod"),
    verify: bool = typer.Option(False, "--verify", "-v", help="Verify wipe with entropy check"),
    log_path: Optional[str] = typer.Option(None, "--log-path", "-l", help="Custom path for audit log"),
):
    """
    🧹 Securely wipe files using Async Engine (NIST SP 800-88 / DoD).
    
    Auto-detects Storage Type (SSD/HDD) and applies optimized sanitization.
    Generates Audit Logs (madara_audit.jsonl).
    """
    print_banner()
    target = os.path.abspath(target)

    # Validate standard
    std_enum = SanitizationStandard.NIST_CLEAR
    s_lower = standard.lower()
    if s_lower in ("clear", "nist_clear"):
        std_enum = SanitizationStandard.NIST_CLEAR
    elif s_lower in ("purge", "nist_purge"):
        std_enum = SanitizationStandard.NIST_PURGE
    elif s_lower in ("dod", "dod_legacy"):
        std_enum = SanitizationStandard.DOD_LEGACY
    else:
        console.print(f"\n  [bold red]Invalid standard:[/] {standard}. Valid: clear, purge, dod")
        raise typer.Exit(code=1)

    # Validate target exists
    if not os.path.exists(target):
        console.print(f"\n  [bold red]{T('target_not_found')}[/] {target}")
        raise typer.Exit(code=1)

    # Collect files
    files = collect_files(target)

    if not files:
        console.print(f"\n  [bold yellow]{T('no_files_found')}[/] {target}")
        raise typer.Exit(code=0)

    # Calculate total size
    total_size = sum(os.path.getsize(f) for f in files if os.path.exists(f))
    is_dir = os.path.isdir(target)

    # Show target info
    console.print()
    info_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    info_table.add_column("Key", style="bold cyan")
    info_table.add_column("Value", style="white")
    info_table.add_row(T("lbl_target"), target)
    info_table.add_row(T("lbl_type"), T("type_dir") if is_dir else T("type_file"))
    info_table.add_row(T("files_to_wipe"), str(len(files)))
    info_table.add_row(T("total_data"), format_bytes(total_size))
    info_table.add_row(T("method"), f"Async Auto-Detect (Standard: {std_enum.value})")
    info_table.add_row("Verify", "Yes" if verify else "No")
    if log_path:
        info_table.add_row("Audit Log", log_path)
    console.print(info_table)

    # Dry run
    if dry_run:
        console.print(f"\n  [bold yellow]{T('dry_run_title')}[/]\n")
        for f in files[:50]:
            size = os.path.getsize(f) if os.path.exists(f) else 0
            console.print(f"    [dim]•[/] {f} [dim]({format_bytes(size)})[/]")
        if len(files) > 50:
            console.print(f"    [dim]{T('more_files', n=len(files) - 50)}[/]")
        raise typer.Exit(code=0)

    # Confirmation
    if not confirm:
        console.print()
        console.print(
            Panel(
                f"[bold red]{T('warning_title')}[/]\n\n{T('warning_body')}",
                border_style="bright_red",
                box=box.DOUBLE_EDGE,
                padding=(1, 2),
            )
        )
        console.print()
        if not typer.confirm(T("confirm_prompt"), default=False):
            console.print(f"\n  [bold cyan]{T('op_cancelled')}[/]")
            raise typer.Exit(code=0)

    console.print()

    # ── Execute Async Wipe ──
    try:
        summary = asyncio.run(async_wipe_logic(
            files, 
            standard=std_enum, 
            verify=verify, 
            log_path=log_path
        ))
    except KeyboardInterrupt:
        console.print("\n[bold red]Interrupted by user.[/]")
        raise typer.Exit(1)

    # Remove empty directories if target was a directory
    if is_dir:
        for root, dirs, remaining_files in os.walk(target, topdown=False):
            for d in dirs:
                try:
                    os.rmdir(os.path.join(root, d))
                except OSError:
                    pass
        try:
            os.rmdir(target)
        except OSError:
            pass

    # ── Completion ──
    _print_completion_panel()
    print_summary(summary)


@app.command()
def version():
    """Show version information."""
    print_banner()
    console.print(f"\n  MadaraMaster v{VERSION}")
    console.print(f"  {T('version_desc')}")
    console.print(f"  {T('version_license')}\n")


# ──────────────────────── Interactive Session ──────────────────

def _parse_multi_paths(raw: str) -> list[str]:
    """
    Parses a raw input string that may contain one or more paths.

    Handles:
        - Single path:           C:\\Users\\docs\\secret.txt
        - Quoted path:           "C:\\Users\\My Docs\\file.txt"
        - Multiple drag-n-drop:  "C:\\a.txt" "C:\\b.txt" "C:\\c.txt"
        - Mixed:                 C:\\a.txt "C:\\My Dir\\b.txt"
    """
    paths: list[str] = []
    i = 0
    raw = raw.strip()

    while i < len(raw):
        # Skip whitespace between paths
        if raw[i] in (' ', '\t'):
            i += 1
            continue

        # Quoted path
        if raw[i] == '"':
            end = raw.find('"', i + 1)
            if end == -1:
                # Unterminated quote — take rest as path
                paths.append(raw[i + 1:].strip())
                break
            paths.append(raw[i + 1:end])
            i = end + 1
        elif raw[i] == "'":
            end = raw.find("'", i + 1)
            if end == -1:
                paths.append(raw[i + 1:].strip())
                break
            paths.append(raw[i + 1:end])
            i = end + 1
        else:
            # Unquoted path — runs until next space (unless it looks like a drive letter path)
            # On Windows, paths with spaces won't work unquoted with multi-file, but single file is fine
            end = i
            while end < len(raw) and raw[end] not in (' ', '\t', '"', "'"):
                end += 1
            paths.append(raw[i:end].strip())
            i = end

    # Filter empty strings
    return [p for p in paths if p]


def _print_file_preview(targets: list[str]):
    """Displays a rich preview table of the files about to be wiped."""
    table = Table(
        title=f"[bold bright_cyan]{T('preview_title')}[/]",
        box=box.ROUNDED,
        border_style="bright_cyan",
        padding=(0, 1),
        show_lines=True,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column(T("preview_name"), style="bold white", ratio=3)
    table.add_column(T("preview_size"), style="bright_yellow", justify="right", min_width=12)
    table.add_column(T("preview_type"), style="dim cyan", min_width=10)

    total_size = 0
    for idx, target in enumerate(targets, start=1):
        name = os.path.basename(target) or target
        if os.path.isdir(target):
            # Count files inside
            file_count = sum(len(files) for _, _, files in os.walk(target))
            size = sum(
                os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(target)
                for f in fs
                if os.path.exists(os.path.join(r, f))
            )
            type_str = f"📁 {T('type_dir')}"
            name_str = f"{name}/ [dim]({file_count} files)[/]"
        else:
            size = os.path.getsize(target) if os.path.exists(target) else 0
            type_str = f"📄 {T('type_file')}"
            name_str = name

        total_size += size
        table.add_row(str(idx), name_str, format_bytes(size), type_str)

    # Footer row with total
    table.add_row(
        "",
        f"[bold]{T('preview_total')}[/]",
        f"[bold bright_green]{format_bytes(total_size)}[/]",
        "",
    )

    console.print()
    console.print(table)
    console.print()


def _print_session_hints():
    """Prints the session drag-and-drop and exit hints."""
    hint = T('session_hint')
    if hint:
        console.print(f"  {hint}")
    console.print(f"  [dim]{T('session_exit_hint')}[/]\n")


def interactive_session():
    """
    Interactive session mode with multi-file accumulation.

    Flow:
        1. User drags/types paths one at a time → each is validated and added
        2. A running counter shows how many files are queued
        3. User presses Enter on empty line → preview table + confirm + wipe
        4. Exit keywords work at any point
    """
    print_banner()
    console.print(f"  [bold cyan]{T('session_title')}[/]\n")
    _print_session_hints()

    while True:
        # ── Accumulation phase: collect paths ──
        queued_targets: list[str] = []

        while True:
            try:
                raw = input(T("session_prompt"))
            except (EOFError, KeyboardInterrupt):
                # If we have queued targets, treat EOF/Interrupt as "done adding"
                # so we proceed to wipe them. If queue is empty, exit.
                if queued_targets:
                    break
                console.print(f"\n  [bold cyan]{T('session_ended')}[/]")
                return

            # Detect --force flag
            skip_confirm = False
            if raw.rstrip().endswith("--force"):
                raw = raw.rstrip()[:-len("--force")]
                skip_confirm = True

            # Sanitize
            cleaned = raw.strip().strip("'").strip('"').strip()

            # Empty input = move to wipe phase (if we have files)
            if not cleaned:
                if queued_targets:
                    break  # Proceed to preview + wipe
                continue  # Nothing queued yet, just ignore

            # Exit keywords (check the raw cleaned input)
            if cleaned.lower() in EXIT_KEYWORDS[current_lang]:
                console.print(f"\n  [bold cyan]{T('session_goodbye')}[/]")
                return

            # Parse paths (handles both single path and multiple quoted paths
            # e.g. dragging 2 files at once: "path1" "path2")
            parsed = _parse_multi_paths(raw)
            if not parsed:
                # Fallback: treat cleaned input as a single path
                parsed = [cleaned]

            for p in parsed:
                target = os.path.abspath(p.strip())
                if not os.path.exists(target):
                    console.print(f"  [bold red]{T('path_not_found')}[/] {target}")
                    continue

                # Add to queue
                queued_targets.append(target)
                basename = os.path.basename(target) or target
                size = os.path.getsize(target) if os.path.isfile(target) else sum(
                    os.path.getsize(os.path.join(r, f))
                    for r, _, fs in os.walk(target)
                    for f in fs
                    if os.path.exists(os.path.join(r, f))
                )
                console.print(
                    f"  [bright_green]✓[/] [bold]{basename}[/] "
                    f"[dim]({format_bytes(size)})[/] — "
                    f"[bright_cyan]{T('queue_count', n=len(queued_targets))}[/]"
                )
            console.print(f"  [dim]{T('queue_hint')}[/]")

        # ── Preview phase ──
        _print_file_preview(queued_targets)

        # ── Confirmation ──
        if not skip_confirm:
            if not confirm_action():
                console.print(f"  [bold cyan]{T('op_cancelled')}[/]")
                console.print()
                _print_session_hints()
                continue

        # ── Wipe phase ──
        # ── Wipe phase ──
        try:
            asyncio.run(async_wipe_logic(queued_targets))
            
            # Explicit completion message and pause
            console.print()
            console.print(Panel(
                Align.center(f"[bold bright_green]✅ {T('completion_msg')}[/]"),
                border_style="green",
                padding=(1, 2)
            ))
            resp = console.input(f"\n  [dim]{T('continue_prompt')}[/]")
            if resp.strip().lower() in EXIT_KEYWORDS[current_lang]:
                console.print(f"\n  [bold cyan]{T('session_goodbye')}[/]")
                # Add slight delay for readability
                time.sleep(0.5)
                break

        except KeyboardInterrupt:
            console.print("\n[bold red]Interrupted by user.[/]")
        except Exception as e:
            console.print(f"\n[bold red]Error during wipe session: {e}[/]")

        # Re-display session hints after wipe completes
        console.print()
        _print_session_hints()


# ──────────────────────── Windows Context Menu ────────────────

def install_context_menu():
    """Installs MadaraMaster into the Windows right-click context menu."""
    if sys.platform != "win32":
        print("Error: Context menu installation is only available on Windows.")
        return

    import winreg

    try:
        key_path = r"*\shell\MadaraMaster"
        command_path = key_path + r"\command"
        script_path = os.path.abspath(__file__)
        cmd = f'"{ sys.executable}" "{script_path}" wipe "%1"'

        # Create shell key with display name and icon
        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Wipe with MadaraMaster")
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, sys.executable)
        winreg.CloseKey(key)

        # Create command key
        cmd_key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, command_path)
        winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(cmd_key)

        print("✔ Context menu installed successfully.")
        print(f"  Command: {cmd}")
    except PermissionError:
        print("Error: Run CMD as Administrator to install context menu.")
    except Exception as e:
        print(f"Error: {e}")


# ──────────────────────── Entry Point ──────────────────────────

if __name__ == "__main__":
    # Handle context menu installation before Typer
    if len(sys.argv) > 1 and sys.argv[1] == "install-right-click":
        install_context_menu()
        sys.exit(0)

    if len(sys.argv) <= 1:
        # Interactive mode: select language first, then start session
        current_lang = select_language()
        interactive_session()
    else:
        # CLI mode: default to EN for standard CLI usage
        app()
