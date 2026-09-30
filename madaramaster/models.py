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
    # Whole batch, planned before the first file is touched, so the global
    # progress runs from 0 % to 100 % once instead of restarting per file.
    batch_files: int = 0
    batch_files_done: int = 0
    batch_total_bytes: int = 0  # sum of file size × passes over the batch
    batch_done_bytes: int = 0  # planned bytes of the files already processed
    batch_written_bytes: int = 0  # bytes actually overwritten in those files
    batch_complete: bool = False  # every file processed: final 100 % frame

    @property
    def total_target_bytes(self) -> int:
        """Bytes the current file needs: its size times its passes."""
        return self.file_size * self.total_passes

    @property
    def current_file_bytes(self) -> int:
        """Progress of the current file, never more than its target."""
        return max(0, min(self.bytes_written_total, self.total_target_bytes))

    @property
    def written_bytes(self) -> int:
        """Bytes written so far: across the batch when there is one."""
        if self.batch_files:
            return self.batch_written_bytes + self.current_file_bytes
        return self.bytes_written_total

    @property
    def target_bytes(self) -> int:
        """Bytes to write in total: across the batch when there is one."""
        return self.batch_total_bytes if self.batch_files else self.total_target_bytes

    @property
    def global_progress(self) -> float:
        """Fraction of the work done, from 0.0 to 1.0 (never goes back)."""
        if self.batch_files:
            if self.batch_total_bytes > 0:
                done = self.batch_done_bytes + self.current_file_bytes
                return min(done / self.batch_total_bytes, 1.0)
            # Only empty files: count files instead of bytes.
            return min(self.batch_files_done / self.batch_files, 1.0)
        target = self.total_target_bytes
        if target <= 0:
            return 1.0 if self.finished else 0.0
        return min(self.bytes_written_total / target, 1.0)
