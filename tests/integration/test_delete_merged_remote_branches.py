from git_sync.git import delete_merged_remote_branches
from git_sync.github import PullRequest

from .gitutils import (
    create_commit,
    remote_branches,
    setup_branches,
    setup_remote,
    squash_merge,
)

FORK_URL = "https://github.com/me/example.git"  # Dummy URL for test
PUSH_REMOTE = b"origin"


def merged_fork_pr(*, hashes: tuple[str, ...], head_hash: str | None) -> PullRequest:
    return PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([FORK_URL]),
        hashes=hashes,
        merged_hash="merge",
        head_hash=head_hash,
        is_cross_repository=True,
    )


async def test_delete_unchanged_merged_fork_branch() -> None:
    # Given a merged PR whose fork branch is still at the merged commit
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    setup_branches(main=commit_c, active_branch="main")
    setup_remote("origin", main=commit_c, my_pr=commit_b)
    pr = merged_fork_pr(hashes=(commit_b,), head_hash=commit_b)

    # When we delete merged remote branches
    await delete_merged_remote_branches(PUSH_REMOTE, FORK_URL, [pr])

    # Then the fork branch is deleted
    assert remote_branches("origin") == {"main": commit_c}


async def test_keep_fork_branch_with_commits_added_since_merge() -> None:
    # Given a merged PR whose fork branch has moved on
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    commit_d = create_commit(commit_b, file="C\n")
    setup_branches(main=commit_c, active_branch="main")
    setup_remote("origin", main=commit_c, my_pr=commit_d)
    pr = merged_fork_pr(hashes=(commit_b,), head_hash=commit_d)

    # When we delete merged remote branches
    await delete_merged_remote_branches(PUSH_REMOTE, FORK_URL, [pr])

    # Then the fork branch is left alone
    assert remote_branches("origin") == {"main": commit_c, "my_pr": commit_d}


async def test_keep_already_deleted_fork_branch() -> None:
    # Given a merged PR whose branch has already been deleted
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    setup_branches(main=commit_c, active_branch="main")
    setup_remote("origin", main=commit_c, my_pr=commit_b)
    pr = merged_fork_pr(hashes=(commit_b,), head_hash=None)

    # When we delete merged remote branches
    await delete_merged_remote_branches(PUSH_REMOTE, FORK_URL, [pr])

    # Then the identically named remote branch is left alone
    assert remote_branches("origin") == {"main": commit_c, "my_pr": commit_b}


async def test_keep_branch_from_same_repository() -> None:
    """A branch in the PR's target repository may belong to a colleague."""
    # Given a merged PR raised from a branch in the target repository
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    setup_branches(main=commit_c, active_branch="main")
    setup_remote("origin", main=commit_c, my_pr=commit_b)
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([FORK_URL]),
        hashes=(commit_b,),
        merged_hash="merge",
        head_hash=commit_b,
        is_cross_repository=False,
    )

    # When we delete merged remote branches
    await delete_merged_remote_branches(PUSH_REMOTE, FORK_URL, [pr])

    # Then the branch is left alone
    assert remote_branches("origin") == {"main": commit_c, "my_pr": commit_b}


async def test_keep_branch_in_another_repository() -> None:
    # Given a merged PR raised from a fork that is not our push remote
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    commit_c = squash_merge(commit_a, commit_b)
    setup_branches(main=commit_c, active_branch="main")
    setup_remote("origin", main=commit_c, my_pr=commit_b)
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset(["https://github.com/someone-else/example.git"]),
        hashes=(commit_b,),
        merged_hash="merge",
        head_hash=commit_b,
        is_cross_repository=True,
    )

    # When we delete merged remote branches
    await delete_merged_remote_branches(PUSH_REMOTE, FORK_URL, [pr])

    # Then the identically named branch on our push remote is left alone
    assert remote_branches("origin") == {"main": commit_c, "my_pr": commit_b}


async def test_keep_unmerged_fork_branch() -> None:
    # Given an unmerged PR
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    setup_branches(main=commit_a, active_branch="main")
    setup_remote("origin", main=commit_a, my_pr=commit_b)
    pr = PullRequest(
        branch_name="my_pr",
        repo_urls=frozenset([FORK_URL]),
        hashes=(commit_b,),
        merged_hash=None,
        head_hash=commit_b,
        is_cross_repository=True,
    )

    # When we delete merged remote branches
    await delete_merged_remote_branches(PUSH_REMOTE, FORK_URL, [pr])

    # Then the fork branch is left alone
    assert remote_branches("origin") == {"main": commit_a, "my_pr": commit_b}
