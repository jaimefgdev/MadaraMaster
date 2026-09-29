"""Result and telemetry data classes shared by the engine and the CLI."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WipeResult:
    filepath: str
    success: bool
    file_size: int = 0
    bytes_written: int = 0
    error: str = ""
    duration: float = 0.0


@dataclass
class WipeSummary:
    total_files: int = 0
    files_wiped: int = 0
    files_failed: int = 0
    total_bytes_overwritten: int = 0
    total_duration: float = 0.0
    errors: list[str] = field(default_factory=list)
    results: list[WipeResult] = field(default_factory=list)
    trims_sent: int = 0


@dataclass
class WipeTelemetry:
    """Real-time snapshot consumed by the Rich dashboard in :mod:`madaramaster.cli`.

    All fields are updated in-place so the dashboard can read the latest
    state without any shared-memory primitives.
    """

    start_time: float = 0.0
    current_pass: int = 0
    total_passes: int = 1
    bytes_written_total: int = 0
    bytes_written_current_pass: int = 0
    file_size: int = 0
    current_file: str = ""
    finished: bool = False
    pass_patterns: list[str] = field(default_factory=list)
    algorithm: str = ""

    @property
    def total_target_bytes(self) -> int:
        return self.file_size * self.total_passes

    @property
    def global_progress(self) -> float:
        target = self.total_target_bytes
        if target <= 0:
            return 1.0
        return min(self.bytes_written_total / target, 1.0)
