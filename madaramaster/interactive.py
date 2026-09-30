"""Interactive drag-and-drop session."""

import asyncio
import os
import shlex

from rich import box
from rich.table import Table

from . import i18n, ui
from .i18n import EXIT_KEYWORDS, T
from .runner import _expand_targets, _remove_empty_dirs, async_wipe_logic
from .safety import collect_files, find_danger
from .ui import _lsize, _print_residue_warning, confirm_action, print_banner, print_summary
from .utils import format_bytes

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
    ui.console.print()
    ui.console.print(table)
    ui.console.print()


def _print_session_hints() -> None:
    """Print the interactive-session usage hints."""
    hint = T("session_hint")
    if hint:
        ui.console.print(f"  {hint}")
    ui.console.print(f"  [dim]{T('session_exit_hint')}[/]\n")


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
    ui.console.print(f"  [bold cyan]{T('session_title')}[/]\n")
    _print_session_hints()

    while True:
        queued_targets: list[str] = []

        while True:
            try:
                raw = input(T("session_prompt"))
            except (EOFError, KeyboardInterrupt):
                if queued_targets:
                    break
                ui.console.print(f"\n  [bold cyan]{T('session_ended')}[/]")
                return

            line = raw.strip()
            if not line:
                if queued_targets:
                    break
                continue

            if line.lower() in EXIT_KEYWORDS[i18n.current_lang] and not os.path.lexists(line):
                ui.console.print(f"\n  [bold cyan]{T('session_goodbye')}[/]")
                return

            for p in _parse_input_line(raw):
                target = os.path.abspath(p)
                if not os.path.lexists(target):
                    ui.console.print(f"  [bold red]{T('path_not_found')}[/] {target}")
                    continue
                danger = find_danger(target)
                if danger:
                    ui.console.print(f"  [bold red]{T('dangerous_target')}[/] {danger}")
                    ui.console.print(f"  [dim]{T('dangerous_target_interactive')}[/]")
                    continue
                if target in queued_targets:
                    continue

                queued_targets.append(target)
                basename = os.path.basename(target) or target
                ui.console.print(
                    f"  [bright_green]✓[/] [bold]{basename}[/] "
                    f"[dim]({format_bytes(_target_size(target))})[/] — "
                    f"[bright_cyan]{T('queue_count', n=len(queued_targets))}[/]"
                )
            ui.console.print(f"  [dim]{T('queue_hint')}[/]")

        files, dirs, errors = _expand_targets(queued_targets)
        for err in errors:
            ui.console.print(f"  [bold red]{err}[/]")
        if not files:
            ui.console.print(f"  [bold yellow]{T('no_files_found')}[/]\n")
            _print_session_hints()
            continue

        _print_file_preview(queued_targets)
        _print_residue_warning(queued_targets)

        if not _confirm_interactive(has_dirs=bool(dirs)):
            ui.console.print(f"  [bold cyan]{T('op_cancelled')}[/]\n")
            _print_session_hints()
            continue

        try:
            summary = asyncio.run(async_wipe_logic(files))
            _remove_empty_dirs(dirs)
            print_summary(summary)
            resp = ui.console.input(f"\n  [dim]{T('continue_prompt')}[/]")
            if resp.strip().lower() in EXIT_KEYWORDS[i18n.current_lang]:
                ui.console.print(f"\n  [bold cyan]{T('session_goodbye')}[/]")
                break
        except KeyboardInterrupt:
            ui.console.print(f"\n[bold red]{T('interrupted')}[/]")
        except Exception as exc:
            ui.console.print(f"\n[bold red]{T('wipe_error')} {exc}[/]")

        ui.console.print()
        _print_session_hints()
