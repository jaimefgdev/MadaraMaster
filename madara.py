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
import os
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from storage import SanitizationStandard
from utils import format_bytes
from wiper import (
    DOD_PASSES,
    WipeResult,
    WipeSummary,
    WipeTelemetry,
    collect_files,
    wipe_directory,
    wipe_file,
)
from wiper_async import AsyncWiper

app = typer.Typer(
    name="madaramaster",
    help="🧹 MadaraMaster — Sanitización Segura de Archivos DoD 5220.22-M",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()
VERSION = "4.0.0"

# diccionario de traducciones EN/ES
LANG = {
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
        "warning_body": "All targeted files will be overwritten 3 times and permanently deleted.\n[bold]Data CANNOT be recovered after this operation.[/]",
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
        "warning_body": "Todos los archivos serán sobrescritos 3 veces y eliminados permanentemente.\n[bold]Los datos NO se podrán recuperar tras esta operación.[/]",
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
    },
}

current_lang = "EN"

EXIT_KEYWORDS = {
    "EN": frozenset(["exit", "close", "quit"]),
    "ES": frozenset(["salir", "cerrar"]),
}

CONFIRM_YES = frozenset(["y", "yes", "s", "si"])


def T(key: str, **kwargs) -> str:
    text = LANG[current_lang].get(key, key)
    return text.format(**kwargs) if kwargs else text


def confirm_action() -> bool:
    answer = input(T("confirm_msg")).lower().strip()
    return answer in CONFIRM_YES


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


def print_banner():
    console.print(
        Panel(
            Align.center(Text(BANNER, style="bold red")),
            border_style="bright_cyan",
            box=box.DOUBLE_EDGE,
            subtitle=f"[dim]DoD 5220.22-M Compliant · v{VERSION}[/]",
        )
    )


def select_language() -> str:
    while True:
        choice = input("Select Language / Seleccione Idioma [1: EN | 2: ES]: ").strip()
        if choice in ("", "1"):
            return "EN"
        if choice == "2":
            return "ES"


def print_summary(summary: WipeSummary):
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
    table.add_row(T("total_overwritten"), f"[bright_yellow]{total:,}[/] [dim]({format_bytes(total)})[/]")
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
        console.print(Panel(content, title=f"[bold red]{T('errors_title')}[/]", border_style="red", box=box.ROUNDED))

    console.print()
    if summary.files_failed == 0 and summary.files_wiped > 0:
        key = "all_sanitized_one" if summary.files_wiped == 1 else "all_sanitized_many"
        console.print(Panel(Align.center(Text(T(key, n=summary.files_wiped), style="bold bright_green")), border_style="bright_green", box=box.DOUBLE_EDGE, padding=(1, 4)))
    elif summary.files_wiped > 0:
        console.print(Panel(Align.center(Text(T("partial_wipe", wiped=summary.files_wiped, failed=summary.files_failed), style="bold bright_yellow")), border_style="yellow", box=box.DOUBLE_EDGE, padding=(1, 4)))
    else:
        console.print(Panel(Align.center(Text(T("no_files_wiped"), style="bold bright_red")), border_style="red", box=box.DOUBLE_EDGE, padding=(1, 4)))


# media móvil de velocidad de escritura en una ventana de 2 segundos
class SpeedTracker:
    def __init__(self, window_seconds: float = 2.0):
        self._window = window_seconds
        self._samples: collections.deque = collections.deque()

    def record(self, bytes_written: int, timestamp: float = None):
        ts = timestamp or time.time()
        self._samples.append((ts, bytes_written))
        cutoff = ts - self._window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def get_speed(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        oldest_ts, oldest_bytes = self._samples[0]
        newest_ts, newest_bytes = self._samples[-1]
        dt = newest_ts - oldest_ts
        return (newest_bytes - oldest_bytes) / dt if dt > 0 else 0.0


def _build_dashboard(telemetry: WipeTelemetry, speed_tracker: SpeedTracker, file_index: int, total_files: int) -> Panel:
    header = Text(T("dash_header"), style="bold bright_cyan")

    basename = os.path.basename(telemetry.current_file) if telemetry.current_file else "—"
    display_name = basename[:45] + "…" if len(basename) > 45 else basename

    if telemetry.current_pass > 0:
        status_text = T(f"dash_pass_{telemetry.current_pass}")
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
        info_table.add_row(T("dash_file_counter"), f"[bright_magenta]{file_index}/{total_files}[/]")

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
    metrics_table.add_row(T("dash_progress"), Group(bar, Text(f" {progress_pct:.1f}%", style="bold bright_green")))
    metrics_table.add_row(T("dash_speed"), Text(f"{format_bytes(int(speed))}/s" if speed > 0 else "—", style="bold bright_yellow"))
    metrics_table.add_row(T("dash_written"), Text(f"{format_bytes(telemetry.bytes_written_total)} / {format_bytes(total_target)}", style="bold bright_magenta"))

    inner = Group(
        Align.center(header),
        Text(""),
        Panel(info_table, border_style="dim cyan", box=box.ROUNDED, padding=(0, 1)),
        Text(""),
        Panel(metrics_table, border_style="dim cyan", box=box.ROUNDED, padding=(0, 1)),
    )
    return Panel(inner, border_style="bright_cyan", box=box.HEAVY, padding=(1, 2))


def _print_completion_panel():
    console.print()
    console.print(Panel(Align.center(Text(T("completion_msg"), style="bold bright_green on black")), border_style="bright_green", box=box.DOUBLE_EDGE, padding=(1, 4)))
    console.print()


async def async_wipe_logic(
    files: list[str],
    standard: SanitizationStandard = SanitizationStandard.NIST_CLEAR,
    verify: bool = False,
    log_path: Optional[str] = None,
) -> WipeSummary:
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
                file_size = file_path_obj.stat().st_size if file_path_obj.exists() else 0
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

            async def progress_callback(p, pass_num, bytes_in_pass, total):
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


@app.command()
def wipe(
    target: str = typer.Argument(..., help="Ruta al archivo o directorio a borrar"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Saltar confirmación"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Vista previa sin borrar"),
    standard: str = typer.Option("clear", "--standard", "-s", help="Estándar: clear, purge, dod"),
    verify: bool = typer.Option(False, "--verify", "-v", help="Verificar con entropía Shannon"),
    log_path: Optional[str] = typer.Option(None, "--log-path", "-l", help="Ruta personalizada para el log"),
):
    """🧹 Borrado seguro con motor Async (NIST SP 800-88 / DoD 5220.22-M)."""
    print_banner()
    target = os.path.abspath(target)

    std_map = {
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

    if not os.path.exists(target):
        console.print(f"\n  [bold red]{T('target_not_found')}[/] {target}")
        raise typer.Exit(code=1)

    files = collect_files(target)
    if not files:
        console.print(f"\n  [bold yellow]{T('no_files_found')}[/] {target}")
        raise typer.Exit(code=0)

    total_size = sum(os.path.getsize(f) for f in files if os.path.exists(f))
    is_dir = os.path.isdir(target)

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

    if dry_run:
        console.print(f"\n  [bold yellow]{T('dry_run_title')}[/]\n")
        for f in files[:50]:
            size = os.path.getsize(f) if os.path.exists(f) else 0
            console.print(f"    [dim]•[/] {f} [dim]({format_bytes(size)})[/]")
        if len(files) > 50:
            console.print(f"    [dim]{T('more_files', n=len(files) - 50)}[/]")
        raise typer.Exit(code=0)

    if not confirm:
        console.print()
        console.print(Panel(f"[bold red]{T('warning_title')}[/]\n\n{T('warning_body')}", border_style="bright_red", box=box.DOUBLE_EDGE, padding=(1, 2)))
        console.print()
        if not typer.confirm(T("confirm_prompt"), default=False):
            console.print(f"\n  [bold cyan]{T('op_cancelled')}[/]")
            raise typer.Exit(code=0)

    console.print()

    try:
        summary = asyncio.run(async_wipe_logic(files, standard=std_enum, verify=verify, log_path=log_path))
    except KeyboardInterrupt:
        console.print("\n[bold red]Interrumpido por el usuario.[/]")
        raise typer.Exit(1)

    # limpiar directorios vacíos si el objetivo era un directorio
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


@app.command()
def version():
    """Muestra la versión de MadaraMaster."""
    print_banner()
    console.print(f"\n  MadaraMaster v{VERSION}")
    console.print(f"  {T('version_desc')}")
    console.print(f"  {T('version_license')}\n")


def _parse_multi_paths(raw: str) -> list[str]:
    # parsea una entrada con una o más rutas, con o sin comillas
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
                paths.append(raw[i + 1:].strip())
                break
            paths.append(raw[i + 1:end])
            i = end + 1
        else:
            end = i
            while end < len(raw) and raw[end] not in (" ", "\t", '"', "'"):
                end += 1
            paths.append(raw[i:end].strip())
            i = end

    return [p for p in paths if p]


def _print_file_preview(targets: list[str]):
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

    table.add_row("", f"[bold]{T('preview_total')}[/]", f"[bold bright_green]{format_bytes(total_size)}[/]", "")
    console.print()
    console.print(table)
    console.print()


def _print_session_hints():
    hint = T("session_hint")
    if hint:
        console.print(f"  {hint}")
    console.print(f"  [dim]{T('session_exit_hint')}[/]\n")


def interactive_session():
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
            console.print(Panel(Align.center(f"[bold bright_green]✅ {T('completion_msg')}[/]"), border_style="green", padding=(1, 2)))
            resp = console.input(f"\n  [dim]{T('continue_prompt')}[/]")
            if resp.strip().lower() in EXIT_KEYWORDS[current_lang]:
                console.print(f"\n  [bold cyan]{T('session_goodbye')}[/]")
                time.sleep(0.5)
                break
        except KeyboardInterrupt:
            console.print("\n[bold red]Interrumpido por el usuario.[/]")
        except Exception as e:
            console.print(f"\n[bold red]Error durante el borrado: {e}[/]")

        console.print()
        _print_session_hints()


def install_context_menu():
    # instala MadaraMaster en el menú contextual de Windows
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
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "install-right-click":
        install_context_menu()
        sys.exit(0)

    if len(sys.argv) <= 1:
        current_lang = select_language()
        interactive_session()
    else:
        app()
