#!/usr/bin/env python3
# Motor de borrado síncrono — DoD 5220.22-M
# jaimefg1888
#
# Tres pases:
#   1. Ceros    (\x00)
#   2. Unos     (\xFF)
#   3. Aleatorio (os.urandom)
#
# Antes de eliminar: renombra el fichero y resetea timestamps
# para que las herramientas de carving no encuentren el inodo original.

import os
import sys
import time
import stat
import string
import random
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable, List

CHUNK_SIZE = 256 * 1024  # 256 KB — reduces syscall overhead on large files
DOD_PASSES = 3


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
    errors: List[str] = field(default_factory=list)
    results: List[WipeResult] = field(default_factory=list)


@dataclass
class WipeTelemetry:
    # snapshot en tiempo real que madara.py usa para actualizar el dashboard
    start_time: float = 0.0
    current_pass: int = 0
    total_passes: int = DOD_PASSES
    bytes_written_total: int = 0
    bytes_written_current_pass: int = 0
    file_size: int = 0
    current_file: str = ""
    finished: bool = False

    @property
    def total_target_bytes(self) -> int:
        return self.file_size * self.total_passes

    @property
    def global_progress(self) -> float:
        target = self.total_target_bytes
        if target <= 0:
            return 1.0
        return min(self.bytes_written_total / target, 1.0)


ProgressCallback = Optional[Callable[[str, int, int, int], None]]


def _overwrite_pass(fd: int, file_size: int, pass_number: int, filepath: str, progress_callback: ProgressCallback = None) -> int:
    os.lseek(fd, 0, os.SEEK_SET)
    bytes_written = 0
    remaining = file_size

    while remaining > 0:
        chunk_len = min(CHUNK_SIZE, remaining)
        if pass_number == 1:
            data = b"\x00" * chunk_len
        elif pass_number == 2:
            data = b"\xFF" * chunk_len
        else:
            data = os.urandom(chunk_len)

        os.write(fd, data)
        bytes_written += chunk_len
        remaining -= chunk_len

        if progress_callback:
            progress_callback(filepath, pass_number, bytes_written, file_size)

    os.fsync(fd)
    return bytes_written


def _scrub_metadata(filepath: str) -> str:
    # epoch 0 para que Autopsy/Sleuth no tenga timestamps útiles
    try:
        os.utime(filepath, (0, 0))
    except OSError:
        pass

    directory = os.path.dirname(filepath) or "."
    random_name = "".join(random.choices(string.ascii_lowercase + string.digits, k=12)) + ".tmp"
    new_path = os.path.join(directory, random_name)

    try:
        os.rename(filepath, new_path)
        return new_path
    except OSError:
        return filepath


def _ensure_writable(filepath: str) -> None:
    try:
        mode = os.stat(filepath).st_mode
        if not (mode & stat.S_IWRITE):
            os.chmod(filepath, mode | stat.S_IWRITE)
    except OSError:
        pass


def wipe_file(filepath: str, progress_callback: ProgressCallback = None) -> WipeResult:
    start_time = time.time()
    filepath = os.path.abspath(filepath)

    if not os.path.isfile(filepath):
        return WipeResult(filepath=filepath, success=False, error=f"Archivo no encontrado: {filepath}")

    _ensure_writable(filepath)

    try:
        file_size = os.path.getsize(filepath)
        total_bytes_written = 0

        if file_size == 0:
            final_path = _scrub_metadata(filepath)
            os.remove(final_path)
            return WipeResult(filepath=filepath, success=True, file_size=0, duration=time.time() - start_time)

        flags = os.O_WRONLY | (os.O_BINARY if sys.platform == "win32" else 0)
        fd = os.open(filepath, flags)

        try:
            for pass_num in range(1, DOD_PASSES + 1):
                total_bytes_written += _overwrite_pass(fd, file_size, pass_num, filepath, progress_callback)
        finally:
            os.close(fd)

        final_path = _scrub_metadata(filepath)
        os.remove(final_path)

        return WipeResult(
            filepath=filepath,
            success=True,
            file_size=file_size,
            bytes_written=total_bytes_written,
            duration=time.time() - start_time,
        )

    except PermissionError as e:
        return WipeResult(filepath=filepath, success=False, error=f"Permiso denegado: {e}", duration=time.time() - start_time)
    except OSError as e:
        return WipeResult(filepath=filepath, success=False, error=f"Error del sistema: {e}", duration=time.time() - start_time)
    except Exception as e:
        return WipeResult(filepath=filepath, success=False, error=f"Error inesperado: {e}", duration=time.time() - start_time)


def wipe_directory(dirpath: str, progress_callback: ProgressCallback = None) -> WipeSummary:
    summary = WipeSummary()
    start_time = time.time()
    dirpath = os.path.abspath(dirpath)

    if not os.path.isdir(dirpath):
        summary.errors.append(f"Directorio no encontrado: {dirpath}")
        return summary

    all_files = [
        os.path.join(root, filename)
        for root, _, files in os.walk(dirpath, topdown=False)
        for filename in files
    ]
    summary.total_files = len(all_files)

    for filepath in all_files:
        result = wipe_file(filepath, progress_callback)
        summary.results.append(result)
        if result.success:
            summary.files_wiped += 1
            summary.total_bytes_overwritten += result.bytes_written
        else:
            summary.files_failed += 1
            summary.errors.append(f"{result.filepath}: {result.error}")

    # limpiamos directorios vacíos de abajo a arriba; si alguno no se puede borrar lo ignoramos
    for root, dirs, _ in os.walk(dirpath, topdown=False):
        for dirname in dirs:
            try:
                os.rmdir(os.path.join(root, dirname))
            except OSError:
                pass
    try:
        os.rmdir(dirpath)
    except OSError:
        pass

    summary.total_duration = time.time() - start_time
    return summary


def collect_files(target: str) -> List[str]:
    target = os.path.abspath(target)
    if os.path.isfile(target):
        return [target]
    if os.path.isdir(target):
        return [
            os.path.join(root, filename)
            for root, _, filenames in os.walk(target, topdown=False)
            for filename in filenames
        ]
    return []
