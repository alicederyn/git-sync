import subprocess
from pathlib import Path


def run_split_stdout(cmd: list[str]) -> list[str]:
    return subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.PIPE,
        encoding="utf-8",
    ).stdout.splitlines()


def get_current_branch() -> str:
    return run_split_stdout(["git", "symbolic-ref", "-q", "HEAD"])[0].removeprefix(
        "refs/heads/"
    )


def stage_changes(**files: str) -> None:
    for filename, content in files.items():
        Path(filename + ".txt").write_text(content)
    subprocess.run(
        ["git", "add", *(filename + ".txt" for filename in files)], check=True
    )


def all_staged_changes() -> dict[str, str]:
    return {
        Path(filename).stem: Path(filename).read_text()
        for filename in run_split_stdout(["git", "diff", "--name-only", "--cached"])
    }


def create_commit(base_commit: str, **files: str) -> str:
    subprocess.run(["git", "checkout", base_commit], check=True)
    for filename, content in files.items():
        Path(filename + ".txt").write_text(content)
    subprocess.run(["git", "add", "*"], check=True)
    subprocess.run(["git", "commit", "-m", "commit"], check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode()


def squash_merge(base_commit: str, pr_commit: str) -> str:
    subprocess.run(["git", "checkout", base_commit], check=True)
    subprocess.run(["git", "merge", "--squash", pr_commit], check=True)
    subprocess.run(["git", "commit", "-m", "Squash commit"], check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"]).strip().decode()


def setup_branches(*, active_branch: str | None = None, **branches: str) -> None:
    # Put git into detached head state
    subprocess.run(["git", "checkout", "--detach", "-q"], check=True)
    # List all branches
    all_branches = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)"],
        check=True,
        stdout=subprocess.PIPE,
        encoding="utf-8",
    ).stdout.splitlines()
    # Delete all branches
    for branch in all_branches:
        subprocess.run(["git", "branch", "-q", "-D", branch], check=True)
    # Set up the branches as desired
    for branch_name, commit_hash in branches.items():
        subprocess.run(
            ["git", "checkout", "-q", commit_hash, "-b", branch_name], check=True
        )
    # Set the active branch, if any
    if active_branch:
        subprocess.run(["git", "checkout", "-q", active_branch], check=True)


def setup_upstreams(**upstreams: str) -> None:
    for branch_name, upstream in upstreams.items():
        subprocess.run(
            ["git", "branch", "--set-upstream-to", upstream, branch_name], check=True
        )


def all_branches() -> dict[str, str]:
    return {
        branch_name: subprocess.run(
            ["git", "rev-parse", branch_name],
            check=True,
            stdout=subprocess.PIPE,
            encoding="utf-8",
        ).stdout.strip()
        for branch_name in subprocess.run(
            ["git", "branch", "-a", "--format", "%(refname:short)"],
            check=True,
            stdout=subprocess.PIPE,
            encoding="utf-8",
        ).stdout.splitlines()
    }
