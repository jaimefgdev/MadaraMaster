#!/usr/bin/env python3
# MadaraMaster — interfaz CLI v4.0
# jaimefg1888
#
# Herramienta de sanitización segura con dashboard en tiempo real.
# Implementa DoD 5220.22-M y NIST SP 800-88.
# Soporte bilingüe: Inglés (EN) y Español (ES).
#
# Uso:
#   python madara.py                          # modo sesión interactiva
#   python madara.py wipe <RUTA>              # borrar archivo o directorio
#   python madara.py wipe <RUTA> --confirm    # sin confirmación
#   python madara.py wipe <RUTA> --dry-run    # vista previa sin borrar

import asyncio
import collections
import errno
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import aiofiles
import typer
from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from safety import find_danger
from storage import SanitizationStandard
from trim import send_trim
from utils import format_bytes
from wiper import (
    DOD_PASSES,
    WipeResult,
    WipeSummary,
    WipeTelemetry,
    collect_files,
)
from wiper_async import AsyncWiper

# ─── Application ─────────────────────────────────────────────────────────────

app = typer.Typer(
    name="madaramaster",
    help="🧹 MadaraMaster — Sanitización Segura de Archivos DoD 5220.22-M",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()
VERSION = "4.0.0"

# ─── i18n ────────────────────────────────────────────────────────────────────
# All user-visible strings are stored here to keep the rest of the code
# free of hard-coded text and to make adding new languages trivial.

LANG: dict[str, dict[str, str]] = {
    "EN": {
        "session_title": "Interactive Session Mode",
        "session_hint": "Drag files and press Enter (or type the path).",
        "session_exit_hint": "Type [bold]exit[/bold] or [bold]close[/bold] to quit.",
        "queue_count": "{n} file(s) queued",
        "queue_hint": "Add more files or press Enter to WIPE.",
        "session_prompt": "❱❱❱ ",
        "session_ended": "Session ended.",
        "session_goodbye": "👋 Session ended. See you later.",
        "continue_prompt": "Press Enter to start a new wipe session or type [bold]exit[/bold] to quit...",
        "path_not_found": "✗ Path not found:",
        "target_not_found": "✗ Target not found:",
        "no_files_found": "⚠ No files found in:",
        "type_dir": "Directory (recursive)",
        "type_file": "Single file",
        "lbl_target": "Target",
        "lbl_type": "Type",
        "files_to_wipe": "Files to wipe",
        "total_data": "Total data",
        "method": "Method",
        "passes": "Passes",
        "pass_values": "1) Zeros  2) Ones  3) Random",
        "dry_run_title": "🔍 DRY RUN — no files will be modified:",
        "more_files": "...and {n} more files",
        "warning_title": "⚠ WARNING: THIS ACTION IS IRREVERSIBLE ⚠",
        "warning_body": (
            "All targeted files will be overwritten 3 times and permanently deleted.\n"
            "[bold]Data CANNOT be recovered after this operation.[/]"
        ),
        "confirm_prompt": "  Are you sure you want to proceed?",
        "confirm_msg": "Are you sure? [y/N]: ",
        "op_cancelled": "Operation cancelled.",
        "starting": "Starting...",
        "preview_title": "📋 FILES TO DESTROY",
        "preview_name": "Name",
        "preview_size": "Size",
        "preview_type": "Type",
        "preview_total": "TOTAL",
        "dash_header": "🛡️  MADARA MASTER v4.0.0 | SECURITY DAEMON",
        "dash_file": "📁 File",
        "dash_algorithm": "🔒 Algorithm",
        "dash_status": "🔄 Status",
        "dash_pass_1": "Pass 1/3 — Overwriting with 0x00 (Zeros)...",
        "dash_pass_2": "Pass 2/3 — Overwriting with 0xFF (Ones)...",
        "dash_pass_3": "Pass 3/3 — Overwriting with Random Bytes...",
        "dash_scrubbing": "🧹 Scrubbing metadata & deleting...",
        "dash_progress": "📊 Global Progress",
        "dash_speed": "🚀 Speed",
        "dash_written": "💾 Effective Write",
        "dash_file_counter": "📂 File",
        "summary_title": "🧹 WIPE SUMMARY",
        "metric": "Metric",
        "value": "Value",
        "total_targeted": "Total Files Targeted",
        "files_wiped_ok": "Files Wiped Successfully",
        "files_failed": "Files Failed",
        "total_overwritten": "Total Bytes Overwritten",
        "effective_written": "Effective Data Written",
        "total_duration": "Total Duration",
        "avg_speed": "Average Write Speed",
        "errors_title": "⚠ Errors",
        "more_errors": "...and {n} more",
        "all_sanitized_one": "✔ {n} FILE DELETED — DATA IRRECOVERABLE",
        "all_sanitized_many": "✔ {n} FILES DELETED — DATA IRRECOVERABLE",
        "partial_wipe": "⚠ PARTIAL WIPE — {wiped} wiped, {failed} failed",
        "no_files_wiped": "✗ NO FILES WERE WIPED",
        "completion_msg": "DELETION COMPLETED SUCCESSFULLY",
        "pass_1": "Pass 1/3 · Zeros",
        "pass_2": "Pass 2/3 · Ones",
        "pass_3": "Pass 3/3 · Random",
        "wiped": "✔ Wiped",
        "version_desc": "DoD 5220.22-M Compliant Secure File Sanitization",
        "version_license": "License: MIT — Authorized Use Only",
        "lbl_verify": "Verify",
        "lbl_audit_log": "Audit Log",
        "wfs_title": "Wipe Free Space",
        "wfs_hint": "Creating a temporary fill-file to defeat wear-leveling…",
        "wfs_filling": "Filling free space with zeros",
        "wfs_chunk": "Chunk",
        "wfs_enospc": "Disk full — all free space covered.",
        "wfs_syncing": "Syncing to physical media (fsync)…",
        "wfs_removing": "Removing fill-file…",
        "wfs_trim": "Sending TRIM to storage controller…",
        "wfs_trim_ok": "TRIM sent successfully.",
        "wfs_trim_skip": "TRIM skipped (not SSD/NVMe or insufficient permissions).",
        "wfs_done": "Free-space wipe complete.",
        "wfs_written": "Zeros written",
        "wfs_duration": "Duration",
        "wfs_error": "Error during free-space wipe",
        "wfs_dry": "DRY RUN — target directory:",
        "dangerous_target": "✗ Refusing to wipe a protected target:",
        "dangerous_target_hint": "Use --allow-dangerous-target only if you are absolutely sure.",
        "confirm_type_name": "  Type the directory name ({name}) to confirm",
        "wfs_cleanup_failed": "Could not remove the fill file — delete it manually:",
    },
    "ES": {
        "session_title": "Modo Sesión Interactiva",
        "session_hint": "Arrastra archivos y pulsa Enter (o escribe la ruta).",
        "session_exit_hint": "Escribe [bold]salir[/bold] o [bold]cerrar[/bold] para salir.",
        "queue_count": "{n} archivo(s) en cola",
        "queue_hint": "Añade más archivos o pulsa Enter para BORRAR.",
        "session_prompt": "❱❱❱ ",
        "session_ended": "Sesión terminada.",
        "session_goodbye": "👋 Sesión terminada. Hasta pronto.",
        "continue_prompt": "Presiona Enter para iniciar una nueva sesión o escribe [bold]salir[/bold] para salir...",
        "path_not_found": "✗ Ruta no encontrada:",
        "target_not_found": "✗ Objetivo no encontrado:",
        "no_files_found": "⚠ No se encontraron archivos en:",
        "type_dir": "Directorio (recursivo)",
        "type_file": "Archivo individual",
        "lbl_target": "Objetivo",
        "lbl_type": "Tipo",
        "files_to_wipe": "Archivos a borrar",
        "total_data": "Datos totales",
        "method": "Método",
        "passes": "Pases",
        "pass_values": "1) Ceros  2) Unos  3) Aleatorio",
        "dry_run_title": "🔍 SIMULACIÓN — no se modificará ningún archivo:",
        "more_files": "...y {n} archivos más",
        "warning_title": "⚠ ADVERTENCIA: ESTA ACCIÓN ES IRREVERSIBLE ⚠",
        "warning_body": (
            "Todos los archivos serán sobrescritos 3 veces y eliminados permanentemente.\n"
            "[bold]Los datos NO se podrán recuperar tras esta operación.[/]"
        ),
        "confirm_prompt": "  ¿Estás seguro de que deseas continuar?",
        "confirm_msg": "¿Estás seguro? [s/N]: ",
        "op_cancelled": "Operación cancelada.",
        "starting": "Iniciando...",
        "preview_title": "📋 ARCHIVOS A DESTRUIR",
        "preview_name": "Nombre",
        "preview_size": "Tamaño",
        "preview_type": "Tipo",
        "preview_total": "TOTAL",
        "dash_header": "🛡️  MADARA MASTER v4.0.0 | SECURITY DAEMON",
        "dash_file": "📁 Archivo",
        "dash_algorithm": "🔒 Algoritmo",
        "dash_status": "🔄 Estado",
        "dash_pass_1": "Pase 1/3 — Sobrescribiendo con 0x00 (Ceros)...",
        "dash_pass_2": "Pase 2/3 — Sobrescribiendo con 0xFF (Unos)...",
        "dash_pass_3": "Pase 3/3 — Sobrescribiendo con Bytes Aleatorios...",
        "dash_scrubbing": "🧹 Limpiando metadatos y eliminando...",
        "dash_progress": "📊 Progreso Global",
        "dash_speed": "🚀 Velocidad",
        "dash_written": "💾 Escritura Efectiva",
        "dash_file_counter": "📂 Archivo",
        "summary_title": "🧹 RESUMEN DE BORRADO",
        "metric": "Métrica",
        "value": "Valor",
        "total_targeted": "Total Archivos Objetivo",
        "files_wiped_ok": "Archivos Borrados con Éxito",
        "files_failed": "Archivos Fallidos",
        "total_overwritten": "Total Bytes Sobrescritos",
        "effective_written": "Datos Efectivos Escritos",
        "total_duration": "Duración Total",
        "avg_speed": "Velocidad Media de Escritura",
        "errors_title": "⚠ Errores",
        "more_errors": "...y {n} más",
        "all_sanitized_one": "✔ {n} ARCHIVO ELIMINADO — DATOS IRRECUPERABLES",
        "all_sanitized_many": "✔ {n} ARCHIVOS ELIMINADOS — DATOS IRRECUPERABLES",
        "partial_wipe": "⚠ BORRADO PARCIAL — {wiped} borrados, {failed} fallidos",
        "no_files_wiped": "✗ NO SE BORRÓ NINGÚN ARCHIVO",
        "completion_msg": "ELIMINACIÓN COMPLETADA CON ÉXITO",
        "pass_1": "Pase 1/3 · Ceros",
        "pass_2": "Pase 2/3 · Unos",
        "pass_3": "Pase 3/3 · Aleatorio",
        "wiped": "✔ Borrado",
        "version_desc": "Sanitización Segura de Archivos — Norma DoD 5220.22-M",
        "version_license": "Licencia: MIT — Uso Autorizado Únicamente",
        "lbl_verify": "Verificar",
        "lbl_audit_log": "Log Auditoría",
        "wfs_title": "Borrado de Espacio Libre",
        "wfs_hint": "Creando archivo de relleno temporal para contrarrestar el wear-leveling…",
        "wfs_filling": "Rellenando espacio libre con ceros",
        "wfs_chunk": "Bloque",
        "wfs_enospc": "Disco lleno — espacio libre cubierto.",
        "wfs_syncing": "Sincronizando con el soporte físico (fsync)…",
        "wfs_removing": "Eliminando archivo de relleno…",
        "wfs_trim": "Enviando TRIM al controlador de almacenamiento…",
        "wfs_trim_ok": "TRIM enviado correctamente.",
        "wfs_trim_skip": "TRIM omitido (no es SSD/NVMe o permisos insuficientes).",
        "wfs_done": "Borrado de espacio libre completado.",
        "wfs_written": "Ceros escritos",
        "wfs_duration": "Duración",
        "wfs_error": "Error durante el borrado de espacio libre",
        "wfs_dry": "SIMULACIÓN — directorio objetivo:",
        "dangerous_target": "✗ Objetivo protegido, no se borrará:",
        "dangerous_target_hint": "Usa --allow-dangerous-target solo si estás completamente seguro.",
        "confirm_type_name": "  Escribe el nombre del directorio ({name}) para confirmar",
        "wfs_cleanup_failed": "No se pudo eliminar el archivo de relleno; bórralo a mano:",
    },
}

current_lang: str = "EN"

EXIT_KEYWORDS: dict[str, frozenset[str]] = {
    "EN": frozenset(["exit", "close", "quit"]),
    "ES": frozenset(["salir", "cerrar"]),
}

CONFIRM_YES: frozenset[str] = frozenset(["y", "yes", "s", "si"])

# ─── Wipe-free-space chunk sizes ─────────────────────────────────────────────
_FILL_CHUNK_LARGE = 64 * 1024 * 1024
_FILL_CHUNK_SMALL = 4 * 1024
_ZEROS_LARGE = b"\x00" * _FILL_CHUNK_LARGE
_ZEROS_SMALL = b"\x00" * _FILL_CHUNK_SMALL

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

   MadaraMaster v4.0.0 • Created by jaimefg1888 • DoD 5220.22-M
"""


# ─── i18n helper ─────────────────────────────────────────────────────────────


def T(key: str, **kwargs: object) -> str:
    """Look up a translation key in the active language dictionary.

    Args:
        key: Translation key defined in :data:`LANG`.
        **kwargs: Format arguments substituted into the translated string.

    Returns:
        The translated (and optionally formatted) string, or *key* itself
        if no entry is found.
    """
    text = LANG[current_lang].get(key, key)
    return text.format(**kwargs) if kwargs else text


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
            Align.center(Text(BANNER, style="bold red")),
            border_style="bright_cyan",
            box=box.DOUBLE_EDGE,
            subtitle=f"[dim]DoD 5220.22-M Compliant · v{VERSION}[/]",
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
    header = Text(T("dash_header"), style="bold bright_cyan")

    basename = os.path.basename(telemetry.current_file) if telemetry.current_file else "—"
    display_name = basename[:45] + "…" if len(basename) > 45 else basename

    if telemetry.finished:
        status_text = T("dash_scrubbing")
    elif telemetry.current_pass > 0:
        status_text = T(f"dash_pass_{telemetry.current_pass}")
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
            T("dash_file_counter"), f"[bright_magenta]{file_index}/{total_files}[/]"
        )

    progress_pct = telemetry.global_progress * 100
    speed = speed_tracker.get_speed()
    total_target = telemetry.total_target_bytes

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
            f"{format_bytes(telemetry.bytes_written_total)} / {format_bytes(total_target)}",
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


def _print_completion_panel() -> None:
    """Render the post-wipe completion banner."""
    console.print()
    console.print(
        Panel(
            Align.center(Text(T("completion_msg"), style="bold bright_green on black")),
            border_style="bright_green",
            box=box.DOUBLE_EDGE,
            padding=(1, 4),
        )
    )
    console.print()


# ─── Async wipe orchestration ─────────────────────────────────────────────────


async def async_wipe_logic(
    files: list[str],
    standard: SanitizationStandard = SanitizationStandard.NIST_CLEAR,
    verify: bool = False,
    log_path: Optional[str] = None,
    allow_hardlinks: bool = False,
) -> WipeSummary:
    """Drive the async wipe engine for a list of files with a live dashboard.

    Args:
        files: Absolute paths of files to wipe.
        standard: Sanitization standard to apply.
        verify: When ``True``, re-read and compare each file after wiping.
        log_path: Optional path to a custom audit-log file.
        allow_hardlinks: Also wipe files that have several hard links.

    Returns:
        A :class:`~wiper.WipeSummary` aggregating the results.
    """
    audit_logger = None
    if log_path:
        from audit import AuditLogger

        audit_logger = AuditLogger(log_path=Path(log_path))

    wiper = AsyncWiper(audit_logger=audit_logger)
    summary = WipeSummary()
    summary.total_files = len(files)
    start_time = time.time()

    telemetry = WipeTelemetry()
    speed_tracker = SpeedTracker(window_seconds=2.0)

    with Live(
        _build_dashboard(telemetry, speed_tracker, 0, len(files)),
        console=console,
        refresh_per_second=12,
        transient=True,
    ) as live:
        for file_idx, filepath in enumerate(files, start=1):
            try:
                file_path_obj = Path(filepath)
                file_size = file_path_obj.lstat().st_size
            except Exception:
                file_size = 0

            telemetry.start_time = time.time()
            telemetry.current_pass = 0
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
            ) -> None:
                telemetry.current_pass = pass_num
                telemetry.bytes_written_current_pass = bytes_in_pass
                current_total = (pass_num - 1) * total + bytes_in_pass
                telemetry.bytes_written_total = current_total
                speed_tracker.record(current_total)
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
                error=result_dict.get("error", ""),
                bytes_written=file_size * result_dict.get("passes_completed", 0),
            )
            summary.results.append(w_res)

            if w_res.success:
                summary.files_wiped += 1
                summary.total_bytes_overwritten += w_res.bytes_written
                telemetry.finished = True
                telemetry.bytes_written_total = w_res.bytes_written
                live.update(_build_dashboard(telemetry, speed_tracker, file_idx, len(files)))
            else:
                summary.files_failed += 1
                summary.errors.append(f"{filepath}: {w_res.error}")

    summary.total_duration = time.time() - start_time
    return summary


# ─── Typer commands ───────────────────────────────────────────────────────────


@app.command()
def wipe(
    target: str = typer.Argument(..., help="Ruta al archivo o directorio a borrar"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Saltar confirmación"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Vista previa sin borrar"),
    standard: str = typer.Option("clear", "--standard", "-s", help="Estándar: clear, purge, dod"),
    verify: bool = typer.Option(False, "--verify", "-v", help="Verificar con entropía Shannon"),
    log_path: Optional[str] = typer.Option(
        None, "--log-path", "-l", help="Ruta personalizada para el log"
    ),
    allow_hardlinks: bool = typer.Option(
        False,
        "--allow-hardlinks",
        help="Borrar también ficheros con varios enlaces duros (destruye los datos de todos sus nombres)",
    ),
    allow_dangerous_target: bool = typer.Option(
        False,
        "--allow-dangerous-target",
        help="Permitir objetivos protegidos: raíz, HOME, directorios del sistema, puntos de montaje",
    ),
) -> None:
    """🧹 Borrado seguro con motor Async (NIST SP 800-88 / DoD 5220.22-M)."""
    print_banner()
    target = os.path.abspath(target)

    std_map: dict[str, SanitizationStandard] = {
        "clear": SanitizationStandard.NIST_CLEAR,
        "nist_clear": SanitizationStandard.NIST_CLEAR,
        "purge": SanitizationStandard.NIST_PURGE,
        "nist_purge": SanitizationStandard.NIST_PURGE,
        "dod": SanitizationStandard.DOD_LEGACY,
        "dod_legacy": SanitizationStandard.DOD_LEGACY,
    }
    std_enum = std_map.get(standard.lower())
    if not std_enum:
        console.print(f"\n  [bold red]Estándar inválido:[/] {standard}. Válidos: clear, purge, dod")
        raise typer.Exit(code=1)

    if not os.path.lexists(target):
        console.print(f"\n  [bold red]{T('target_not_found')}[/] {target}")
        raise typer.Exit(code=1)

    danger = find_danger(target)
    if danger and not allow_dangerous_target:
        console.print(f"\n  [bold red]{T('dangerous_target')}[/] {danger}")
        console.print(f"  [dim]{T('dangerous_target_hint')}[/]")
        raise typer.Exit(code=2)

    files = collect_files(target)
    if not files:
        console.print(f"\n  [bold yellow]{T('no_files_found')}[/] {target}")
        raise typer.Exit(code=0)

    total_size = sum(_lsize(f) for f in files)
    is_dir = os.path.isdir(target) and not os.path.islink(target)

    console.print()
    info_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    info_table.add_column("Key", style="bold cyan")
    info_table.add_column("Value", style="white")
    info_table.add_row(T("lbl_target"), target)
    info_table.add_row(T("lbl_type"), T("type_dir") if is_dir else T("type_file"))
    info_table.add_row(T("files_to_wipe"), str(len(files)))
    info_table.add_row(T("total_data"), format_bytes(total_size))
    info_table.add_row(T("method"), f"Async Auto-Detect (Standard: {std_enum.value})")
    info_table.add_row(T("lbl_verify"), "Yes" if verify else "No")
    if log_path:
        info_table.add_row(T("lbl_audit_log"), log_path)
    console.print(info_table)

    if dry_run:
        console.print(f"\n  [bold yellow]{T('dry_run_title')}[/]\n")
        for f in files[:50]:
            size = _lsize(f)
            console.print(f"    [dim]•[/] {f} [dim]({format_bytes(size)})[/]")
        if len(files) > 50:
            console.print(f"    [dim]{T('more_files', n=len(files) - 50)}[/]")
        raise typer.Exit(code=0)

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
        if is_dir:
            expected = os.path.basename(target)
            typed = typer.prompt(T("confirm_type_name", name=expected), default="")
            confirmed = typed.strip() == expected
        else:
            confirmed = typer.confirm(T("confirm_prompt"), default=False)
        if not confirmed:
            console.print(f"\n  [bold cyan]{T('op_cancelled')}[/]")
            raise typer.Exit(code=0)

    console.print()

    try:
        summary = asyncio.run(
            async_wipe_logic(
                files,
                standard=std_enum,
                verify=verify,
                log_path=log_path,
                allow_hardlinks=allow_hardlinks,
            )
        )
    except KeyboardInterrupt:
        console.print("\n[bold red]Interrumpido por el usuario.[/]")
        raise typer.Exit(1)

    if is_dir:
        for root, dirs, _ in os.walk(target, topdown=False):
            for d in dirs:
                try:
                    os.rmdir(os.path.join(root, d))
                except OSError:
                    pass
        try:
            os.rmdir(target)
        except OSError:
            pass

    _print_completion_panel()
    print_summary(summary)


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


@app.command("wipe-free-space")
def wipe_free_space_cmd(
    path: str = typer.Argument(
        default=".",
        help="Directorio cuyo espacio libre se va a sobrescribir (default: directorio actual)",
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Saltar confirmación"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Vista previa sin ejecutar"),
    no_trim: bool = typer.Option(False, "--no-trim", help="Omitir el TRIM post-borrado"),
) -> None:
    """🧹 Rellena el espacio libre del disco con ceros para contrarrestar el wear-leveling.

    Escribe ceros hasta ENOSPC, hace fsync() y borra el archivo temporal.
    En SSD/NVMe envía además TRIM para activar el GC del controlador.

    Uso::

        python madara.py wipe-free-space /ruta/directorio
        python madara.py wipe-free-space . --confirm
        python madara.py wipe-free-space /mnt/datos --dry-run
    """
    from storage import detect_storage_type

    print_banner()
    target_dir = Path(os.path.abspath(path))

    if not target_dir.is_dir():
        console.print(f"\n  [bold red]{T('target_not_found')}[/] {target_dir}")
        raise typer.Exit(code=1)

    try:
        sv = os.statvfs(target_dir) if hasattr(os, "statvfs") else None
        free_b: Optional[int] = (sv.f_bavail * sv.f_frsize) if sv else None
    except OSError:
        free_b = None

    storage_type = detect_storage_type(target_dir)

    console.print()
    info = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    info.add_column("Key", style="bold cyan")
    info.add_column("Value", style="white")
    info.add_row(T("lbl_target"), str(target_dir))
    info.add_row("Storage", storage_type.value.upper())
    info.add_row("Free space", format_bytes(free_b) if free_b else "—")
    info.add_row(
        "Method",
        "Fill 0x00 → fsync → unlink" + ("" if no_trim else " → TRIM"),
    )
    console.print(info)

    if dry_run:
        console.print(f"\n  [bold yellow]{T('wfs_dry')}[/] {target_dir}")
        raise typer.Exit(code=0)

    if not confirm:
        console.print()
        console.print(
            Panel(
                f"[bold yellow]{T('wfs_hint')}[/]\n\n"
                "[dim]El disco quedará momentáneamente lleno — comportamiento esperado.\n"
                "No se modificará ningún archivo existente.[/]",
                border_style="yellow",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        console.print()
        if not typer.confirm(T("confirm_prompt"), default=False):
            console.print(f"\n  [bold cyan]{T('op_cancelled')}[/]")
            raise typer.Exit(code=0)

    console.print()

    written_ref: list[int] = [0]
    chunk_ref: list[int] = [0]
    start_ref: list[float] = [time.time()]

    def _build_wfs_panel() -> Panel:
        elapsed = time.time() - start_ref[0]
        speed = written_ref[0] / elapsed if elapsed > 0 else 0
        pct_str = (
            f"  [dim]({100 * written_ref[0] / free_b:.1f}%)[/]"
            if free_b and free_b > 0
            else ""
        )
        inner = Table(box=None, show_header=False, padding=(0, 2), expand=True)
        inner.add_column("Key", style="bold white", ratio=1)
        inner.add_column("Value", style="bright_white", ratio=3)
        inner.add_row(
            T("wfs_filling"),
            f"[bright_yellow]{format_bytes(written_ref[0])}[/]"
            + (f" / {format_bytes(free_b)}" if free_b else "")
            + pct_str,
        )
        inner.add_row(T("dash_speed"), f"[bright_cyan]{format_bytes(int(speed))}/s[/]")
        inner.add_row(T("wfs_chunk"), f"[dim]{chunk_ref[0]}[/]")
        inner.add_row(T("total_duration"), f"[bright_magenta]{elapsed:.1f}s[/]")
        return Panel(
            inner,
            title=f"[bold bright_cyan]{T('wfs_title')}[/]",
            border_style="bright_cyan",
            box=box.HEAVY,
            padding=(1, 2),
        )

    def _update(bw: int, ci: int) -> None:
        written_ref[0] = bw
        chunk_ref[0] = ci

    try:
        with Live(
            _build_wfs_panel(),
            console=console,
            refresh_per_second=8,
            transient=True,
        ) as live:
            start_ref[0] = time.time()

            async def _run() -> dict[str, object]:
                return await _async_wipe_free_space(
                    target_dir,
                    update_fn=lambda bw, ci: (_update(bw, ci), live.update(_build_wfs_panel())),
                    trim=not no_trim,
                )

            result = asyncio.run(_run())

    except KeyboardInterrupt:
        console.print("\n[bold red]Interrumpido por el usuario.[/]")
        raise typer.Exit(1)

    console.print()
    if result["success"]:
        t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        t.add_column("Key", style="bold cyan")
        t.add_column("Value", style="bright_green")
        t.add_row(T("wfs_written"), format_bytes(result["bytes_written"]))
        t.add_row(T("wfs_duration"), f"{result['duration']:.2f}s")
        if not no_trim:
            t.add_row(
                "TRIM",
                T("wfs_trim_ok") if result["trim_sent"] else T("wfs_trim_skip"),
            )
        console.print(t)
        console.print()
        console.print(
            Panel(
                Align.center(Text(T("wfs_done"), style="bold bright_green")),
                border_style="bright_green",
                box=box.DOUBLE_EDGE,
                padding=(1, 4),
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]{T('wfs_error')}:[/]\n{result.get('error', '—')}",
                border_style="red",
                box=box.ROUNDED,
            )
        )
        raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Display version and license information."""
    print_banner()
    console.print(f"\n  MadaraMaster v{VERSION}")
    console.print(f"  {T('version_desc')}")
    console.print(f"  {T('version_license')}\n")


# ─── Interactive session ──────────────────────────────────────────────────────


def _parse_multi_paths(raw: str) -> list[str]:
    """Parse a raw input string that may contain one or more file paths.

    Handles paths with and without surrounding quotes and separates multiple
    paths delimited by whitespace.

    Args:
        raw: Raw text as entered by the user (possibly drag-and-dropped from
            the OS, which may wrap paths in quotes).

    Returns:
        A list of non-empty path strings.
    """
    paths: list[str] = []
    i = 0
    raw = raw.strip()

    while i < len(raw):
        if raw[i] in (" ", "\t"):
            i += 1
            continue
        if raw[i] in ('"', "'"):
            quote = raw[i]
            end = raw.find(quote, i + 1)
            if end == -1:
                paths.append(raw[i + 1 :].strip())
                break
            paths.append(raw[i + 1 : end])
            i = end + 1
        else:
            end = i
            while end < len(raw) and raw[end] not in (" ", "\t", '"', "'"):
                end += 1
            paths.append(raw[i:end].strip())
            i = end

    return [p for p in paths if p]


def _print_file_preview(targets: list[str]) -> None:
    """Render a Rich table previewing the files queued for wiping.

    Args:
        targets: List of absolute paths (files or directories) to preview.
    """
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

    table.add_row(
        "",
        f"[bold]{T('preview_total')}[/]",
        f"[bold bright_green]{format_bytes(total_size)}[/]",
        "",
    )
    console.print()
    console.print(table)
    console.print()


def _print_session_hints() -> None:
    """Print the interactive-session usage hints."""
    hint = T("session_hint")
    if hint:
        console.print(f"  {hint}")
    console.print(f"  [dim]{T('session_exit_hint')}[/]\n")


def interactive_session() -> None:
    """Run the interactive drag-and-drop wipe session.

    Prompts the user to enter or drag file paths, builds a queue, previews
    it, then triggers the async wipe engine.  Loops until the user types an
    exit keyword.
    """
    print_banner()
    console.print(f"  [bold cyan]{T('session_title')}[/]\n")
    _print_session_hints()

    while True:
        queued_targets: list[str] = []
        skip_confirm = False

        while True:
            try:
                raw = input(T("session_prompt"))
            except (EOFError, KeyboardInterrupt):
                if queued_targets:
                    break
                console.print(f"\n  [bold cyan]{T('session_ended')}[/]")
                return

            if raw.rstrip().endswith("--force"):
                raw = raw.rstrip()[: -len("--force")]
                skip_confirm = True

            cleaned = raw.strip().strip("'").strip('"').strip()

            if not cleaned:
                if queued_targets:
                    break
                continue

            if cleaned.lower() in EXIT_KEYWORDS[current_lang]:
                console.print(f"\n  [bold cyan]{T('session_goodbye')}[/]")
                return

            parsed = _parse_multi_paths(raw) or [cleaned]

            for p in parsed:
                target = os.path.abspath(p.strip())
                if not os.path.exists(target):
                    console.print(f"  [bold red]{T('path_not_found')}[/] {target}")
                    continue

                queued_targets.append(target)
                basename = os.path.basename(target) or target
                size = (
                    os.path.getsize(target)
                    if os.path.isfile(target)
                    else sum(
                        os.path.getsize(os.path.join(r, f))
                        for r, _, fs in os.walk(target)
                        for f in fs
                        if os.path.exists(os.path.join(r, f))
                    )
                )
                console.print(
                    f"  [bright_green]✓[/] [bold]{basename}[/] "
                    f"[dim]({format_bytes(size)})[/] — "
                    f"[bright_cyan]{T('queue_count', n=len(queued_targets))}[/]"
                )
            console.print(f"  [dim]{T('queue_hint')}[/]")

        _print_file_preview(queued_targets)

        if not skip_confirm:
            if not confirm_action():
                console.print(f"  [bold cyan]{T('op_cancelled')}[/]\n")
                _print_session_hints()
                continue

        try:
            asyncio.run(async_wipe_logic(queued_targets))
            console.print()
            console.print(
                Panel(
                    Align.center(f"[bold bright_green]✅ {T('completion_msg')}[/]"),
                    border_style="green",
                    padding=(1, 2),
                )
            )
            resp = console.input(f"\n  [dim]{T('continue_prompt')}[/]")
            if resp.strip().lower() in EXIT_KEYWORDS[current_lang]:
                console.print(f"\n  [bold cyan]{T('session_goodbye')}[/]")
                time.sleep(0.5)
                break
        except KeyboardInterrupt:
            console.print("\n[bold red]Interrumpido por el usuario.[/]")
        except Exception as exc:
            console.print(f"\n[bold red]Error durante el borrado: {exc}[/]")

        console.print()
        _print_session_hints()


# ─── Windows context-menu installer ──────────────────────────────────────────


def install_context_menu() -> None:
    """Register MadaraMaster in the Windows Explorer right-click menu.

    Requires the script to be run as Administrator (writes to
    ``HKEY_CLASSES_ROOT``).  Prints a diagnostic message and exits if the
    platform is not Windows or if privileges are insufficient.
    """
    if sys.platform != "win32":
        print("Error: solo disponible en Windows.")
        return

    import winreg

    try:
        key_path = r"*\shell\MadaraMaster"
        command_path = key_path + r"\command"
        script_path = os.path.abspath(__file__)
        cmd = f'"{sys.executable}" "{script_path}" wipe "%1"'

        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Wipe with MadaraMaster")
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, sys.executable)
        winreg.CloseKey(key)

        cmd_key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, command_path)
        winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(cmd_key)

        print("✔ Menú contextual instalado correctamente.")
        print(f"  Comando: {cmd}")
    except PermissionError:
        print("Error: ejecuta CMD como Administrador para instalar el menú contextual.")
    except Exception as exc:
        print(f"Error: {exc}")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "install-right-click":
        install_context_menu()
        sys.exit(0)

    if len(sys.argv) <= 1:
        current_lang = select_language()
        interactive_session()
    else:
        app()
