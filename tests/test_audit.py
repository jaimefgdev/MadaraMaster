"""Point 11 — audit log: opt-in hash, private default location, --no-log."""

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import audit
import madara
import wiper_async
from audit import AuditLogger, NullAuditLogger
from conftest import REAL_DEFAULT_LOG_PATH


def _records(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


@pytest.mark.parametrize(
    "platform, env, expected",
    [
        ("linux", {}, ".local/state/madaramaster/audit.jsonl"),
        ("linux", {"XDG_STATE_HOME": "XDG"}, "XDG/madaramaster/audit.jsonl"),
        ("darwin", {}, "Library/Logs/MadaraMaster/audit.jsonl"),
        ("win32", {"LOCALAPPDATA": "LAD"}, "LAD/MadaraMaster/audit.jsonl"),
    ],
)
def test_default_log_path_is_per_user(monkeypatch, tmp_path, platform, env, expected):
    monkeypatch.setattr(audit.sys, "platform", platform)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    for var in ("XDG_STATE_HOME", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, str(tmp_path / v))

    assert REAL_DEFAULT_LOG_PATH() == tmp_path / expected


def test_default_log_is_not_in_the_working_directory():
    assert REAL_DEFAULT_LOG_PATH().parent != Path.cwd()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_log_file_and_directory_are_private(tmp_path):
    log = tmp_path / "state" / "madara" / "audit.jsonl"
    AuditLogger(log).log_wipe_operation(tmp_path / "x", 1, None, "clear", {"success": True})
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert stat.S_IMODE(log.parent.stat().st_mode) == 0o700


async def test_hash_is_not_recorded_by_default(tmp_path, audit_path):
    w = wiper_async.AsyncWiper(AuditLogger(audit_path))
    f = tmp_path / "secret.txt"
    f.write_bytes(b"top secret")
    assert (await w.wipe_file(f))["success"]
    assert _records(audit_path)[-1]["sha256_before"] is None


async def test_hash_is_recorded_when_requested(tmp_path, audit_path):
    w = wiper_async.AsyncWiper(AuditLogger(audit_path), hash_before=True)
    f = tmp_path / "secret.txt"
    f.write_bytes(b"top secret")
    assert (await w.wipe_file(f))["success"]
    assert _records(audit_path)[-1]["sha256_before"] == hashlib.sha256(b"top secret").hexdigest()


async def test_null_logger_writes_nothing(tmp_path):
    w = wiper_async.AsyncWiper(NullAuditLogger())
    f = tmp_path / "secret.txt"
    f.write_bytes(b"x")
    assert (await w.wipe_file(f))["success"]
    assert list(tmp_path.rglob("*.jsonl")) == []


def _wipe_cli(*args):
    return CliRunner().invoke(madara.app, ["wipe", *args])


def test_cli_default_log_goes_to_user_location(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"a")
    res = _wipe_cli(str(f), "-y")
    assert res.exit_code == 0, res.output
    default = audit.default_log_path()
    assert default.exists()
    assert not (Path.cwd() / "madara_audit.jsonl").exists()
    assert _records(default)[-1]["sha256_before"] is None


def test_cli_hash_flag(tmp_path, audit_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"content")
    res = _wipe_cli(str(f), "-y", "--hash", "-l", str(audit_path))
    assert res.exit_code == 0, res.output
    assert _records(audit_path)[-1]["sha256_before"] == hashlib.sha256(b"content").hexdigest()


def test_cli_no_log_flag(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"a")
    res = _wipe_cli(str(f), "-y", "--no-log")
    assert res.exit_code == 0, res.output
    assert not f.exists()
    assert not audit.default_log_path().exists()
    assert list(tmp_path.rglob("*.jsonl")) == []
    assert os.listdir(tmp_path) == []
