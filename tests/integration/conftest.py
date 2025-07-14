import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def run_in_git_repo(tmp_path: Path) -> Iterator[None]:
    repo = tmp_path / "repo"
    repo.mkdir()
    original_dir = os.getcwd()
    try:
        os.chdir(repo)
        subprocess.run(["git", "init", "-b", "main"], check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "Initial commit"], check=True
        )
        subprocess.run(["git", "config", "advice.detachedHead", "false"], check=True)
        subprocess.run(["git", "config", "user.email", "ci@example.com"], check=True)
        subprocess.run(["git", "config", "user.name", "CI"], check=True)
        yield
    finally:
        os.chdir(original_dir)
