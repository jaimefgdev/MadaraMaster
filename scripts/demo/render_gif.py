#!/usr/bin/env python3
"""Render an asciicast v2 recording to an animated GIF.

A small, dependency-light alternative to `agg <https://github.com/asciinema/agg>`_
(use agg instead if you have it; ``make_demo.sh`` does so automatically).
The terminal is emulated with `pyte`, frames are drawn with Pillow using
DejaVu Sans Mono, and emoji are drawn with Noto Color Emoji when available.

Usage::

    pip install pyte pillow
    python scripts/demo/render_gif.py docs/demo.cast docs/demo.gif
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyte
from PIL import Image, ImageDraw, ImageFont

FONT_DIRS = [
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/dejavu"),
    Path("/Library/Fonts"),
    Path.home() / ".local/share/fonts",
]
EMOJI_FONTS = [
    Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
    Path("/usr/share/fonts/noto/NotoColorEmoji.ttf"),
    Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
]

# Dark theme (One Dark-like).  pyte colour names -> RGB.
THEME = {
    "bg": (30, 33, 39),
    "fg": (220, 223, 228),
    "black": (40, 44, 52),
    "red": (224, 108, 117),
    "green": (152, 195, 121),
    "brown": (229, 192, 123),
    "blue": (97, 175, 239),
    "magenta": (198, 120, 221),
    "cyan": (86, 182, 194),
    "white": (220, 223, 228),
    "brightblack": (92, 99, 112),
    "brightred": (240, 128, 138),
    "brightgreen": (170, 220, 140),
    "brightbrown": (240, 210, 140),
    "brightblue": (120, 190, 255),
    "brightmagenta": (215, 140, 235),
    "brightcyan": (110, 205, 215),
    "brightwhite": (255, 255, 255),
}
ALIASES = {"yellow": "brown", "brightyellow": "brightbrown"}


def find_font(name: str) -> Path:
    for d in FONT_DIRS:
        p = d / name
        if p.exists():
            return p
    raise SystemExit(f"font {name} not found; install DejaVu fonts (fonts-dejavu)")


def color(value: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    if value == "default":
        return default
    value = ALIASES.get(value, value)
    if value in THEME:
        return THEME[value]
    if len(value) == 6:
        try:
            return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            pass
    return default


def is_wide_emoji(ch: str, next_cell_data: str | None) -> bool:
    """Colour-emoji glyph only for characters the terminal laid out as wide.

    pyte marks the second half of a wide character with an empty cell.
    Narrow symbols such as ⚠ or ✔ stay in the text font.
    """
    return next_cell_data == "" and ord(ch[0]) >= 0x2300


class Renderer:
    def __init__(self, cols: int, rows: int, font_size: int, padding: int) -> None:
        self.cols, self.rows, self.pad = cols, rows, padding
        self.font = ImageFont.truetype(str(find_font("DejaVuSansMono.ttf")), font_size)
        self.bold = ImageFont.truetype(str(find_font("DejaVuSansMono-Bold.ttf")), font_size)
        # The cell is exactly as tall as the full-block glyph so that
        # box-drawing characters join up between rows.
        _, top, _, bottom = self.font.getbbox("█")
        self.cw = round(self.font.getlength("M"))
        self.ch = bottom - top
        self.yoff = -top
        emoji = next((p for p in EMOJI_FONTS if p.exists()), None)
        self.emoji_font = ImageFont.truetype(str(emoji), 109) if emoji else None
        self._emoji_cache: dict[str, Image.Image | None] = {}
        self.size = (cols * self.cw + 2 * padding, rows * self.ch + 2 * padding)

    def emoji(self, ch: str) -> Image.Image | None:
        if ch not in self._emoji_cache:
            self._emoji_cache[ch] = self._draw_emoji(ch)
        return self._emoji_cache[ch]

    def _draw_emoji(self, ch: str) -> Image.Image | None:
        if self.emoji_font is None:
            return None
        img = Image.new("RGBA", (136, 128), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((0, 0), ch, font=self.emoji_font, embedded_color=True)
        box = img.getbbox()
        if not box:
            return None
        img = img.crop(box)
        target_h = self.ch - 3
        w = max(1, round(img.width * target_h / img.height))
        return img.resize((min(w, 2 * self.cw), target_h), Image.LANCZOS)

    def frame(self, screen: pyte.Screen, cursor: bool) -> Image.Image:
        img = Image.new("RGB", self.size, THEME["bg"])
        draw = ImageDraw.Draw(img)
        for y in range(self.rows):
            line = screen.buffer[y]
            for x in range(self.cols):
                cell = line[x]
                fg = color(cell.fg, THEME["fg"])
                bg = color(cell.bg, THEME["bg"])
                if cell.reverse:
                    fg, bg = bg, fg
                if cell.bold and cell.fg in THEME and not cell.fg.startswith("bright"):
                    fg = THEME.get("bright" + cell.fg, fg)
                px, py = self.pad + x * self.cw, self.pad + y * self.ch
                if bg != THEME["bg"]:
                    draw.rectangle([px, py, px + self.cw - 1, py + self.ch - 1], fill=bg)
                data = cell.data
                if not data or data == " ":
                    continue
                nxt = line[x + 1].data if x + 1 < self.cols else None
                if is_wide_emoji(data, nxt):
                    glyph = self.emoji(data[0])
                    if glyph is not None:
                        img.paste(glyph, (px, py + 1), glyph)
                        continue
                font = self.bold if cell.bold else self.font
                draw.text((px, py + self.yoff), data[0], font=font, fill=fg)
        if cursor and not screen.cursor.hidden:
            cx = self.pad + screen.cursor.x * self.cw
            cy = self.pad + screen.cursor.y * self.ch
            draw.rectangle([cx, cy, cx + self.cw - 1, cy + self.ch - 1], fill=THEME["fg"])
        return img


def render(
    cast: Path, out: Path, font_size: int, fps: int, idle_limit: float, end_hold: float
) -> None:
    lines = cast.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    events = [json.loads(line) for line in lines[1:] if line.strip()]
    cols, rows = header["width"], header["height"]

    screen = pyte.Screen(cols, rows)
    stream = pyte.Stream(screen)
    renderer = Renderer(cols, rows, font_size, padding=12)

    # Output events on the GIF's clock: pauses longer than idle_limit are cut.
    timeline: list[tuple[float, str]] = []
    last_t = 0.0
    shift = 0.0  # idle time removed so far
    for t, kind, data in events:
        if kind != "o":
            continue
        gap = t - last_t
        if gap > idle_limit:
            shift += gap - idle_limit
        last_t = t
        timeline.append((t - shift, data))

    # A frame is the screen *after* an event, shown from that event until the
    # next frame.  The state after event i is captured when it stays on screen
    # long enough to matter (the next event is at least one frame period after
    # the last capture) and always for the last event, so the final state of a
    # burst (e.g. a dashboard at 100 % before a pause) is never skipped.
    frames: list[Image.Image] = []
    starts: list[float] = []
    step = 1.0 / fps
    for i, (at, data) in enumerate(timeline):
        stream.feed(data)
        next_at = timeline[i + 1][0] if i + 1 < len(timeline) else None
        if frames and next_at is not None and next_at - starts[-1] < step:
            continue
        img = renderer.frame(screen, cursor=True)
        if frames and img.tobytes() == frames[-1].tobytes():
            continue
        starts.append(at if starts else 0.0)
        frames.append(img)
    durations = [
        max(20, round((b - a) * 1000)) for a, b in zip(starts, starts[1:], strict=False)
    ]
    durations.append(round(end_hold * 1000))

    palette_frames = [
        f.quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        for f in frames
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    palette_frames[0].save(
        out,
        save_all=True,
        append_images=palette_frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,
    )
    total = sum(durations) / 1000
    width, height = renderer.size
    print(f"wrote {out}: {len(frames)} frames, {total:.1f}s, {width}x{height}px,"
          f" {out.stat().st_size / 1024:.0f} KB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cast", type=Path)
    parser.add_argument("gif", type=Path)
    parser.add_argument("--font-size", type=int, default=15,
                        help="15 px gives DejaVu Sans Mono an integer 9 px advance")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--idle-limit", type=float, default=2.5,
                        help="Longest pause kept, in seconds")
    parser.add_argument("--end-hold", type=float, default=4.0,
                        help="How long the last frame stays before looping, in seconds")
    args = parser.parse_args()
    render(args.cast, args.gif, args.font_size, args.fps, args.idle_limit, args.end_hold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
