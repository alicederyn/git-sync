from git_sync.git import (
    fetch_and_fast_forward_to_upstream,
    get_branches_with_remote_upstreams,
)

from .gitutils import (
    all_branches,
    create_commit,
    delete_remote_branch,
    setup_branches,
    setup_remote,
    setup_upstreams,
    setup_worktree,
)


async def test_fast_forward_despite_branch_in_other_worktree() -> None:
    # Given two branches behind their upstreams, one checked out in another worktree
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    setup_branches(main=commit_a, feat=commit_a, other=commit_a, active_branch="main")
    setup_remote("origin", feat=commit_b, other=commit_b)
    setup_upstreams(feat="origin/feat", other="origin/other")
    setup_worktree("other_worktree", "feat")

    # When we fast-forward to upstream
    await fetch_and_fast_forward_to_upstream(await get_branches_with_remote_upstreams())

    # Then only the branch not in another worktree is fast-forwarded
    assert all_branches() == {
        "main": commit_a,
        "feat": commit_a,
        "other": commit_b,
        "origin/feat": commit_b,
        "origin/other": commit_b,
    }


async def test_fast_forward_despite_upstream_gone() -> None:
    # Given two branches behind their upstreams, one with its upstream deleted
    commit_a = create_commit("main", file="A\n")
    commit_b = create_commit(commit_a, file="B\n")
    setup_branches(main=commit_a, feat=commit_a, other=commit_a, active_branch="main")
    setup_remote("origin", feat=commit_b, other=commit_b)
    setup_upstreams(feat="origin/feat", other="origin/other")
    delete_remote_branch("origin", "feat")

    # When we fast-forward to upstream
    await fetch_and_fast_forward_to_upstream(await get_branches_with_remote_upstreams())

    # Then the branch with an existing upstream is fast-forwarded
    assert all_branches() == {
        "main": commit_a,
        "feat": commit_a,
        "other": commit_b,
        "origin/other": commit_b,
    }
