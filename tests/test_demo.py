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


def test_render_gif_keeps_terminal_colours_exact():
    """A few pixels of a terminal colour are not averaged into their neighbours.

    The old 96-colour median cut turned the pink "Total Duration" value of
    the summary almost grey in the last frame.
    """
    pytest.importorskip("pyte")
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw

    spec = importlib.util.spec_from_file_location("render_gif", DEMO / "render_gif.py")
    render_gif = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(render_gif)

    pink, grey = render_gif.THEME["brightmagenta"], (171, 139, 175)
    img = Image.new("RGB", (400, 100), render_gif.THEME["bg"])
    draw = ImageDraw.Draw(img)
    for x in range(400):  # far more colours than a GIF palette holds
        draw.line([(x, 0), (x, 89)], fill=(x % 256, (x * 3) % 256, 255 - x % 256))
    draw.rectangle([10, 92, 17, 97], fill=pink)  # a small patch, like one glyph
    draw.rectangle([30, 92, 37, 97], fill=grey)

    out = render_gif.to_palette(img, {pink, grey, render_gif.THEME["bg"]}).convert("RGB")
    assert out.getpixel((13, 95)) == pink
    assert out.getpixel((33, 95)) == grey
    assert out.getpixel((200, 95)) == render_gif.THEME["bg"]


def load_checker():
    pytest.importorskip("pyte")
    spec = importlib.util.spec_from_file_location("check_cast", DEMO / "check_cast.py")
    check_cast = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check_cast)
    return check_cast


def test_checked_in_recording_has_no_repaint_leftovers():
    # Every screen of the recording (a superset of the GIF frames) is clean.
    assert load_checker().check(DOCS / "demo.cast") == []


def _write_cast(path, *chunks, width=40, height=10):
    lines = [json.dumps({"version": 2, "width": width, "height": height})]
    lines += [json.dumps([i * 0.1, "o", c]) for i, c in enumerate(chunks)]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


DASH = "┏" + "━" * 20 + "┓\r\n┃ MADARA MASTER v5 ┃\r\n┗" + "━" * 20 + "┛"


def test_checker_accepts_a_clean_dashboard(tmp_path):
    cast = _write_cast(tmp_path / "ok.cast", "Type the directory name: x\r\n", DASH)
    assert load_checker().check(cast) == []


def test_checker_flags_a_duplicated_prompt(tmp_path):
    cast = _write_cast(
        tmp_path / "dup.cast", "Type the directory name: x\r\n", DASH,
        "\r\nType the directory name: x",
    )
    problems = load_checker().check(cast)
    assert any("on screen 2 times" in p for p in problems)
    assert any("text below the dashboard" in p for p in problems)


def test_checker_flags_a_half_drawn_repaint(tmp_path):
    torn = "┏" + "━" * 20 + "┓\r\n┃ MADARA MASTER v5 ┃\r\n┗" + "━" * 8
    cast = _write_cast(tmp_path / "torn.cast", torn)
    problems = load_checker().check(cast)
    assert any("drawn only in part" in p for p in problems)


# Majors that run on Node.js 24; the previous ones run on the deprecated Node.js 20.
MIN_ACTION_MAJOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/upload-artifact": 6,
    "actions/download-artifact": 7,
}


def test_workflows_use_node24_actions():
    import re

    workflows = ROOT / ".github" / "workflows"
    if not workflows.is_dir():
        pytest.skip("no .github/workflows (e.g. running from the sdist)")
    found = set()
    for wf in workflows.glob("*.yml"):
        for action, major in re.findall(r"uses:\s*([\w.-]+/[\w.-]+)@v(\d+)", wf.read_text()):
            if action in MIN_ACTION_MAJOR:
                found.add(action)
                assert int(major) >= MIN_ACTION_MAJOR[action], f"{wf.name}: {action}@v{major}"
    assert found == set(MIN_ACTION_MAJOR)


# Like Rich at the end of a transient Live: erase the dashboard, print the summary.
CLEAR_AND_SUMMARY = "\r\x1b[2KWIPE SUMMARY"


def _progress_cast(path, steps):
    """A cast whose dashboard line shows each (time, percent) in *steps*."""
    lines = [json.dumps({"version": 2, "width": 60, "height": 5})]
    for t, pct in steps:
        lines.append(json.dumps([t, "o", f"\r\x1b[2KGlobal Progress  {pct:.1f}%"]))
    lines.append(json.dumps([steps[-1][0] + 1.0, "o", CLEAR_AND_SUMMARY]))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_checker_wants_100_percent_held_on_screen(tmp_path):
    check = load_checker().check
    assert check(_progress_cast(tmp_path / "ok.cast", [(0, 0), (0.1, 60), (0.2, 100)])) == []
    never = check(_progress_cast(tmp_path / "never.cast", [(0, 0), (0.1, 95)]))
    assert any("never shows 100 %" in p for p in never)
    brief = _progress_cast(tmp_path / "brief.cast", [(0, 0), (0.1, 100)])
    text = brief.read_text().splitlines()
    text[-1] = json.dumps([0.15, "o", CLEAR_AND_SUMMARY])  # replaced after 50 ms
    brief.write_text("\n".join(text), encoding="utf-8")
    assert any("100 % shown for" in p for p in check(brief))


def test_checker_flags_progress_going_back(tmp_path):
    problems = load_checker().check(
        _progress_cast(tmp_path / "back.cast", [(0, 0), (0.1, 84), (0.2, 18.5), (0.3, 100)])
    )
    assert any("went back from 84.0% to 18.5%" in p for p in problems)


def test_render_gif_keeps_the_state_before_a_pause_for_its_real_duration(tmp_path):
    """The screen after a burst stays in the GIF as long as it stayed on screen.

    The renderer used to snapshot *before* each event, so a final state
    (e.g. the dashboard at 100 %) lasted until the next event after the pause.
    """
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

    events = [[0.0, "o", "a"], [0.01, "o", "b"], [0.02, "o", "c"], [0.62, "o", "d"]]
    cast = tmp_path / "burst.cast"
    cast.write_text(
        "\n".join(json.dumps(x) for x in [{"version": 2, "width": 10, "height": 2}, *events]),
        encoding="utf-8",
    )
    out = tmp_path / "burst.gif"
    render_gif.render(cast, out, font_size=15, fps=12, idle_limit=2.5, end_hold=1.0)

    from PIL import Image

    with Image.open(out) as im:
        durations = []
        for i in range(im.n_frames):
            im.seek(i)
            durations.append(im.info["duration"])
    assert 600 in durations  # "abc" from 0.02 s to 0.62 s
    assert durations[-1] == 1000
