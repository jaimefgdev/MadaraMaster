"""MadaraMaster command-line interface.

Secure file sanitization with a live dashboard.  Bilingual (EN/ES).

Usage::

    madara                              # interactive session
    madara wipe <PATH>                  # wipe a file or directory
    madara wipe <PATH> --dry-run        # preview without touching anything
    madara wipe-free-space <DIR>        # overwrite the free space of a filesystem
    madara --lang es wipe <PATH>        # Spanish interface (or MADARA_LANG=es)

``python -m madaramaster`` and ``python madara.py`` are equivalent.
"""

import asyncio
import collections
import errno
import os
import shlex
import sys
import time
import uuid
from enum import Enum
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

from . import __version__, residue, storage
from .audit import AuditLogger, NullAuditLogger, default_log_path
from .engine import AsyncWiper
from .models import WipeResult, WipeSummary, WipeTelemetry
from .safety import collect_files, find_danger
from .storage import SanitizationStandard, StorageType
from .trim import send_trim
from .utils import format_bytes

# ─── Application ─────────────────────────────────────────────────────────────

app = typer.Typer(
    name="madara",
    help="🧹 MadaraMaster — secure file sanitization (NIST SP 800-88 / DoD 5220.22-M patterns).",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()


class Standard(str, Enum):
    """Values accepted by ``--standard``."""

    clear = "clear"
    purge = "purge"
    dod = "dod"


class Language(str, Enum):
    """Values accepted by ``--lang``."""

    en = "en"
    es = "es"

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
        "continue_prompt": (
            "Press Enter to start a new wipe session or type [bold]exit[/bold] to quit..."
        ),
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
            "All targeted files will be overwritten (1 to 3 passes depending on the\n"
            "standard and the storage type) and permanently deleted.\n"
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
        "dash_header": "🛡️  MADARA MASTER v{version}",
        "dash_file": "📁 File",
        "dash_algorithm": "🔒 Algorithm",
        "dash_status": "🔄 Status",
        "dash_pass": "Pass {i}/{n} — {pattern}...",
        "pat_zeros": "Overwriting with 0x00 (Zeros)",
        "pat_ones": "Overwriting with 0xFF (Ones)",
        "pat_random": "Overwriting with Random Bytes",
        "dash_algorithm_value": "{standard} · {n} pass(es)",
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
        "all_sanitized_one": "✔ {n} FILE OVERWRITTEN AND DELETED",
        "all_sanitized_many": "✔ {n} FILES OVERWRITTEN AND DELETED",
        "partial_wipe": "⚠ PARTIAL WIPE — {wiped} wiped, {failed} failed",
        "no_files_wiped": "✗ NO FILES WERE WIPED",
        "completion_msg": "DELETION COMPLETED SUCCESSFULLY",
        "wiped": "✔ Wiped",
        "version_desc": "Secure file sanitization (NIST SP 800-88 / DoD 5220.22-M patterns)",
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
        "dangerous_target_interactive": (
            "Protected targets cannot be wiped from the interactive session."
        ),
        "confirm_word": "WIPE",
        "confirm_word_prompt": "Directories are queued. Type {word} to confirm: ",
        "ssd_purge_warning": (
            "The target is on an SSD/NVMe drive. Overwriting files cannot guarantee\n"
            "NIST 800-88 Purge on flash (wear-leveling, over-provisioning).\n"
            "For that, use full-disk encryption or the drive's own secure erase."
        ),
        "purge_forces_verify": "The purge standard always verifies after wiping.",
        "residue_title": "Copies may survive this wipe",
        "residue_cow_fs": (
            "Copy-on-write filesystem (btrfs, ZFS, APFS, ReFS…): overwrites go to new\n"
            "blocks, so the old data can stay on disk."
        ),
        "residue_network": (
            "Network location: the server may keep its own snapshots, caches or backups."
        ),
        "residue_cloud_sync": (
            "Cloud-synced folder (OneDrive, Dropbox, Google Drive, iCloud…): the cloud\n"
            "copy and its version history are not wiped. Delete them there too."
        ),
        "residue_data_journal": (
            "ext3/ext4 mounted with data=journal: file contents may remain in the journal."
        ),
        "residue_hint": "See the README's Limitations section for details.",
        "trims_sent": "TRIM sent",
        "lbl_hash": "Hash before wipe",
        "yes": "Yes",
        "no": "No",
        "interrupted": "Interrupted by the user.",
        "wipe_error": "Error during the wipe:",
        "lbl_storage": "Storage",
        "lbl_free_space": "Free space",
        "wfs_full_note": (
            "The disk will be full for a moment — this is expected.\n"
            "No existing file will be modified."
        ),
        "ctx_windows_only": "Error: only available on Windows.",
        "ctx_installed": "✔ Context-menu entry installed for the current user.",
        "ctx_command": "  Command: {cmd}",
        "ctx_error": "Error: {error}",
        "banner_subtitle": "NIST SP 800-88 · DoD 5220.22-M · v{version}",
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
        "continue_prompt": (
            "Presiona Enter para iniciar una nueva sesión o escribe [bold]salir[/bold] "
            "para salir..."
        ),
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
            "Todos los archivos serán sobrescritos (de 1 a 3 pases según el estándar\n"
            "y el tipo de almacenamiento) y eliminados permanentemente.\n"
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
        "dash_header": "🛡️  MADARA MASTER v{version}",
        "dash_file": "📁 Archivo",
        "dash_algorithm": "🔒 Algoritmo",
        "dash_status": "🔄 Estado",
        "dash_pass": "Pase {i}/{n} — {pattern}...",
        "pat_zeros": "Sobrescribiendo con 0x00 (Ceros)",
        "pat_ones": "Sobrescribiendo con 0xFF (Unos)",
        "pat_random": "Sobrescribiendo con Bytes Aleatorios",
        "dash_algorithm_value": "{standard} · {n} pase(s)",
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
        "all_sanitized_one": "✔ {n} ARCHIVO SOBRESCRITO Y ELIMINADO",
        "all_sanitized_many": "✔ {n} ARCHIVOS SOBRESCRITOS Y ELIMINADOS",
        "partial_wipe": "⚠ BORRADO PARCIAL — {wiped} borrados, {failed} fallidos",
        "no_files_wiped": "✗ NO SE BORRÓ NINGÚN ARCHIVO",
        "completion_msg": "ELIMINACIÓN COMPLETADA CON ÉXITO",
        "wiped": "✔ Borrado",
        "version_desc": "Sanitización segura de archivos (patrones NIST SP 800-88 / DoD 5220.22-M)",
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
        "dangerous_target_interactive": (
            "Los objetivos protegidos no se pueden borrar desde la sesión interactiva."
        ),
        "confirm_word": "BORRAR",
        "confirm_word_prompt": "Hay directorios en la cola. Escribe {word} para confirmar: ",
        "ssd_purge_warning": (
            "El objetivo está en un SSD/NVMe. Sobrescribir ficheros no garantiza\n"
            "NIST 800-88 Purge en flash (wear-leveling, sobreaprovisionamiento).\n"
            "Para eso, usa cifrado de disco completo o el borrado seguro de la unidad."
        ),
        "purge_forces_verify": "El estándar purge siempre verifica tras el borrado.",
        "residue_title": "Pueden quedar copias tras este borrado",
        "residue_cow_fs": (
            "Sistema de archivos copy-on-write (btrfs, ZFS, APFS, ReFS…): lo que se\n"
            "sobrescribe va a bloques nuevos y los datos antiguos pueden seguir en disco."
        ),
        "residue_network": (
            "Ubicación de red: el servidor puede guardar sus propias instantáneas,\n"
            "cachés o copias de seguridad."
        ),
        "residue_cloud_sync": (
            "Carpeta sincronizada con la nube (OneDrive, Dropbox, Google Drive, iCloud…):\n"
            "la copia de la nube y su historial de versiones no se borran. Bórralos allí."
        ),
        "residue_data_journal": (
            "ext3/ext4 montado con data=journal: el contenido puede quedar en el journal."
        ),
        "residue_hint": "Consulta la sección Limitaciones del README para más detalles.",
        "trims_sent": "TRIM enviado",
        "lbl_hash": "Hash previo",
        "yes": "Sí",
        "no": "No",
        "interrupted": "Interrumpido por el usuario.",
        "wipe_error": "Error durante el borrado:",
        "lbl_storage": "Almacenamiento",
        "lbl_free_space": "Espacio libre",
        "wfs_full_note": (
            "El disco quedará momentáneamente lleno — comportamiento esperado.\n"
            "No se modificará ningún archivo existente."
        ),
        "ctx_windows_only": "Error: solo disponible en Windows.",
        "ctx_installed": "✔ Menú contextual instalado para el usuario actual.",
        "ctx_command": "  Comando: {cmd}",
        "ctx_error": "Error: {error}",
        "banner_subtitle": "NIST SP 800-88 · DoD 5220.22-M · v{version}",
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

   MadaraMaster v{version} • Created by jaimefg1888
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

    if telemetry.finished:
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

    telemetry = WipeTelemetry()
    speed_tracker = SpeedTracker(window_seconds=2.0)

    with Live(
        _build_dashboard(telemetry, speed_tracker, 0, len(files)),
        console=console,
        refresh_per_second=12,
        transient=True,
    ) as live:
        for file_idx, filepath in enumerate(files, start=1):
            file_path_obj = Path(filepath)
            try:
                file_size = file_path_obj.lstat().st_size
            except OSError:
                file_size = 0
            try:
                patterns = wiper.plan(file_path_obj, standard)
            except Exception:
                patterns = []

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
                error=result_dict.get("error") or "",
                bytes_written=file_size * result_dict.get("passes_completed", 0),
            )
            summary.results.append(w_res)

            if w_res.success:
                summary.files_wiped += 1
                summary.total_bytes_overwritten += w_res.bytes_written
                telemetry.finished = True
                telemetry.bytes_written_total = w_res.bytes_written
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

    # One TRIM per filesystem for the whole batch, not one per file.
    for directory in trim_targets.values():
        if await asyncio.to_thread(send_trim, directory):
            summary.trims_sent += 1

    summary.total_duration = time.time() - start_time
    return summary


# ─── Typer commands ───────────────────────────────────────────────────────────


@app.callback()
def _global_options(
    lang: Optional[Language] = typer.Option(
        None,
        "--lang",
        envvar="MADARA_LANG",
        case_sensitive=False,
        help="Interface language: en or es (also MADARA_LANG).",
    ),
) -> None:
    """🧹 MadaraMaster — secure file sanitization."""
    global current_lang
    if lang is not None:
        current_lang = lang.value.upper()



@app.command()
def wipe(
    target: str = typer.Argument(..., help="File or directory to wipe."),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip the confirmation prompt."),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="List the targets and exit."),
    standard: Standard = typer.Option(
        Standard.clear, "--standard", "-s", case_sensitive=False, help="Sanitization standard."
    ),
    verify: bool = typer.Option(
        False, "--verify", help="Re-read and compare after wiping (always on with purge)."
    ),
    log_path: Optional[str] = typer.Option(
        None, "--log-path", "-l", help="Custom audit-log path."
    ),
    no_log: bool = typer.Option(False, "--no-log", help="Do not write an audit log."),
    hash_before: bool = typer.Option(
        False,
        "--hash",
        help="Record each file's pre-wipe SHA-256 in the audit log (reveals its content).",
    ),
    trim: bool = typer.Option(
        False, "--trim", help="Send one TRIM per filesystem at the end (SSD/NVMe, Linux)."
    ),
    allow_hardlinks: bool = typer.Option(
        False,
        "--allow-hardlinks",
        help="Also wipe files with several hard links (destroys the data of every name).",
    ),
    allow_dangerous_target: bool = typer.Option(
        False,
        "--allow-dangerous-target",
        help="Allow protected targets: roots, home, system directories, mount points.",
    ),
) -> None:
    """🧹 Overwrite and delete a file or a directory tree."""
    print_banner()
    target = os.path.abspath(target)

    std_enum = SanitizationStandard(standard.value)

    if not os.path.lexists(target):
        console.print(f"\n  [bold red]{T('target_not_found')}[/] {target}")
        raise typer.Exit(code=1)

    danger = find_danger(target)
    if danger and not allow_dangerous_target:
        console.print(f"\n  [bold red]{T('dangerous_target')}[/] {danger}")
        console.print(f"  [dim]{T('dangerous_target_hint')}[/]")
        raise typer.Exit(code=2)

    files, dirs, _ = _expand_targets([target], allow_dangerous=True)
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
    verify = verify or std_enum == SanitizationStandard.NIST_PURGE
    info_table.add_row(T("method"), f"Async Auto-Detect (Standard: {std_enum.value})")
    info_table.add_row(T("lbl_verify"), T("yes") if verify else T("no"))
    info_table.add_row(T("lbl_hash"), T("yes") if hash_before else T("no"))
    if no_log:
        info_table.add_row(T("lbl_audit_log"), "—")
    else:
        info_table.add_row(T("lbl_audit_log"), log_path or str(default_log_path()))
    console.print(info_table)

    if std_enum == SanitizationStandard.NIST_PURGE:
        console.print(f"  [dim]{T('purge_forces_verify')}[/]")

    if std_enum != SanitizationStandard.NIST_CLEAR:
        if storage.detect_storage_type(Path(target)) in (StorageType.SSD, StorageType.NVME):
            console.print()
            console.print(
                Panel(
                    T("ssd_purge_warning"), border_style="yellow", box=box.ROUNDED, padding=(1, 2)
                )
            )

    _print_residue_warning([target])

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
                hash_before=hash_before,
                no_log=no_log,
                trim=trim,
            )
        )
    except KeyboardInterrupt:
        console.print(f"\n[bold red]{T('interrupted')}[/]")
        raise typer.Exit(1) from None

    _remove_empty_dirs(dirs)
    print_summary(summary)

    if summary.files_failed or not summary.files_wiped:
        raise typer.Exit(code=1)


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
        help="Directory on the filesystem whose free space is overwritten (default: current).",
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip the confirmation prompt."),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would be done and exit."
    ),
    no_trim: bool = typer.Option(False, "--no-trim", help="Do not send TRIM afterwards."),
) -> None:
    """🧹 Fill the free space of a filesystem with zeros, then delete the fill file.

    Writes zeros until ENOSPC, fsyncs, removes the fill file and, unless
    ``--no-trim`` is given, sends TRIM (Linux only).
    """
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

    storage_type = storage.detect_storage_type(target_dir)

    console.print()
    info = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    info.add_column("Key", style="bold cyan")
    info.add_column("Value", style="white")
    info.add_row(T("lbl_target"), str(target_dir))
    info.add_row(T("lbl_storage"), storage_type.value.upper())
    info.add_row(T("lbl_free_space"), format_bytes(free_b) if free_b else "—")
    info.add_row(
        T("method"),
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
                f"[bold yellow]{T('wfs_hint')}[/]\n\n[dim]{T('wfs_full_note')}[/]",
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
        console.print(f"\n[bold red]{T('interrupted')}[/]")
        raise typer.Exit(1) from None

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
    console.print(f"\n  MadaraMaster v{__version__}")
    console.print(f"  {T('version_desc')}")
    console.print(f"  {T('version_license')}\n")


# ─── Interactive session ──────────────────────────────────────────────────────


def _strip_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _parse_input_line(raw: str) -> list[str]:
    """Parse a line typed or drag-and-dropped into the interactive session.

    * If the whole line (without surrounding quotes) is an existing path,
      it is taken as a single path, so unquoted names with spaces or
      apostrophes work (``My Documents/it's mine.txt``).
    * Otherwise the line is split like a shell would (:func:`shlex.split`):
      quotes group words and, on POSIX, backslash-escaped spaces (as
      inserted by macOS/Linux terminals on drag-and-drop) are honoured.
      On Windows backslashes are path separators, not escapes.

    Args:
        raw: Raw text as entered by the user.

    Returns:
        A list of non-empty path strings.
    """
    line = raw.strip()
    if not line:
        return []
    whole = _strip_quotes(line)
    if os.path.lexists(whole):
        return [whole]
    try:
        tokens = shlex.split(line, posix=(os.name != "nt"))
    except ValueError:  # unbalanced quotes
        return [whole]
    return [_strip_quotes(t) for t in tokens if t.strip()]


def _target_size(target: str) -> int:
    """Total size of the entries that would be wiped for *target*."""
    return sum(_lsize(f) for f in collect_files(target))


def _print_file_preview(targets: list[str]) -> None:
    """Render a Rich table previewing the targets queued for wiping.

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
        entries = collect_files(target)
        size = sum(_lsize(f) for f in entries)
        if os.path.isdir(target) and not os.path.islink(target):
            type_str = f"📁 {T('type_dir')}"
            name_str = f"{name}/ [dim]({len(entries)} files)[/]"
        else:
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


def _confirm_interactive(has_dirs: bool) -> bool:
    """Ask for confirmation; directories require typing a confirmation word."""
    if has_dirs:
        word = T("confirm_word")
        return input(T("confirm_word_prompt", word=word)).strip() == word
    return confirm_action()


def interactive_session() -> None:
    """Run the interactive drag-and-drop wipe session.

    Prompts the user to enter or drag file paths, builds a queue, previews
    it, then triggers the async wipe engine through the same target
    expansion as the ``wipe`` command (protected targets refused, links
    never followed, directories expanded and removed once empty).  Loops
    until the user types an exit keyword.
    """
    print_banner()
    console.print(f"  [bold cyan]{T('session_title')}[/]\n")
    _print_session_hints()

    while True:
        queued_targets: list[str] = []

        while True:
            try:
                raw = input(T("session_prompt"))
            except (EOFError, KeyboardInterrupt):
                if queued_targets:
                    break
                console.print(f"\n  [bold cyan]{T('session_ended')}[/]")
                return

            line = raw.strip()
            if not line:
                if queued_targets:
                    break
                continue

            if line.lower() in EXIT_KEYWORDS[current_lang] and not os.path.lexists(line):
                console.print(f"\n  [bold cyan]{T('session_goodbye')}[/]")
                return

            for p in _parse_input_line(raw):
                target = os.path.abspath(p)
                if not os.path.lexists(target):
                    console.print(f"  [bold red]{T('path_not_found')}[/] {target}")
                    continue
                danger = find_danger(target)
                if danger:
                    console.print(f"  [bold red]{T('dangerous_target')}[/] {danger}")
                    console.print(f"  [dim]{T('dangerous_target_interactive')}[/]")
                    continue
                if target in queued_targets:
                    continue

                queued_targets.append(target)
                basename = os.path.basename(target) or target
                console.print(
                    f"  [bright_green]✓[/] [bold]{basename}[/] "
                    f"[dim]({format_bytes(_target_size(target))})[/] — "
                    f"[bright_cyan]{T('queue_count', n=len(queued_targets))}[/]"
                )
            console.print(f"  [dim]{T('queue_hint')}[/]")

        files, dirs, errors = _expand_targets(queued_targets)
        for err in errors:
            console.print(f"  [bold red]{err}[/]")
        if not files:
            console.print(f"  [bold yellow]{T('no_files_found')}[/]\n")
            _print_session_hints()
            continue

        _print_file_preview(queued_targets)
        _print_residue_warning(queued_targets)

        if not _confirm_interactive(has_dirs=bool(dirs)):
            console.print(f"  [bold cyan]{T('op_cancelled')}[/]\n")
            _print_session_hints()
            continue

        try:
            summary = asyncio.run(async_wipe_logic(files))
            _remove_empty_dirs(dirs)
            print_summary(summary)
            resp = console.input(f"\n  [dim]{T('continue_prompt')}[/]")
            if resp.strip().lower() in EXIT_KEYWORDS[current_lang]:
                console.print(f"\n  [bold cyan]{T('session_goodbye')}[/]")
                break
        except KeyboardInterrupt:
            console.print(f"\n[bold red]{T('interrupted')}[/]")
        except Exception as exc:
            console.print(f"\n[bold red]{T('wipe_error')} {exc}[/]")

        console.print()
        _print_session_hints()


# ─── Windows context-menu installer ──────────────────────────────────────────


def _context_menu_command() -> str:
    """Command line registered in the Explorer context menu.

    A PyInstaller build (``sys.frozen``) is its own executable; otherwise
    the running interpreter launches the installed package with ``-m``.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" wipe "%1"'
    return f'"{sys.executable}" -m madaramaster wipe "%1"'


@app.command("install-right-click")
def install_context_menu() -> None:
    """🪟 Add "Wipe with MadaraMaster" to the Explorer right-click menu (Windows).

    The entry is registered for the current user only
    (``HKCU\\Software\\Classes``), so no administrator rights are needed.
    The wipe still asks for confirmation.
    """
    if sys.platform != "win32":
        console.print(T("ctx_windows_only"))
        raise typer.Exit(code=1)

    import winreg

    key_path = r"Software\Classes\*\shell\MadaraMaster"
    cmd = _context_menu_command()
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Wipe with MadaraMaster")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, sys.executable)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path + r"\command") as cmd_key:
            winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, cmd)
    except OSError as exc:
        console.print(T("ctx_error", error=exc))
        raise typer.Exit(code=1) from exc

    console.print(T("ctx_installed"))
    console.print(T("ctx_command", cmd=cmd))


# ─── Entry point ─────────────────────────────────────────────────────────────


def _ensure_utf8_output() -> None:
    """Make redirected output able to carry the banner and box-drawing characters.

    When stdout/stderr go to a pipe or a file, Python uses the locale
    encoding (cp1252 on most Windows setups), and printing the banner raised
    ``UnicodeEncodeError``.  Interactive consoles already report UTF-8, so
    they are left untouched.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main() -> None:
    """Console-script entry point: interactive session without arguments."""
    global current_lang
    _ensure_utf8_output()
    if len(sys.argv) <= 1:
        current_lang = select_language()
        interactive_session()
    else:
        app()


if __name__ == "__main__":
    main()
