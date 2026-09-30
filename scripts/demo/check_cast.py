#!/usr/bin/env python3
"""Check a demo recording for repaint leftovers, frame by frame.

The asciicast is replayed in `pyte` and the screen is inspected after
*every* output event (a superset of the frames that end up in the GIF):

* the confirmation prompt is on screen at most once;
* while the live dashboard is on screen it is complete (top and bottom
  border) and nothing is printed below it;
* the summary table and the final banner are never on screen twice;
* no replacement characters (U+FFFD) from split UTF-8 sequences;
* the dashboard's global progress never goes back and never claims
  100 % with nothing to write ("0 B / 0 B").

Usage::

    python scripts/demo/check_cast.py docs/demo.cast

Exit code 0 when the recording is clean, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pyte

CONFIRM = "Type the directory name"
DASH_HEADER = "MADARA MASTER v"
PROGRESS = re.compile(r"Global Progress.*?(\d+(?:\.\d)?)%")
ONCE = (CONFIRM, "WIPE SUMMARY", "FILES OVERWRITTEN AND DELETED", DASH_HEADER)


def load(path: Path) -> tuple[dict, list[list]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[0]), [json.loads(line) for line in lines[1:] if line.strip()]


def screen_problems(rows: list[str]) -> list[str]:
    """Problems visible on one screen (a list of text rows)."""
    problems = []
    for text in ONCE:
        n = sum(text in row for row in rows)
        if n > 1:
            problems.append(f"{text!r} on screen {n} times")
    if any("�" in row for row in rows):
        problems.append("replacement character on screen")

    header = next((i for i, row in enumerate(rows) if DASH_HEADER in row), None)
    if header is not None:
        top = next((i for i in range(header, -1, -1) if rows[i].lstrip().startswith("┏")), None)
        bottom = next((i for i in range(header, len(rows)) if rows[i].lstrip().startswith("┗")),
                      None)
        if top is None:
            problems.append("dashboard without its top border")
        if bottom is None:
            # Still being drawn, or scrolled off: every row below the header
            # must belong to the panel.
            if any(row.strip() and not row.lstrip().startswith("┃") for row in rows[header:]):
                problems.append("dashboard without its bottom border")
        else:
            below = [row for row in rows[bottom + 1:] if row.strip()]
            if below:
                problems.append(f"text below the dashboard: {below[0].strip()[:60]!r}")
            if not rows[bottom].rstrip().endswith("┛"):
                problems.append("dashboard bottom border drawn only in part")
    return problems


def check(path: Path) -> list[str]:
    header, events = load(path)
    screen = pyte.Screen(header["width"], header["height"])
    stream = pyte.Stream(screen)
    problems = []
    last_progress = None
    for i, (t, kind, data) in enumerate(events):
        if kind != "o":
            continue
        stream.feed(data)
        rows = [row.rstrip() for row in screen.display]
        found = screen_problems(rows)
        match = next((m for m in map(PROGRESS.search, rows) if m), None)
        if match:
            progress = float(match.group(1))
            if last_progress is not None and progress < last_progress:
                found.append(f"global progress went back from {last_progress}% to {progress}%")
            last_progress = progress
        if any("0 B / 0 B" in row for row in rows):
            found.append("dashboard shows '0 B / 0 B'")
        for p in found:
            problems.append(f"event {i} (t={t:.2f}s): {p}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cast", type=Path)
    args = parser.parse_args()
    problems = check(args.cast)
    for p in problems:
        print(p)
    print(f"{args.cast}: {'clean' if not problems else f'{len(problems)} problem(s)'}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
