"""Windows only — Alternate Data Streams are enumerated and wiped without crashing.

Regression: ``FindFirstStreamW`` was called without a ``restype``; ctypes
truncated the 64-bit find handle and every wipe on Windows failed with an
access violation.
"""

import os
import sys

import pytest

from madaramaster import engine as wiper_async

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="NTFS alternate data streams")


def test_enumerates_alternate_data_streams(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"main stream")
    with open(f"{f}:hidden", "wb") as ads:
        ads.write(b"secret in a stream")

    assert wiper_async._enumerate_ads_windows(f) == [":hidden:$DATA"]


def test_file_without_streams_has_none(tmp_path):
    f = tmp_path / "plain.txt"
    f.write_bytes(b"x")
    assert wiper_async._enumerate_ads_windows(f) == []


async def test_wipe_destroys_streams_and_file(tmp_path, wiper):
    f = tmp_path / "doc.txt"
    f.write_bytes(os.urandom(5000))
    with open(f"{f}:hidden", "wb") as ads:
        ads.write(b"secret in a stream" * 100)

    result = await wiper.wipe_file(f, verify=True)

    assert result["success"], result["error"]
    assert result["ads_wiped"] == 1
    assert not f.exists()
