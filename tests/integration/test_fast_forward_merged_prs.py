import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from git_sync.git import update_merged_prs
from git_sync.github import PullRequest

REPO_URL = "https://github.com/example/example.git"  # Dummy URL for test


def run_split_stdout(cmd: list[str]) -> list[str]:
    return subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.PIPE,
        encoding="utf-8",
    ).stdout.splitlines()


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
        yield
    finally:
        os.chdir(original_dir)


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


@pytest.mark.asyncio
async def test_delete_merged_inactive_pr_branch() -> None:
    # Given a merged PR
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    commit_d = create_commit(commit_b, file="C\n")
    setup_branches(
        main=commit_c, my_pr=commit_b, more_work=commit_d, active_branch="main"
    )
    setup_upstreams(my_pr="main", more_work="main")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        branch_hash=commit_b,
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is deleted
    assert all_branches() == {
        "main": commit_c,
        "more_work": commit_d,
    }


@pytest.mark.asyncio
async def test_force_inactive_upstream_branch_to_merged_commit() -> None:
    # Given a merged PR
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    commit_d = create_commit(commit_b, file="C\n")
    setup_branches(
        main=commit_c, my_pr=commit_b, more_work=commit_d, active_branch="main"
    )
    setup_upstreams(my_pr="main", more_work="my_pr")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        branch_hash=commit_b,
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is fast-forwarded to the merged commit
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_c,
        "more_work": commit_d,
    }


@pytest.mark.asyncio
async def test_merged_inactive_pr_branch_with_deletion_disabled() -> None:
    # Given a merged PR
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    commit_d = create_commit(commit_b, file="C\n")
    setup_branches(
        main=commit_c, my_pr=commit_b, more_work=commit_d, active_branch="main"
    )
    setup_upstreams(my_pr="main", more_work="main")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        branch_hash=commit_b,
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr], allow_delete=False)

    # Then the PR branch is fast-forwarded to the merged commit
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_c,
        "more_work": commit_d,
    }


@pytest.mark.asyncio
async def test_delete_merged_active_pr_branch() -> None:
    # Given a merged PR
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    commit_d = create_commit(commit_b, file="C\n")
    setup_branches(
        main=commit_c, my_pr=commit_b, more_work=commit_d, active_branch="my_pr"
    )
    setup_upstreams(my_pr="main", more_work="main")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        branch_hash=commit_b,
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is deleted
    assert all_branches() == {
        "main": commit_c,
        "more_work": commit_d,
    }
    # And the active branch is set to its upstream
    assert get_current_branch() == "main"


@pytest.mark.asyncio
async def test_force_active_upstream_branch_to_merged_commit() -> None:
    # Given a merged PR
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    commit_d = create_commit(commit_b, file="C\n")
    setup_branches(
        main=commit_c, my_pr=commit_b, more_work=commit_d, active_branch="my_pr"
    )
    setup_upstreams(my_pr="main", more_work="my_pr")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        branch_hash=commit_b,
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is fast-forwarded to the merged commit
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_c,
        "more_work": commit_d,
    }


@pytest.mark.asyncio
async def test_merged_active_upstream_branch_with_deletion_disabled() -> None:
    # Given a merged PR
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    commit_d = create_commit(commit_b, file="C\n")
    setup_branches(
        main=commit_c, my_pr=commit_b, more_work=commit_d, active_branch="my_pr"
    )
    setup_upstreams(my_pr="main", more_work="main")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        branch_hash=commit_b,
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr], allow_delete=False)

    # Then the PR branch is fast-forwarded to the merged commit
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_c,
        "more_work": commit_d,
    }


@pytest.mark.asyncio
async def test_staged_changes_not_lost() -> None:
    # Given staged changes over a merged PR
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    setup_branches(main=commit_c, my_pr=commit_b, active_branch="my_pr")
    stage_changes(file="C\n")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        branch_hash=commit_b,
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the active branch is unaffected
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_b,
    }
    # And the staged changes are preserved
    assert all_staged_changes() == {"file": "C\n"}


@pytest.mark.asyncio
async def test_unstaged_changes_to_committed_files_not_lost() -> None:
    # Given unstaged changes to committed files over a merged PR
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    setup_branches(main=commit_c, my_pr=commit_b, active_branch="my_pr")
    Path("file.txt").write_text("C\n")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        branch_hash=commit_b,
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the active branch is unaffected
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_b,
    }
    # And the unstaged changes are preserved
    assert Path("file.txt").read_text() == "C\n"


@pytest.mark.asyncio
async def test_fastforward_when_pr_had_additional_commits() -> None:
    # Given a merged PR with additional commits
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = create_commit(commit_b, file="C\n")
    commit_d = squash_merge(commit_a, commit_c)
    commit_e = create_commit(commit_b, file="D\n")
    setup_branches(
        main=commit_d, my_pr=commit_b, more_work=commit_e, active_branch="my_pr"
    )
    setup_upstreams(my_pr="main", more_work="my_pr")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        branch_hash=commit_c,
        merged_hash=commit_d,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is fast-forwarded to the merged commit
    assert all_branches() == {
        "main": commit_d,
        "my_pr": commit_d,
        "more_work": commit_e,
    }


@pytest.mark.asyncio
async def test_no_fastforward_when_branch_has_additional_commits() -> None:
    # Given a branch with additional commits
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = create_commit(commit_b, file="C\n")
    commit_d = squash_merge(commit_a, commit_c)
    setup_branches(main=commit_d, my_pr=commit_c, active_branch="my_pr")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        branch_hash=commit_b,
        merged_hash=commit_d,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is unaffected
    assert all_branches() == {
        "main": commit_d,
        "my_pr": commit_c,
    }
