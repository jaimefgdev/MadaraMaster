"""MadaraMaster command-line interface.

Secure file sanitization with a live dashboard.  Bilingual (EN/ES).

Usage::

    madara                              # interactive session
    madara wipe <PATH>                  # wipe a file or directory
    madara wipe <PATH> --dry-run        # preview without touching anything
    madara wipe-free-space <DIR>        # overwrite the free space of a filesystem
    madara --lang es wipe <PATH>        # Spanish interface (or MADARA_LANG=es)

``python -m madaramaster`` and ``python madara.py`` are equivalent.

The implementation is split by responsibility; this module is the stable
entry point (``madaramaster.cli:main``) and re-exports the names it used
to define:

* :mod:`madaramaster.i18n` — translations and the active language
* :mod:`madaramaster.ui` — console, banner, prompts, summary, dashboard
* :mod:`madaramaster.runner` — shared wipe flow used by every front end
* :mod:`madaramaster.free_space` — free-space fill engine
* :mod:`madaramaster.interactive` — interactive session
* :mod:`madaramaster.commands` — Typer application and commands
"""

from .audit import default_log_path
from .commands import (
    Language,
    Standard,
    _context_menu_command,
    _ensure_utf8_output,
    _global_options,
    app,
    install_context_menu,
    main,
    version,
    wipe,
    wipe_free_space_cmd,
)
from .free_space import (
    _FILL_CHUNK_LARGE,
    _FILL_CHUNK_SMALL,
    _ZEROS_LARGE,
    _ZEROS_SMALL,
    _async_wipe_free_space,
)
from .i18n import CONFIRM_YES, EXIT_KEYWORDS, LANG, T
from .interactive import (
    _confirm_interactive,
    _parse_input_line,
    _print_file_preview,
    _print_session_hints,
    _strip_quotes,
    _target_size,
    interactive_session,
)
from .runner import _FLASH_TYPES, _expand_targets, _remove_empty_dirs, async_wipe_logic
from .trim import send_trim
from .ui import (
    BANNER,
    SpeedTracker,
    _build_dashboard,
    _lsize,
    _print_residue_warning,
    confirm_action,
    print_banner,
    print_summary,
    select_language,
)

__all__ = [
    "BANNER",
    "CONFIRM_YES",
    "EXIT_KEYWORDS",
    "LANG",
    "Language",
    "SpeedTracker",
    "Standard",
    "T",
    "_FILL_CHUNK_LARGE",
    "_FILL_CHUNK_SMALL",
    "_FLASH_TYPES",
    "_ZEROS_LARGE",
    "_ZEROS_SMALL",
    "_async_wipe_free_space",
    "_build_dashboard",
    "_confirm_interactive",
    "_context_menu_command",
    "_ensure_utf8_output",
    "_expand_targets",
    "_global_options",
    "_lsize",
    "_parse_input_line",
    "_print_file_preview",
    "_print_residue_warning",
    "_print_session_hints",
    "_remove_empty_dirs",
    "_strip_quotes",
    "_target_size",
    "app",
    "async_wipe_logic",
    "confirm_action",
    "default_log_path",
    "install_context_menu",
    "interactive_session",
    "main",
    "print_banner",
    "print_summary",
    "select_language",
    "send_trim",
    "version",
    "wipe",
    "wipe_free_space_cmd",
]

if __name__ == "__main__":
    main()
