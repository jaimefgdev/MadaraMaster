#!/usr/bin/env python3
# Log de auditoría forense — formato JSON Lines
# jaimefgdev

import getpass
import json
import logging
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional


def default_log_path() -> Path:
    """Return the per-user default location of the audit log.

    The log records file names, so it is kept out of the working directory
    (which may be the very directory being wiped) and in a private
    per-user location instead:

    * Linux/BSD: ``$XDG_STATE_HOME/madaramaster/audit.jsonl``
      (default ``~/.local/state/madaramaster/audit.jsonl``)
    * macOS: ``~/Library/Logs/MadaraMaster/audit.jsonl``
    * Windows: ``%LOCALAPPDATA%\\MadaraMaster\\audit.jsonl``
    """
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return base / "MadaraMaster" / "audit.jsonl"
    if sys.platform == "darwin":
        return home / "Library" / "Logs" / "MadaraMaster" / "audit.jsonl"
    base = Path(os.environ.get("XDG_STATE_HOME") or home / ".local" / "state")
    return base / "madaramaster" / "audit.jsonl"


def _safe_username() -> str:
    """Return the current username without raising in daemon / Docker environments.

    ``os.getlogin()`` raises ``OSError`` when there is no controlling
    terminal (typical in Docker, CI pipelines, or systemd services).
    The function falls back to ``getpass.getuser()`` and finally to
    well-known environment variables.
    """
    try:
        return os.getlogin()
    except OSError:
        pass
    try:
        return getpass.getuser()
    except Exception:
        pass
    return os.environ.get("USER", os.environ.get("USERNAME", "unknown"))


class AuditLogger:
    """Append-only forensic audit logger that writes JSON Lines records.

    Each call to :meth:`log_wipe_operation` appends a single JSON object
    terminated by a newline to the configured log file.  Reading is done
    lazily via :meth:`get_logs` to avoid loading the entire file into RAM.

    The file and its directory are created on first write with owner-only
    permissions (``0600`` / ``0700`` on POSIX).

    Args:
        log_path: Destination file for the audit log.  Defaults to
            :func:`default_log_path`.
    """

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self.log_path = Path(log_path) if log_path is not None else default_log_path()

    def _append(self, line: str) -> None:
        self.log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(line)

    def log_wipe_operation(
        self,
        file_path: Path,
        file_size: int,
        sha256_before: Optional[str],
        standard_used: str,
        result: dict[str, Any],
    ) -> None:
        """Append one JSON record describing a completed wipe operation.

        Args:
            file_path: Absolute path of the file that was wiped.
            file_size: Size of the file in bytes, captured before wiping.
            sha256_before: Hex-encoded SHA-256 digest of the file contents
                before the wipe started, or ``None`` when hashing was not
                requested (``--hash``).  The digest lets anyone who has the
                log confirm what the file contained, so it is opt-in.
            standard_used: Sanitization standard identifier (e.g. ``"clear"``).
            result: Dictionary returned by the wipe engine.  Expected keys:
                ``passes_completed``, ``verified``, ``duration``,
                ``success``, ``error``, ``strategy``.
        """
        try:
            record: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "file": str(file_path.absolute()),
                "size_bytes": file_size,
                "sha256_before": sha256_before,
                "standard": standard_used,
                "passes": result.get("passes_completed", 0),
                "verified": result.get("verified", False),
                "duration_sec": result.get("duration", 0.0),
                "user": _safe_username(),
                "hostname": socket.gethostname(),
                "success": result.get("success", False),
                "error": result.get("error"),
                "strategy": result.get("strategy", "Unknown"),
                "final_path": result.get("final_path"),
            }
            self._append(json.dumps(record) + "\n")
        except Exception as exc:
            logging.error("Could not write to the audit log: %s", exc)

    def get_logs(self) -> Generator[dict[str, Any], None, None]:
        """Yield parsed log records one at a time.

        Reads the log file lazily so arbitrarily large audit logs can be
        processed without exhausting available memory.

        Yields:
            One dictionary per valid JSON line in the log file.
        """
        if not self.log_path.exists():
            return
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


class NullAuditLogger(AuditLogger):
    """Audit logger that records nothing (``--no-log``)."""

    def __init__(self) -> None:
        self.log_path = None  # type: ignore[assignment]

    def log_wipe_operation(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_logs(self) -> Generator[dict[str, Any], None, None]:
        return
        yield
