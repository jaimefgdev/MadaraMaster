"""Points 12 and 13 — truthful messages and exit codes; purge verifies, SSD warning."""

import os

import pytest
from rich.console import Console
from typer.testing import CliRunner

from madaramaster import cli as madara
from madaramaster import i18n, runner, ui
from madaramaster.models import WipeTelemetry
from madaramaster.storage import SanitizationStandard, StorageType


@pytest.fixture(autouse=True)
def english():
    i18n.current_lang = "EN"
    yield
    i18n.current_lang = "EN"


def _render(renderable) -> str:
    con = Console(record=True, width=140, color_system=None)
    con.print(renderable)
    return con.export_text()


# ── Point 12 ─────────────────────────────────────────────────────────────────


def test_dashboard_shows_the_real_number_of_passes():
    t = WipeTelemetry(
        current_pass=1,
        total_passes=1,
        pass_patterns=["random"],
        algorithm="clear · 1 pass(es)",
        file_size=100,
        bytes_written_total=50,
        current_file="f.bin",
    )
    text = _render(madara._build_dashboard(t, madara.SpeedTracker(), 1, 1))
    assert "Pass 1/1" in text
    assert "Random" in text
    assert "3 Passes" not in text and "1/3" not in text
    assert "clear · 1 pass(es)" in text


def test_single_pass_progress_reaches_100_percent():
    t = WipeTelemetry(total_passes=1, file_size=100, bytes_written_total=100)
    assert t.global_progress == 1.0


def test_warning_does_not_promise_three_passes():
    assert "3 times" not in madara.LANG["EN"]["warning_body"]
    assert "3 veces" not in madara.LANG["ES"]["warning_body"]


async def test_dashboard_is_fed_from_the_engine_plan(tmp_path, monkeypatch, fake_storage):
    fake_storage.return_value = StorageType.SSD
    f = tmp_path / "f.bin"
    f.write_bytes(os.urandom(10))
    seen = []
    real = madara._build_dashboard

    def spy(telemetry, *args):
        seen.append((telemetry.total_passes, list(telemetry.pass_patterns)))
        return real(telemetry, *args)

    monkeypatch.setattr(runner, "_build_dashboard", spy)
    summary = await madara.async_wipe_logic([str(f)], standard=SanitizationStandard.DOD_LEGACY)
    assert summary.files_wiped == 1
    assert (1, ["random"]) in seen


def test_cli_exit_code_is_nonzero_when_a_file_fails(tmp_path, audit_path):
    a = tmp_path / "a.txt"
    a.write_bytes(b"x")
    try:
        os.link(a, tmp_path / "b.txt")  # refused without --allow-hardlinks
    except (OSError, NotImplementedError):
        pytest.skip("hard links not available")
    res = CliRunner().invoke(madara.app, ["wipe", str(a), "-y", "-l", str(audit_path)])
    assert res.exit_code == 1, res.output
    assert "COMPLETED SUCCESSFULLY" not in res.output
    assert "NO FILES WERE WIPED" in res.output


def test_cli_exit_code_is_zero_on_success(tmp_path, audit_path):
    a = tmp_path / "a.txt"
    a.write_bytes(b"x")
    res = CliRunner().invoke(madara.app, ["wipe", str(a), "-y", "-l", str(audit_path)])
    assert res.exit_code == 0, res.output
    assert not a.exists()


def test_interactive_reports_the_real_outcome(tmp_path, monkeypatch):
    """The interactive session used to print 'COMPLETED SUCCESSFULLY' unconditionally."""
    a = tmp_path / "a.txt"
    a.write_bytes(b"x")
    try:
        os.link(a, tmp_path / "b.txt")
    except (OSError, NotImplementedError):
        pytest.skip("hard links not available")
    lines = iter([str(a), "", "y", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    con = Console(record=True, width=140, color_system=None)
    monkeypatch.setattr(ui, "console", con)

    madara.interactive_session()

    out = con.export_text()
    assert "COMPLETED SUCCESSFULLY" not in out
    assert "NO FILES WERE WIPED" in out
    assert a.exists()


# ── Point 13 ─────────────────────────────────────────────────────────────────


async def test_purge_always_verifies(tmp_path, wiper):
    f = tmp_path / "f.bin"
    f.write_bytes(os.urandom(5000))
    result = await wiper.wipe_file(f, SanitizationStandard.NIST_PURGE, verify=False)
    assert result["success"], result["error"]
    assert result["verified"] is True


async def test_clear_does_not_verify_unless_asked(tmp_path, wiper):
    f = tmp_path / "f.bin"
    f.write_bytes(os.urandom(5000))
    result = await wiper.wipe_file(f, SanitizationStandard.NIST_CLEAR)
    assert result["verified"] is None


def test_cli_purge_shows_verify_on(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    res = CliRunner().invoke(madara.app, ["wipe", str(f), "--dry-run", "-s", "purge"])
    assert res.exit_code == 0, res.output
    assert "always verifies" in res.output
    assert "Verify            Yes" in res.output or "Yes" in res.output.split("Verify", 1)[1][:40]


@pytest.mark.parametrize(
    "storage_type, standard, warned",
    [
        (StorageType.SSD, "purge", True),
        (StorageType.NVME, "dod", True),
        (StorageType.SSD, "clear", False),
        (StorageType.HDD, "purge", False),
    ],
)
def test_ssd_purge_warning(tmp_path, fake_storage, storage_type, standard, warned):
    fake_storage.return_value = storage_type
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    res = CliRunner().invoke(madara.app, ["wipe", str(f), "--dry-run", "-s", standard])
    assert res.exit_code == 0, res.output
    assert ("cannot guarantee" in res.output) is warned
    assert f.exists()
