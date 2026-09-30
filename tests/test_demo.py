"""The README demo: docs/demo.cast, docs/demo.gif and scripts/demo/.

Nothing is recorded or wiped here: the checked-in recording is only read,
and the GIF renderer is exercised on a tiny synthetic cast in ``tmp_path``.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from madaramaster.i18n import LANG

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DEMO = ROOT / "scripts" / "demo"
GIF_URL = "https://raw.githubusercontent.com/jaimefgdev/MadaraMaster/main/docs/demo.gif"


def load_cast(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[0]), [json.loads(line) for line in lines[1:] if line.strip()]


def test_demo_cast_is_valid_and_shows_the_whole_flow():
    header, events = load_cast(DOCS / "demo.cast")
    assert header["version"] == 2
    assert header["width"] >= 80 and header["height"] >= 24
    times = [e[0] for e in events]
    assert times == sorted(times)
    assert 10 <= times[-1] <= 40  # roughly a 20 second demo
    assert all(e[1] == "o" for e in events)

    output = "".join(e[2] for e in events)
    assert "\ufffd" not in output  # no UTF-8 sequence split between reads
    for text in (
        "madara wipe secret-project",
        "Type the directory name (secret-project) to confirm",
        "WIPE SUMMARY",
        "5 FILES OVERWRITTEN AND DELETED",
        "No such file or directory",
    ):
        assert text in output, text
    # The recording ran in a throwaway temporary directory.
    assert "/home/" not in output and "C:\\" not in output


def test_demo_gif_is_checked_in_and_small():
    gif = DOCS / "demo.gif"
    data = gif.read_bytes()
    assert data[:6] in (b"GIF87a", b"GIF89a")
    assert len(data) < 2 * 1024 * 1024


@pytest.mark.parametrize("lang", sorted(LANG))
def test_no_variation_selectors_in_strings(lang):
    # U+FE0F makes emoji width differ between Rich and terminals, which
    # misaligns the live dashboard (and leaves stale lines in the demo).
    bad = {k: v for k, v in LANG[lang].items() if "\ufe0f" in v}
    assert not bad


def test_readme_shows_demo_install_and_exe_link():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    head = readme[: readme.index("## 🇬🇧 English")]
    assert GIF_URL in head  # absolute URL, so it also renders on PyPI
    assert "pip install madaramaster" in head
    assert "https://github.com/jaimefgdev/MadaraMaster/releases/latest" in head
    assert "scripts/demo/make_demo.sh" in readme


def test_demo_scripts_are_present():
    for name in ("record.py", "render_gif.py", "make_demo.sh"):
        assert (DEMO / name).is_file(), name
    record = (DEMO / "record.py").read_text(encoding="utf-8")
    assert "tempfile.mkdtemp" in record
    assert '"HOME": str(tmp)' in record
    assert "--trim" not in record.split('madara = [')[1]


def test_render_gif_on_a_synthetic_cast(tmp_path):
    pytest.importorskip("pyte")
    pytest.importorskip("PIL")
    spec = importlib.util.spec_from_file_location("render_gif", DEMO / "render_gif.py")
    render_gif = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(render_gif)
    try:
        render_gif.find_font("DejaVuSansMono.ttf")
        render_gif.find_font("DejaVuSansMono-Bold.ttf")
    except SystemExit:
        pytest.skip("DejaVu fonts not installed")

    cast = tmp_path / "t.cast"
    events = [[0.0, "o", "$ "], [0.5, "o", "\x1b[1;32mok\x1b[0m ┌──┐\r\n"], [9.0, "o", "$ "]]
    cast.write_text(
        "\n".join(json.dumps(x) for x in [{"version": 2, "width": 20, "height": 4}, *events]),
        encoding="utf-8",
    )
    out = tmp_path / "t.gif"
    render_gif.render(cast, out, font_size=15, fps=10, idle_limit=1.0, end_hold=1.0)

    from PIL import Image

    with Image.open(out) as im:
        assert im.n_frames >= 2
        durations = []
        for i in range(im.n_frames):
            im.seek(i)
            durations.append(im.info["duration"])
    # The 8.5 s pause is capped by idle_limit, the last frame held end_hold.
    assert sum(durations) <= 3000
    assert durations[-1] == 1000
