import shutil
import subprocess

import pytest

from debugagent.scanner.history import mine_history
from debugagent.scanner.languages import scan_services

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(mini_system):
    _git(mini_system, "init", "-q")
    _git(mini_system, "config", "user.email", "t@example.com")
    _git(mini_system, "config", "user.name", "t")
    _git(mini_system, "add", "-A")
    _git(mini_system, "commit", "-qm", "initial")
    target = mini_system / "services/billing/app/client.py"
    for i, msg in enumerate([
        "fix: handle None customer",
        "Fix NoneType on missing address",
        "bugfix: null invoice total",
        "fix: UTC offset in due date",
        "feat: add export",
    ]):
        target.write_text(f"# {i}\n")
        _git(mini_system, "commit", "-qam", msg)
    return mini_system


def test_counts_fix_commits_by_tag_per_service(repo):
    h = mine_history(repo, scan_services(repo))
    assert h["billing"]["null"] == 3
    assert h["billing"]["timezone"] == 1
    assert "orders" not in h or h["orders"] == {}


def test_non_git_dir_returns_empty(mini_system):
    assert mine_history(mini_system, scan_services(mini_system)) == {}
