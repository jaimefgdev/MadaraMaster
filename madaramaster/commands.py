"""Typer application: global options, commands and the console-script entry point."""

import asyncio
import os
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.align import Align
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__, i18n, storage, ui
from .audit import default_log_path
from .free_space import _async_wipe_free_space
from .i18n import T
from .interactive import interactive_session
from .runner import _expand_targets, _remove_empty_dirs, async_wipe_logic
from .safety import find_danger
from .storage import SanitizationStandard, StorageType
from .ui import _lsize, _print_residue_warning, print_banner, print_summary, select_language
from .utils import format_bytes

# ─── Application ─────────────────────────────────────────────────────────────

app = typer.Typer(
    name="madara",
    help="🧹 MadaraMaster — secure file sanitization (NIST SP 800-88 / DoD 5220.22-M patterns).",
    add_completion=False,
    no_args_is_help=True,
)


class Standard(str, Enum):
    """Values accepted by ``--standard``."""

    clear = "clear"
    purge = "purge"
    dod = "dod"


class Language(str, Enum):
    """Values accepted by ``--lang``."""

    en = "en"
    es = "es"


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
    if lang is not None:
        i18n.current_lang = lang.value.upper()



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
        ui.console.print(f"\n  [bold red]{T('target_not_found')}[/] {target}")
        raise typer.Exit(code=1)

    danger = find_danger(target)
    if danger and not allow_dangerous_target:
        ui.console.print(f"\n  [bold red]{T('dangerous_target')}[/] {danger}")
        ui.console.print(f"  [dim]{T('dangerous_target_hint')}[/]")
        raise typer.Exit(code=2)

    files, dirs, _ = _expand_targets([target], allow_dangerous=True)
    if not files:
        ui.console.print(f"\n  [bold yellow]{T('no_files_found')}[/] {target}")
        raise typer.Exit(code=0)

    total_size = sum(_lsize(f) for f in files)
    is_dir = os.path.isdir(target) and not os.path.islink(target)

    ui.console.print()
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
    ui.console.print(info_table)

    if std_enum == SanitizationStandard.NIST_PURGE:
        ui.console.print(f"  [dim]{T('purge_forces_verify')}[/]")

    if std_enum != SanitizationStandard.NIST_CLEAR:
        if storage.detect_storage_type(Path(target)) in (StorageType.SSD, StorageType.NVME):
            ui.console.print()
            ui.console.print(
                Panel(
                    T("ssd_purge_warning"), border_style="yellow", box=box.ROUNDED, padding=(1, 2)
                )
            )

    _print_residue_warning([target])

    if dry_run:
        ui.console.print(f"\n  [bold yellow]{T('dry_run_title')}[/]\n")
        for f in files[:50]:
            size = _lsize(f)
            ui.console.print(f"    [dim]•[/] {f} [dim]({format_bytes(size)})[/]")
        if len(files) > 50:
            ui.console.print(f"    [dim]{T('more_files', n=len(files) - 50)}[/]")
        raise typer.Exit(code=0)

    if not confirm:
        ui.console.print()
        ui.console.print(
            Panel(
                f"[bold red]{T('warning_title')}[/]\n\n{T('warning_body')}",
                border_style="bright_red",
                box=box.DOUBLE_EDGE,
                padding=(1, 2),
            )
        )
        ui.console.print()
        if is_dir:
            expected = os.path.basename(target)
            typed = typer.prompt(T("confirm_type_name", name=expected), default="")
            confirmed = typed.strip() == expected
        else:
            confirmed = typer.confirm(T("confirm_prompt"), default=False)
        if not confirmed:
            ui.console.print(f"\n  [bold cyan]{T('op_cancelled')}[/]")
            raise typer.Exit(code=0)

    ui.console.print()

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
        ui.console.print(f"\n[bold red]{T('interrupted')}[/]")
        raise typer.Exit(1) from None

    _remove_empty_dirs(dirs)
    print_summary(summary)

    if summary.files_failed or not summary.files_wiped:
        raise typer.Exit(code=1)


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
        ui.console.print(f"\n  [bold red]{T('target_not_found')}[/] {target_dir}")
        raise typer.Exit(code=1)

    try:
        sv = os.statvfs(target_dir) if hasattr(os, "statvfs") else None
        free_b: Optional[int] = (sv.f_bavail * sv.f_frsize) if sv else None
    except OSError:
        free_b = None

    storage_type = storage.detect_storage_type(target_dir)

    ui.console.print()
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
    ui.console.print(info)

    if dry_run:
        ui.console.print(f"\n  [bold yellow]{T('wfs_dry')}[/] {target_dir}")
        raise typer.Exit(code=0)

    if not confirm:
        ui.console.print()
        ui.console.print(
            Panel(
                f"[bold yellow]{T('wfs_hint')}[/]\n\n[dim]{T('wfs_full_note')}[/]",
                border_style="yellow",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        ui.console.print()
        if not typer.confirm(T("confirm_prompt"), default=False):
            ui.console.print(f"\n  [bold cyan]{T('op_cancelled')}[/]")
            raise typer.Exit(code=0)

    ui.console.print()

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
            console=ui.console,
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
        ui.console.print(f"\n[bold red]{T('interrupted')}[/]")
        raise typer.Exit(1) from None

    ui.console.print()
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
        ui.console.print(t)
        ui.console.print()
        ui.console.print(
            Panel(
                Align.center(Text(T("wfs_done"), style="bold bright_green")),
                border_style="bright_green",
                box=box.DOUBLE_EDGE,
                padding=(1, 4),
            )
        )
    else:
        ui.console.print(
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
    ui.console.print(f"\n  MadaraMaster v{__version__}")
    ui.console.print(f"  {T('version_desc')}")
    ui.console.print(f"  {T('version_license')}\n")


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
        ui.console.print(T("ctx_windows_only"))
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
        ui.console.print(T("ctx_error", error=exc))
        raise typer.Exit(code=1) from exc

    ui.console.print(T("ctx_installed"))
    ui.console.print(T("ctx_command", cmd=cmd))


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
    _ensure_utf8_output()
    if len(sys.argv) <= 1:
        i18n.current_lang = select_language()
        interactive_session()
    else:
        app()

