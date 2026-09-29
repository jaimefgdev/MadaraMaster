"""Warnings for setups where a file-level wipe cannot remove every copy."""

import os
import sys

import pytest
from typer.testing import CliRunner

from madaramaster import cli as madara
from madaramaster import residue
from madaramaster.residue import Residue

# conftest replaces detect_residue_risks with a mock; keep the real one here.
REAL_DETECT = residue.detect_residue_risks

MOUNTINFO = """\
22 1 8:2 / / rw,relatime shared:1 - ext4 /dev/sda2 rw,errors=remount-ro
30 22 0:40 / /home rw,relatime shared:2 - btrfs /dev/sda3 rw,space_cache=v2
31 22 8:5 / /srv/journal rw,relatime shared:3 - ext4 /dev/sda5 rw,data=journal
32 22 0:50 / /mnt/nas rw,relatime shared:4 - nfs4 nas:/export rw,vers=4.2
33 22 8:6 / /media/My\\040Disk rw,relatime shared:5 - xfs /dev/sdb1 rw
"""

BSD_MOUNT = """\
/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)
/dev/disk3s5 on /System/Volumes/Data (apfs, local, journaled, nobrowse)
//user@nas/share on /Volumes/share (smbfs, nodev, nosuid, mounted by user)
/dev/disk4s1 on /Volumes/USB STICK (msdos, local, nodev, nosuid)
"""


def _p(*parts):
    return os.path.join(os.sep, *parts)


# ─── Mount-table parsing ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path, fstype",
    [
        (_p("etc", "passwd"), "ext4"),
        (_p("home", "jaime", "doc.txt"), "btrfs"),
        (_p("mnt", "nas", "x"), "nfs4"),
        (_p("media", "My Disk", "a.pdf"), "xfs"),
        (_p("homeless", "a"), "ext4"),  # prefix of "/home" but not inside it
    ],
)
def test_parse_mountinfo_picks_longest_mount(path, fstype):
    assert residue.parse_mountinfo(MOUNTINFO, path)[0] == fstype


def test_parse_mountinfo_reads_super_options():
    fs = residue.parse_mountinfo(MOUNTINFO, _p("srv", "journal", "f"))
    assert fs[0] == "ext4" and "data=journal" in fs[1]


def test_parse_mountinfo_ignores_garbage():
    assert residue.parse_mountinfo("garbage\n\n", _p("x")) is None


@pytest.mark.parametrize(
    "path, fstype",
    [
        (_p("System", "Volumes", "Data", "Users", "j", "a.txt"), "apfs"),
        (_p("Volumes", "share", "doc"), "smbfs"),
        (_p("Volumes", "USB STICK", "a"), "msdos"),
    ],
)
def test_parse_bsd_mount(path, fstype):
    assert residue.parse_bsd_mount(BSD_MOUNT, path)[0] == fstype


# ─── Risk translation ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fs, expected",
    [
        (("btrfs", set()), [Residue.COW_FS]),
        (("apfs", {"local"}), [Residue.COW_FS]),
        (("refs", set()), [Residue.COW_FS]),
        (("nfs4", set()), [Residue.NETWORK]),
        (("ntfs", {"remote"}), [Residue.NETWORK]),
        (("unc", {"remote"}), [Residue.NETWORK]),
        (("ext4", {"rw", "data=journal"}), [Residue.DATA_JOURNAL]),
        (("ext4", {"rw", "data=ordered"}), []),
        (("ntfs", set()), []),
        (None, []),
    ],
)
def test_risks_from_filesystem(fs, expected):
    assert residue.risks_from_filesystem(fs) == expected


# ─── Cloud sync ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "parts, synced",
    [
        (("Users", "j", "Dropbox", "a.pdf"), True),
        (("Users", "j", "OneDrive", "a.pdf"), True),
        (("Users", "j", "OneDrive - Empresa SL", "a.pdf"), True),
        (("Users", "j", "Google Drive", "a.pdf"), True),
        (("Users", "j", "Library", "CloudStorage", "GoogleDrive-x", "a"), True),
        (("Users", "j", "Library", "Mobile Documents", "com~apple~CloudDocs", "a"), True),
        (("Users", "j", "Documents", "a.pdf"), False),
        (("Users", "j", "dropbox-notes.txt"), False),
    ],
)
def test_cloud_folder_names(parts, synced):
    assert residue.is_cloud_synced(_p(*parts), environ={}) is synced


def test_cloud_env_var_root():
    root = _p("data", "sync-here")
    assert residue.is_cloud_synced(os.path.join(root, "a.txt"), environ={"OneDrive": root})
    assert not residue.is_cloud_synced(_p("data", "other", "a.txt"), environ={"OneDrive": root})


# ─── Entry point ─────────────────────────────────────────────────────────────


def test_detect_combines_filesystem_and_cloud(monkeypatch):
    monkeypatch.setattr(residue, "filesystem_info", lambda p: ("btrfs", set()))
    monkeypatch.setattr(residue, "is_cloud_synced", lambda p: True)
    assert REAL_DETECT(_p("home", "a")) == [Residue.COW_FS, Residue.CLOUD_SYNC]


def test_detect_never_raises(monkeypatch):
    def boom(p):
        raise RuntimeError("probe failed")

    monkeypatch.setattr(residue, "filesystem_info", boom)
    assert REAL_DETECT(_p("x")) == []


def test_real_probe_on_this_machine(tmp_path):
    """The real (read-only) probe works on the CI runners and never raises."""
    info = residue.filesystem_info(str(tmp_path))
    if sys.platform.startswith("linux") or sys.platform == "win32":
        assert info is not None and info[0]
    risks = REAL_DETECT(tmp_path)
    assert isinstance(risks, list)
    assert Residue.NETWORK not in risks


# ─── CLI output ──────────────────────────────────────────────────────────────


@pytest.fixture
def english():
    madara.current_lang = "EN"
    yield
    madara.current_lang = "EN"


def test_cli_warns_before_wiping(tmp_path, fake_residue, english):
    fake_residue.return_value = [Residue.COW_FS, Residue.CLOUD_SYNC]
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    res = CliRunner().invoke(madara.app, ["wipe", str(f), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "Copies may survive this wipe" in res.output
    assert "Copy-on-write" in res.output
    assert "Cloud-synced folder" in res.output
    assert f.exists()


def test_cli_no_warning_when_nothing_detected(tmp_path, fake_residue, english):
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    res = CliRunner().invoke(madara.app, ["wipe", str(f), "--dry-run"])
    assert res.exit_code == 0, res.output
    assert "Copies may survive" not in res.output


def test_cli_warning_in_spanish(tmp_path, fake_residue):
    fake_residue.return_value = [Residue.NETWORK]
    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    try:
        res = CliRunner().invoke(madara.app, ["--lang", "es", "wipe", str(f), "--dry-run"])
    finally:
        madara.current_lang = "EN"
    assert res.exit_code == 0, res.output
    assert "Pueden quedar copias" in res.output
    assert "Ubicación de red" in res.output


def test_every_residue_has_both_translations():
    for risk in Residue:
        for lang in ("EN", "ES"):
            assert f"residue_{risk.value}" in madara.LANG[lang]
