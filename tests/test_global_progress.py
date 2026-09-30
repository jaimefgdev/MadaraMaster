"""Global progress of the live dashboard: once from 0 % to 100 % over the batch.

It used to restart for every file (84 % → 18.5 % when the next file began)
and to show 100 % with "0 B / 0 B" before the first file.  The wipes here
only touch files in pytest's temporary directory.
"""

import os
import re

import pytest
from rich.console import Console

from madaramaster import cli as madara
from madaramaster import i18n, runner
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


def _percent(text: str) -> float:
    return float(re.search(r"(\d+\.\d)%", text).group(1))


@pytest.fixture
def frames(monkeypatch):
    """Every dashboard the runner builds: (progress, written, target, rendered text)."""
    seen = []
    real = runner._build_dashboard

    def spy(telemetry, *args):
        panel = real(telemetry, *args)
        seen.append(
            (telemetry.global_progress, telemetry.written_bytes, telemetry.target_bytes,
             _render(panel))
        )
        return panel

    monkeypatch.setattr(runner, "_build_dashboard", spy)
    return seen


def _make(tmp_path, sizes):
    paths = []
    for i, size in enumerate(sizes):
        p = tmp_path / f"f{i}.bin"
        p.write_bytes(os.urandom(size))
        paths.append(str(p))
    return paths


def _assert_monotonic_0_to_100(frames):
    progress = [f[0] for f in frames]
    assert progress[0] == 0.0
    assert progress[-1] == 1.0
    assert all(b >= a for a, b in zip(progress, progress[1:], strict=False)), progress
    shown = [_percent(f[3]) for f in frames]
    assert shown[0] == 0.0 and shown[-1] == 100.0
    assert all(b >= a for a, b in zip(shown, shown[1:], strict=False)), shown


# ── Model ────────────────────────────────────────────────────────────────────


def test_batch_starts_at_zero_with_the_real_total():
    t = WipeTelemetry(batch_files=2, batch_total_bytes=3 * 3072)
    assert t.global_progress == 0.0
    text = _render(madara._build_dashboard(t, madara.SpeedTracker(), 0, 2))
    assert "0.0%" in text and "100.0%" not in text
    assert "0 B / 9.0 KB" in text
    assert "0 B / 0 B" not in text


def test_progress_counts_finished_files_plus_the_current_one():
    t = WipeTelemetry(
        batch_files=2, batch_files_done=1, batch_total_bytes=400, batch_done_bytes=300,
        batch_written_bytes=300, file_size=50, total_passes=2, bytes_written_total=50,
    )
    assert t.global_progress == pytest.approx(350 / 400)
    assert t.written_bytes == 350 and t.target_bytes == 400


def test_current_file_never_counts_more_than_its_target():
    # Passes cover whole clusters, so raw counters can exceed size × passes.
    t = WipeTelemetry(batch_files=1, batch_total_bytes=100, file_size=100,
                      total_passes=1, bytes_written_total=4096)
    assert t.global_progress == 1.0
    assert t.written_bytes == 100


def test_nothing_to_do_is_not_reported_as_done():
    assert WipeTelemetry().global_progress == 0.0
    assert WipeTelemetry(batch_files=3).global_progress == 0.0


# ── Runner ───────────────────────────────────────────────────────────────────


async def test_progress_rises_once_over_the_whole_batch(tmp_path, frames, fake_storage):
    fake_storage.return_value = StorageType.HDD
    # Big first, small last: the old per-file progress dropped at each change.
    paths = _make(tmp_path, [3 * 1024 * 1024, 700 * 1024, 411])
    total = sum(os.path.getsize(p) for p in paths)

    summary = await madara.async_wipe_logic(paths, standard=SanitizationStandard.NIST_PURGE)

    assert summary.files_wiped == 3
    passes = 3  # purge on an HDD
    assert all(f[2] == total * passes for f in frames), "the target is the whole batch"
    assert all(0 <= f[1] <= f[2] for f in frames)
    assert frames[-1][1] == total * passes
    _assert_monotonic_0_to_100(frames)
    assert "0 B / 0 B" not in frames[0][3]
    # Several intermediate values, not just 0 % and 100 %.
    assert len({round(f[0], 3) for f in frames}) > 5


async def test_a_failed_file_does_not_push_progress_back(tmp_path, frames, fake_storage):
    fake_storage.return_value = StorageType.HDD
    paths = _make(tmp_path, [256 * 1024, 64 * 1024, 128 * 1024])
    try:
        os.link(paths[1], tmp_path / "second-link.bin")  # refused without --allow-hardlinks
    except (OSError, NotImplementedError):
        pytest.skip("hard links not available")

    summary = await madara.async_wipe_logic(paths, standard=SanitizationStandard.NIST_CLEAR)

    assert summary.files_wiped == 2 and summary.files_failed == 1
    _assert_monotonic_0_to_100(frames)


async def test_batch_of_empty_files_counts_files(tmp_path, frames, fake_storage):
    fake_storage.return_value = StorageType.HDD
    paths = _make(tmp_path, [0, 0])

    summary = await madara.async_wipe_logic(paths, standard=SanitizationStandard.NIST_CLEAR)

    assert summary.files_wiped == 2
    _assert_monotonic_0_to_100(frames)
