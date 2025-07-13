from pathlib import Path

import pytest

from git_sync.git import update_merged_prs
from git_sync.github import PullRequest

from .gitutils import (
    all_branches,
    all_staged_changes,
    create_commit,
    get_current_branch,
    setup_branches,
    setup_upstreams,
    squash_merge,
    stage_changes,
)

REPO_URL = "https://github.com/example/example.git"  # Dummy URL for test


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
