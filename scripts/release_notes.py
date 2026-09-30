#!/usr/bin/env python3
"""Write the GitHub Release notes for a tag from the commits since the previous tag.

Used by .github/workflows/release.yml::

    python scripts/release_notes.py --tag v5.1.0 --assets assets \\
        --repo jaimefgdev/MadaraMaster > notes.md

The notes contain:

* the non-merge commits between the previous ``v*`` tag and this one
  (the whole history for the first release);
* a link to the full diff;
* the SHA-256 of every file attached to the release;
* install instructions.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def previous_tag(tag: str, cwd: Path | None = None) -> str | None:
    """The closest ``v*`` tag reachable from the parent of *tag*, if any."""
    try:
        return _git("describe", "--tags", "--abbrev=0", "--match", "v*", f"{tag}^", cwd=cwd).strip()
    except subprocess.CalledProcessError:
        return None


def commits(tag: str, since: str | None, cwd: Path | None = None) -> list[tuple[str, str]]:
    """``(subject, short_sha)`` of the non-merge commits in ``since..tag``."""
    rev_range = f"{since}..{tag}" if since else tag
    out = _git("log", "--no-merges", "--pretty=format:%s%x1f%h", rev_range, cwd=cwd)
    return [tuple(line.split("\x1f", 1)) for line in out.splitlines() if line]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render(tag: str, repo: str, assets: Path, cwd: Path | None = None) -> str:
    version = tag[1:] if tag.startswith("v") else tag
    since = previous_tag(tag, cwd)
    lines = ["## Changes", ""]
    entries = commits(tag, since, cwd)
    lines += [f"- {subject} ({sha})" for subject, sha in entries] or ["- No changes."]
    lines.append("")
    if since:
        lines.append(f"**Full changelog:** https://github.com/{repo}/compare/{since}...{tag}")
    else:
        lines.append(f"**Full history:** https://github.com/{repo}/commits/{tag}")

    files = sorted(p for p in assets.iterdir() if p.is_file()) if assets.is_dir() else []
    if files:
        lines += ["", "## Downloads", "", "| File | SHA-256 |", "|------|---------|"]
        lines += [f"| `{p.name}` | `{sha256(p)}` |" for p in files]

    lines += [
        "",
        "## Install",
        "",
        "```bash",
        f"pip install madaramaster=={version}",
        "```",
        "",
        "Windows: download the `.exe` above; it runs with your own rights and never asks "
        "for elevation by itself.",
        "",
        "Read the README's Limitations section before relying on file-level wiping.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="Tag being released, e.g. v5.1.0")
    parser.add_argument("--repo", required=True, help="owner/name on GitHub")
    parser.add_argument("--assets", type=Path, default=Path("assets"), help="Release files")
    args = parser.parse_args(argv)
    sys.stdout.write(render(args.tag, args.repo, args.assets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
