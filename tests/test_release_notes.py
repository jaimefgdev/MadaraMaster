"""scripts/release_notes.py — release notes from the commits since the previous tag.

Runs git only inside a temporary repository created in ``tmp_path``.
"""

import hashlib
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release_notes.py"
spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}
# Independent of the developer's git config (signing, default branch, hooks).
GIT_OPTS = ["-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "core.hooksPath="]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    env = dict(os.environ, **GIT_ENV)

    def git(*args):
        subprocess.run(
            ["git", *GIT_OPTS, *args], cwd=root, env=env, check=True, capture_output=True
        )

    def commit(message):
        git("commit", "--allow-empty", "-m", message)

    git("init", "-q")
    git("checkout", "-q", "-b", "main")
    commit("feat: first feature")
    commit("fix: first fix")
    git("tag", "v1.0.0")
    commit("feat: second feature")
    git("checkout", "-q", "-b", "topic")
    commit("fix: from a branch")
    git("checkout", "-q", "main")
    git("merge", "-q", "--no-ff", "topic", "-m", "Merge branch topic")
    git("tag", "v1.1.0")
    return root


def test_notes_list_commits_since_previous_tag(repo, tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "madaramaster-1.1.0-py3-none-any.whl").write_bytes(b"wheel")
    (assets / "MadaraMaster-1.1.0-windows-x64.exe").write_bytes(b"exe")

    notes = release_notes.render("v1.1.0", "owner/repo", assets, cwd=repo)

    assert "- feat: second feature (" in notes
    assert "- fix: from a branch (" in notes
    assert "first feature" not in notes and "first fix" not in notes
    assert "Merge branch" not in notes
    assert "https://github.com/owner/repo/compare/v1.0.0...v1.1.0" in notes
    assert hashlib.sha256(b"exe").hexdigest() in notes
    assert "`MadaraMaster-1.1.0-windows-x64.exe`" in notes
    assert "pip install madaramaster==1.1.0" in notes


def test_first_release_covers_the_whole_history(repo, tmp_path):
    notes = release_notes.render("v1.0.0", "owner/repo", tmp_path / "none", cwd=repo)
    assert "- feat: first feature (" in notes
    assert "- fix: first fix (" in notes
    assert "second feature" not in notes
    assert "https://github.com/owner/repo/commits/v1.0.0" in notes
    assert "## Downloads" not in notes


def test_previous_tag_ignores_non_release_tags(repo):
    subprocess.run(
        ["git", *GIT_OPTS, "tag", "not-a-release", "v1.1.0^"], cwd=repo, check=True,
        env=dict(os.environ, **GIT_ENV),
    )
    assert release_notes.previous_tag("v1.1.0", cwd=repo) == "v1.0.0"
