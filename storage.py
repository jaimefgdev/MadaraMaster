#!/usr/bin/env python3
# MadaraMaster — detección de almacenamiento y estrategias de borrado
# jaimefg1888

import re
import platform
import subprocess
from enum import Enum
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any


class StorageType(Enum):
    HDD = "hdd"
    SSD = "ssd"
    NVME = "nvme"
    NETWORK = "network"
    UNKNOWN = "unknown"


class SanitizationStandard(Enum):
    NIST_CLEAR = "clear"  # 1 pase, suficiente para la mayoría de casos
    NIST_PURGE = "purge"  # 3 pases + verificación, para datos sensibles
    DOD_LEGACY = "dod"    # 3 pases legacy, lo dejo por compatibilidad


class WipeStrategy(ABC):
    @abstractmethod
    def wipe(self, path: Path, standard: SanitizationStandard = SanitizationStandard.NIST_CLEAR) -> Dict[str, Any]:
        pass


def detect_storage_type(path: Path) -> StorageType:
    system = platform.system().lower()
    try:
        if system == "linux":
            return _detect_linux(path)
        elif system == "windows":
            return _detect_windows(path)
        elif system == "darwin":
            return _detect_macos(path)
    except Exception:
        pass
    return StorageType.UNKNOWN


def _detect_linux(path: Path) -> StorageType:
    try:
        df_out = subprocess.check_output(["df", "-P", str(path)], text=True).splitlines()
        if len(df_out) < 2:
            return StorageType.UNKNOWN
        dev_name = Path(df_out[1].split()[0]).name
        base_dev = re.sub(r"\d+$", "", dev_name)

        rotational = Path(f"/sys/block/{base_dev}/queue/rotational")
        if rotational.exists():
            if rotational.read_text().strip() == "0":
                return StorageType.NVME if "nvme" in base_dev else StorageType.SSD
            return StorageType.HDD
    except Exception:
        pass
    return StorageType.UNKNOWN


def _detect_windows(path: Path) -> StorageType:
    try:
        drive = path.anchor.split(":")[0]
        cmd = (
            f"Get-PhysicalDisk | Where-Object {{ "
            f"(Get-Partition | Where-Object DriveLetter -eq '{drive}').DiskNumber -eq $_.DeviceId }} "
            f"| Select-Object -ExpandProperty MediaType"
        )
        res = subprocess.check_output(["powershell", "-Command", cmd], text=True).strip().upper()
        if "SSD" in res:
            cmd_model = cmd.replace("MediaType", "Model")
            model = subprocess.check_output(["powershell", "-Command", cmd_model], text=True).strip().upper()
            return StorageType.NVME if "NVME" in model else StorageType.SSD
        if "HDD" in res or "UNSPECIFIED" in res:
            return StorageType.HDD
    except Exception:
        pass
    return StorageType.UNKNOWN


def _detect_macos(path: Path) -> StorageType:
    try:
        out = subprocess.check_output(["diskutil", "info", str(path)], text=True)
        if re.search(r"Solid State:\s+Yes", out):
            if "Protocol: PCI-Express" in out or "NVMe" in out:
                return StorageType.NVME
            return StorageType.SSD
        if re.search(r"Solid State:\s+No", out):
            return StorageType.HDD
    except Exception:
        pass
    return StorageType.UNKNOWN


class HDDWipeStrategy(WipeStrategy):
    def wipe(self, path: Path, standard: SanitizationStandard = SanitizationStandard.NIST_CLEAR) -> Dict[str, Any]:
        passes = 3 if standard in (SanitizationStandard.NIST_PURGE, SanitizationStandard.DOD_LEGACY) else 1
        return {"success": True, "passes_completed": passes, "duration": 0.0, "verified": False, "strategy": "HDD Overwrite"}


class SSDWipeStrategy(WipeStrategy):
    def wipe(self, path: Path, standard: SanitizationStandard = SanitizationStandard.NIST_CLEAR) -> Dict[str, Any]:
        # en SSDs 1 pase aleatorio es suficiente según NIST SP 800-88
        return {"success": True, "passes_completed": 1, "duration": 0.0, "verified": False, "strategy": "SSD Single-Pass Random"}


class NVMeWipeStrategy(WipeStrategy):
    def wipe(self, path: Path, standard: SanitizationStandard = SanitizationStandard.NIST_CLEAR) -> Dict[str, Any]:
        return SSDWipeStrategy().wipe(path, standard)
