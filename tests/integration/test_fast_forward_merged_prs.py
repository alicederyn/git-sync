from pathlib import Path

from git_sync.git import update_merged_prs
from git_sync.github import PullRequest

from .gitutils import (
    all_branches,
    all_staged_changes,
    create_commit,
    get_current_branch,
    get_head,
    setup_branches,
    setup_upstreams,
    setup_worktree,
    squash_merge,
    stage_changes,
    start_bisect,
    start_rebase,
)

REPO_URL = "https://github.com/example/example.git"  # Dummy URL for test


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
        hashes=(commit_b,),
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is deleted
    assert all_branches() == {
        "main": commit_c,
        "more_work": commit_d,
    }


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
        hashes=(commit_b,),
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
        hashes=(commit_b,),
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
        hashes=(commit_b,),
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
        hashes=(commit_b,),
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
        hashes=(commit_b,),
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
        hashes=(commit_b,),
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
        hashes=(commit_b,),
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
        hashes=(commit_c, commit_b),
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
        hashes=(commit_b,),
        merged_hash=commit_d,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is unaffected
    assert all_branches() == {
        "main": commit_d,
        "my_pr": commit_c,
    }


async def test_fastforward_when_branch_is_at_superseded_pr_head() -> None:
    # Given a merged PR that was rebased on GitHub before merging
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = create_commit(commit_a, other="C\n")
    commit_d = create_commit(commit_c, file="B\n")
    commit_e = squash_merge(commit_c, commit_d)
    setup_branches(main=commit_e, my_pr=commit_b, active_branch="main")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        hashes=(commit_d,),
        merged_hash=commit_e,
        superseded_heads=frozenset([commit_b]),
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr], allow_delete=False)

    # Then the PR branch is fast-forwarded to the merged commit
    assert all_branches() == {
        "main": commit_e,
        "my_pr": commit_e,
    }


async def test_skip_merged_pr_branch_in_other_worktree() -> None:
    # Given a merged PR, checked out in another worktree
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    setup_branches(main=commit_c, my_pr=commit_b, active_branch="main")
    setup_upstreams(my_pr="main")
    setup_worktree("other_worktree", "my_pr")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        hashes=(commit_b,),
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is left alone
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_b,
    }


async def test_detach_head_when_upstream_is_in_other_worktree() -> None:
    # Given a merged PR, checked out, with its upstream checked out in another worktree
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    setup_branches(main=commit_c, my_pr=commit_b, active_branch="my_pr")
    setup_upstreams(my_pr="main")
    setup_worktree("other_worktree", "main")
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        hashes=(commit_b,),
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is deleted
    assert all_branches() == {"main": commit_c}
    # And HEAD is detached at the upstream
    assert get_head() == commit_c


async def test_skip_merged_pr_branch_being_rebased_in_other_worktree() -> None:
    # Given a merged PR, being rebased in another worktree
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    setup_branches(main=commit_c, my_pr=commit_b, active_branch="main")
    setup_upstreams(my_pr="main")
    start_rebase(cwd=setup_worktree("other_worktree", "my_pr"))
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        hashes=(commit_b,),
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is left alone
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_b,
    }


async def test_skip_merged_pr_branch_being_bisected_in_other_worktree() -> None:
    # Given a merged PR, being bisected in another worktree
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    setup_branches(main=commit_c, my_pr=commit_b, active_branch="main")
    setup_upstreams(my_pr="main")
    start_bisect(cwd=setup_worktree("other_worktree", "my_pr"))
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        hashes=(commit_b,),
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is left alone
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_b,
    }


async def test_skip_merged_pr_branch_being_rebased_in_current_worktree() -> None:
    # Given a merged PR, being rebased in the current worktree
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    setup_branches(main=commit_c, my_pr=commit_b, active_branch="my_pr")
    setup_upstreams(my_pr="main")
    start_rebase()
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([REPO_URL]),
        hashes=(commit_b,),
        merged_hash=commit_c,
    )

    # When we update merged PRs
    await update_merged_prs(REPO_URL, [pr])

    # Then the PR branch is left alone
    assert all_branches() == {
        "main": commit_c,
        "my_pr": commit_b,
    }
