#!/usr/bin/env python3
# Motor asíncrono de borrado — v4.0
# jaimefg1888

import asyncio
import hashlib
import math
import os
import random
import stat
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles

from audit import AuditLogger
from storage import SanitizationStandard, StorageType, detect_storage_type


def _ensure_writable(path: Path) -> None:
    """Make the file writable if it is read-only."""
    try:
        mode = path.stat().st_mode
        if not (mode & stat.S_IWRITE):
            os.chmod(path, mode | stat.S_IWRITE)
    except OSError:
        pass


class AsyncWiper:
    def __init__(self, audit_logger: Optional[AuditLogger] = None):
        self.audit = audit_logger or AuditLogger()
        # buffers distintos según soporte; en SSDs los writes grandes son más eficientes
        self.BUFFER_HDD = 10 * 1024 * 1024
        self.BUFFER_SSD = 50 * 1024 * 1024

    async def wipe_file(
        self,
        path: Path,
        standard: SanitizationStandard = SanitizationStandard.NIST_CLEAR,
        verify: bool = False,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "success": False,
            "passes_completed": 0,
            "verified": False,
            "duration": 0.0,
            "strategy": "Unknown",
            "error": None,
        }

        # guardamos esto antes de tocar nada, porque después del unlink ya no hay stat()
        sha256_before = "unknown"
        file_size_for_audit = 0

        try:
            if not path.exists():
                raise FileNotFoundError(f"No se encuentra el archivo: {path}")

            file_size_for_audit = path.stat().st_size
            _ensure_writable(path)
            storage_type = detect_storage_type(path)

            if storage_type in (StorageType.SSD, StorageType.NVME):
                strategy_name = "SSD/NVMe"
                buffer_size = self.BUFFER_SSD
            else:
                strategy_name = "HDD"
                buffer_size = self.BUFFER_HDD

            result["strategy"] = f"{strategy_name} ({standard.value})"

            sha256_before = await self._calculate_sha256(path)
            passes_config = self._get_passes_config(storage_type, standard)
            passes_done = 0
            start_time = time.time()

            async with aiofiles.open(path, "rb+") as f:
                for pass_idx, pattern_type in enumerate(passes_config, 1):
                    await f.seek(0)
                    remaining = file_size_for_audit
                    bytes_this_pass = 0

                    while remaining > 0:
                        chunk_size = min(remaining, buffer_size)
                        data = await self._generate_pattern(pattern_type, chunk_size)
                        await f.write(data)
                        remaining -= chunk_size
                        bytes_this_pass += chunk_size

                        if progress_callback:
                            if asyncio.iscoroutinefunction(progress_callback):
                                await progress_callback(path, pass_idx, bytes_this_pass, file_size_for_audit)
                            else:
                                progress_callback(path, pass_idx, bytes_this_pass, file_size_for_audit)

                    await f.flush()
                    await asyncio.to_thread(os.fsync, f.fileno())
                    passes_done += 1

            result["duration"] = time.time() - start_time
            result["passes_completed"] = passes_done
            result["success"] = True

            if verify:
                # verificamos antes de eliminar; necesitamos el archivo todavía en disco
                verified = await self._verify_entropy(path, expected_pattern=passes_config[-1])
                result["verified"] = verified
                if not verified:
                    result["error"] = "Verificación de entropía fallida"
                    result["success"] = False
            else:
                result["verified"] = None  # skipped

            try:
                path.unlink()
            except Exception as e:
                result["error"] = f"Borrado completado pero no se pudo eliminar el inodo: {e}"

        except Exception as e:
            result["error"] = str(e)
            result["success"] = False

        # log siempre al final, con los datos que hayamos podido recoger
        self.audit.log_wipe_operation(
            path,
            file_size_for_audit,
            sha256_before,
            standard.value,
            result,
        )

        return result

    def _get_passes_config(self, storage_type: StorageType, standard: SanitizationStandard) -> list:
        # en SSDs más de un pase no aporta nada útil y desgasta la celda
        if storage_type in (StorageType.SSD, StorageType.NVME):
            return ["random"]
        if standard == SanitizationStandard.NIST_CLEAR:
            return ["zeros"]
        return ["zeros", "ones", "random"]

    async def _generate_pattern(self, pattern_type: str, size: int) -> bytes:
        if pattern_type == "zeros":
            return b"\x00" * size
        if pattern_type == "ones":
            return b"\xFF" * size
        return await asyncio.to_thread(os.urandom, size)

    async def _calculate_sha256(self, path: Path) -> str:
        sha256 = hashlib.sha256()
        try:
            async with aiofiles.open(path, "rb") as f:
                while chunk := await f.read(1024 * 1024):
                    sha256.update(chunk)
        except Exception:
            return "hash_error"
        return sha256.hexdigest()

    async def _verify_entropy(
        self,
        path: Path,
        expected_pattern: str = "random",
        sample_count: int = 20,
        block_size: int = 4096,
    ) -> bool:
        # muestreamos bloques aleatorios para no tener que leer el fichero entero
        # entropía de datos aleatorios debería estar por encima de 7.0 bits/byte
        if not path.exists() or path.stat().st_size == 0:
            return True

        file_size = path.stat().st_size

        def calc_entropy(data: bytes) -> float:
            if not data:
                return 0.0
            counter = Counter(data)
            length = len(data)
            return -sum((c / length) * math.log2(c / length) for c in counter.values())

        total_entropy = 0.0
        samples_taken = 0

        try:
            async with aiofiles.open(path, "rb") as f:
                for _ in range(sample_count):
                    offset = random.randint(0, max(0, file_size - block_size)) if file_size > block_size else 0
                    await f.seek(offset)
                    data = await f.read(block_size)
                    if data:
                        total_entropy += calc_entropy(data)
                        samples_taken += 1
        except Exception:
            return False

        if samples_taken == 0:
            return True

        avg_entropy = total_entropy / samples_taken
        return avg_entropy > 7.0 if expected_pattern == "random" else avg_entropy < 0.1
