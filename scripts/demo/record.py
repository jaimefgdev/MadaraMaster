#!/usr/bin/env python3
"""Record the README demo as an asciicast v2 file.

Everything happens inside a fresh temporary directory:

1. a small "secret-project" tree of throwaway files is created there;
2. the commands are typed into a pseudo-terminal with human-like delays:
   ``ls``, ``madara wipe secret-project`` (info panel, confirmation,
   dashboard, summary) and ``ls`` again to show the files are gone;
3. the session is written to ``docs/demo.cast`` (play it with
   ``asciinema play docs/demo.cast`` or render it with ``render_gif.py``).

Nothing outside the temporary directory is touched: HOME and
XDG_STATE_HOME point into it, so even the audit log lands there, and the
directory is removed at the end.  No TRIM is sent (``--trim`` is not used).

POSIX only (it uses the ``pty`` module).  Usage::

    python scripts/demo/record.py [--out docs/demo.cast]
"""

from __future__ import annotations

import argparse
import codecs
import fcntl
import json
import os
import pty
import select
import shutil
import struct
import sys
import tempfile
import termios
import time
from pathlib import Path

COLS, ROWS = 100, 34
PROMPT = "\x1b[1;32mdemo\x1b[0m:\x1b[1;34m~/tmp\x1b[0m$ "
TYPE_DELAY = 0.06
# Output pause that ends one burst (e.g. one dashboard repaint), in seconds.
QUIET = 0.02

# Throwaway files for the demo: name -> size in bytes.
FILES = {
    "contracts/q3-report.pdf": 96 * 1024 * 1024,
    "contracts/nda-signed.pdf": 6 * 1024 * 1024,
    "keys/id_ed25519": 411,
    "notes.txt": 2_048,
    "photos/passport.jpg": 18 * 1024 * 1024,
}


class Recorder:
    """Collects output events with timestamps relative to the start."""

    def __init__(self) -> None:
        self.start = time.monotonic()
        self.events: list[tuple[float, str]] = []

    def emit(self, text: str) -> None:
        self.events.append((round(time.monotonic() - self.start, 4), text))

    def type(self, text: str, delay: float = TYPE_DELAY) -> None:
        """Type *text* key by key, then press Enter (CR LF in one event, so
        no frame shows the cursor back at the start of the line)."""
        for ch in text:
            self.emit(ch)
            time.sleep(delay)
        self.emit("\r\n")

    def pause(self, seconds: float) -> None:
        time.sleep(seconds)

    def save(self, path: Path) -> None:
        header = {
            "version": 2,
            "width": COLS,
            "height": ROWS,
            "timestamp": 0,  # fixed, so the file does not change on every run
            "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
            "title": "MadaraMaster demo",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            f.write(json.dumps(header) + "\n")
            for t, text in self.events:
                f.write(json.dumps([t, "o", text]) + "\n")


def make_files(root: Path) -> None:
    for rel, size in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as f:
            remaining = size
            while remaining:
                chunk = min(remaining, 1 << 20)
                f.write(os.urandom(chunk))
                remaining -= chunk


def listing(root: Path) -> str:
    """A small `ls -R`-like listing of *root*, relative to its parent."""
    lines = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        rel = Path(dirpath).relative_to(root.parent)
        lines.append(f"\x1b[1;34m{rel}/\x1b[0m")
        for name in sorted(filenames):
            size = (Path(dirpath) / name).stat().st_size
            lines.append(f"  {name:<22} {size / 1024 / 1024:6.1f} MB" if size > 1 << 20
                         else f"  {name:<22} {size:6d} B")
    return "\r\n".join(lines) + "\r\n"


def run_in_pty(rec: Recorder, argv: list[str], cwd: Path, env: dict[str, str],
               answers: list[tuple[str, str]]) -> int:
    """Run *argv* in a pty, recording its output and typing *answers*.

    Each answer is ``(wait_for_text, text_to_type)``: when *wait_for_text*
    appears in the output, *text_to_type* is typed character by character.
    """
    pid, fd = pty.fork()
    if pid == 0:  # child
        os.chdir(cwd)
        os.execvpe(argv[0], argv, env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    pending = list(answers)
    seen = ""
    # Reads can split a multi-byte UTF-8 character; decoding each chunk on
    # its own would turn it into replacement characters (and wider lines).
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def pump(timeout: float) -> bool:
        """Record the output that arrives within *timeout*; False at EOF.

        A dashboard repaint is larger than one pty read (about 4 KB), so
        reads are joined until the output pauses: each repaint becomes a
        single event and no frame can show it half drawn.
        """
        nonlocal seen
        chunks = []
        eof = False
        ready, _, _ = select.select([fd], [], [], timeout)
        deadline = time.monotonic() + 0.25
        while ready:
            try:
                data = os.read(fd, 65536)
            except OSError:  # Linux: EIO once the child has exited
                data = b""
            if not data:
                eof = True
                break
            chunks.append(data)
            if time.monotonic() > deadline:
                break
            ready, _, _ = select.select([fd], [], [], QUIET)
        text = decoder.decode(b"".join(chunks))
        if text:
            rec.emit(text)
            seen += text
        return not eof

    while pump(0.05):
        if pending and pending[0][0] in seen:
            _, reply = pending.pop(0)
            seen = ""
            rec.pause(1.6)  # let the viewer read the prompt
            for ch in reply:
                key_time = time.monotonic() + TYPE_DELAY * 2
                os.write(fd, ch.encode())
                # Record the echo of every key, so the answer is seen being typed.
                pump(TYPE_DELAY * 2)
                time.sleep(max(0.0, key_time - time.monotonic()))
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("docs/demo.cast"))
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    tmp = Path(tempfile.mkdtemp(prefix="madara-demo-"))
    try:
        project = tmp / "secret-project"
        make_files(project)

        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp),
            "XDG_STATE_HOME": str(tmp / "state"),
            "TERM": "xterm-256color",
            # One column less than the pty: lines never end exactly at the last
            # column, where terminal emulators without deferred wrap (pyte,
            # used by render_gif.py) would scroll and leave dashboard
            # repaints one line short.
            "COLUMNS": str(COLS - 1),
            "LINES": str(ROWS),
            "LANG": "C.UTF-8",
            "PYTHONPATH": str(repo),
            "PYTHONIOENCODING": "utf-8",
        }
        madara = [sys.executable, "-m", "madaramaster"]

        rec = Recorder()
        rec.emit(PROMPT)
        rec.pause(0.8)
        rec.type("ls -R secret-project")
        rec.emit(listing(project))
        rec.emit(PROMPT)
        rec.pause(1.2)
        rec.type("madara wipe secret-project -s purge")
        code = run_in_pty(
            rec,
            [*madara, "wipe", "secret-project", "-s", "purge"],
            tmp,
            env,
            answers=[("Type the directory name", "secret-project\r")],
        )
        rec.pause(3.0)
        rec.emit(PROMPT)
        rec.pause(0.6)
        rec.type("ls secret-project")
        gone = not project.exists()
        rec.emit(
            "ls: cannot access 'secret-project': No such file or directory\r\n"
            if gone
            else listing(project)
        )
        rec.emit(PROMPT)
        rec.pause(2.5)
        rec.emit("")  # final timestamp keeps the last frame on screen

        rec.save(args.out)
        print(f"wrote {args.out} ({rec.events[-1][0]:.1f}s, exit code {code}, wiped={gone})")
        return 0 if code == 0 and gone else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
