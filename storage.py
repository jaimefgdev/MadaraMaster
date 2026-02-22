#!/usr/bin/env python3
# Detección de tipo de almacenamiento y selección de estrategia
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
    NIST_CLEAR = "clear"  # 1 pase, suficiente para casi todo
    NIST_PURGE = "purge"  # 3 pases + verificación
    DOD_LEGACY = "dod"    # igual que purge, lo mantengo por compatibilidad con scripts viejos


class WipeStrategy(ABC):
    @abstractmethod
    def get_passes(self, standard: SanitizationStandard) -> int:
        pass

    @abstractmethod
    def get_description(self) -> str:
        pass


class HDDWipeStrategy(WipeStrategy):
    def get_passes(self, standard: SanitizationStandard) -> int:
        if standard in (SanitizationStandard.NIST_PURGE, SanitizationStandard.DOD_LEGACY):
            return 3
        return 1

    def get_description(self) -> str:
        return "HDD: sobrescritura magnética clásica (zeros → ones → random)"


class SSDWipeStrategy(WipeStrategy):
    def get_passes(self, standard: SanitizationStandard) -> int:
        # NIST SP 800-88 es claro: un pase aleatorio es suficiente en flash
        # hacer más pases solo consume ciclos de escritura sin beneficio real
        return 1

    def get_description(self) -> str:
        return "SSD/NVMe: pase único aleatorio criptográfico"


class NVMeWipeStrategy(SSDWipeStrategy):
    # NVMe y SSD se tratan igual a nivel de borrado por software
    def get_description(self) -> str:
        return "NVMe: pase único aleatorio criptográfico"


def get_strategy(storage_type: StorageType) -> WipeStrategy:
    if storage_type == StorageType.HDD:
        return HDDWipeStrategy()
    if storage_type == StorageType.NVME:
        return NVMeWipeStrategy()
    # SSD y UNKNOWN reciben la misma estrategia conservadora
    return SSDWipeStrategy()


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
