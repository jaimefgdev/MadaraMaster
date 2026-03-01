#!/usr/bin/env python3
# Log de auditoría forense — formato JSON Lines
# jaimefg1888

import json
import logging
import os
import getpass
import socket
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any


def _safe_username() -> str:
    """os.getlogin() raises OSError in Docker and daemon environments."""
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
    def __init__(self, log_path: Path = Path("madara_audit.jsonl")):
        self.log_path = log_path

    def log_wipe_operation(self, file_path: Path, file_size: int, sha256_before: str, standard_used: str, result: Dict[str, Any]):
        try:
            record = {
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
            }
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logging.error(f"No se pudo escribir en el log de auditoría: {e}")

    def get_logs(self):
        # generador para no cargar todo el fichero en memoria de golpe
        if not self.log_path.exists():
            return
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
