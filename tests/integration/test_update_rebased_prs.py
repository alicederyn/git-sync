from git_sync.git import update_rebased_prs
from git_sync.github import PullRequest

from .gitutils import (
    all_branches,
    all_staged_changes,
    create_commit,
    setup_branches,
    setup_worktree,
    stage_changes,
)

REPO_URL = "https://github.com/example/example.git"  # Dummy URL for test


async def test_update_inactive_branch_to_rebased_pr_head() -> None:
    # Given an open PR rebased onto main on GitHub
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = create_commit(commit_a, other="C\n")
    commit_d = create_commit(commit_c, file="B\n")
    setup_branches(main=commit_c, my_pr=commit_b, active_branch="main")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        hashes=(commit_d,),
        merged_hash=None,
        superseded_heads=frozenset([commit_b]),
    )

    # When we update rebased PRs
    await update_rebased_prs(REPO_URL, [pr])

    # Then the PR branch is moved to the rebased PR head
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_d,
    }


async def test_update_active_branch_to_rebased_pr_head() -> None:
    # Given an open PR rebased onto main on GitHub, checked out locally
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = create_commit(commit_a, other="C\n")
    commit_d = create_commit(commit_c, file="B\n")
    setup_branches(main=commit_c, my_pr=commit_b, active_branch="my_pr")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        hashes=(commit_d,),
        merged_hash=None,
        superseded_heads=frozenset([commit_b]),
    )

    # When we update rebased PRs
    await update_rebased_prs(REPO_URL, [pr])

    # Then the PR branch is moved to the rebased PR head
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_d,
    }


async def test_staged_changes_not_lost() -> None:
    # Given staged changes over an open PR rebased onto main on GitHub
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = create_commit(commit_a, other="C\n")
    commit_d = create_commit(commit_c, file="B\n")
    setup_branches(main=commit_c, my_pr=commit_b, active_branch="my_pr")
    stage_changes(file="D\n")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        hashes=(commit_d,),
        merged_hash=None,
        superseded_heads=frozenset([commit_b]),
    )

    # When we update rebased PRs
    await update_rebased_prs(REPO_URL, [pr])

    # Then the active branch is unaffected
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_b,
    }
    # And the staged changes are preserved
    assert all_staged_changes() == {"file": "D\n"}


async def test_no_update_when_branch_has_additional_commits() -> None:
    # Given a local branch with commits not in any PR head
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = create_commit(commit_a, other="C\n")
    commit_d = create_commit(commit_c, file="B\n")
    commit_e = create_commit(commit_b, file="E\n")
    setup_branches(main=commit_c, my_pr=commit_e, active_branch="main")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        hashes=(commit_d,),
        merged_hash=None,
        superseded_heads=frozenset([commit_b]),
    )

    # When we update rebased PRs
    await update_rebased_prs(REPO_URL, [pr])

    # Then the PR branch is unaffected
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_e,
    }


async def test_skip_rebased_pr_branch_in_other_worktree() -> None:
    # Given an open PR rebased onto main on GitHub, checked out in another worktree
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = create_commit(commit_a, other="C\n")
    commit_d = create_commit(commit_c, file="B\n")
    setup_branches(main=commit_c, my_pr=commit_b, active_branch="main")
    setup_worktree("other_worktree", "my_pr")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        hashes=(commit_d,),
        merged_hash=None,
        superseded_heads=frozenset([commit_b]),
    )

    # When we update rebased PRs
    await update_rebased_prs(REPO_URL, [pr])

    # Then the PR branch is left alone
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_b,
    }
