import os
from asyncio.subprocess import DEVNULL, PIPE, create_subprocess_exec
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .github import PullRequest

_ExecArg = bytes | str | Path


class GitError(Exception):
    def __init__(self, args: Iterable[_ExecArg], returncode: int) -> None:
        def tostr(arg: _ExecArg) -> str:
            return arg.decode(errors="replace") if isinstance(arg, bytes) else str(arg)

        super().__init__(
            f"""git {" ".join(tostr(a) for a in args)} failed (code {returncode})"""
        )
        self.returncode = returncode


async def git(*args: _ExecArg, check_return: bool = True) -> None:
    """Call git"""
    proc = await create_subprocess_exec("git", *args)
    returncode = await proc.wait()
    if returncode != 0 and check_return:
        raise GitError(args, returncode)


async def git_output(*args: _ExecArg, check_return: bool = True) -> bytes:
    """Call git and return stdout"""
    proc = await create_subprocess_exec("git", *args, stdout=PIPE)
    assert proc.stdout  # work around typeshed limitation
    stdout = await proc.stdout.read()
    returncode = await proc.wait()
    if returncode != 0 and check_return:
        raise GitError(args, returncode)
    return stdout.rstrip(b"\r\n")


@dataclass
class Branch:
    name: bytes
    upstream: bytes
    is_current: bool


async def in_git_repo() -> bool:
    proc = await create_subprocess_exec(
        "git", "rev-parse", "--is-inside-work-tree", stdout=DEVNULL, stderr=DEVNULL
    )
    return await proc.wait() == 0


async def get_current_branch() -> bytes | None:
    raw_bytes = await git_output("symbolic-ref", "-q", "HEAD", check_return=False)
    return raw_bytes or None


async def get_default_push_remote() -> bytes | None:
    raw_bytes = await git_output("config", "remote.pushdefault", check_return=False)
    return raw_bytes or None


async def get_branch_hashes() -> dict[bytes, str]:
    raw_bytes = await git_output(
        "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"
    )
    return {
        ref[11:]: hash.decode("ascii")
        for (ref, hash) in (line.split(b" ") for line in raw_bytes.splitlines())
    }


async def get_branches_with_remote_upstreams() -> list[Branch]:
    current_branch = await get_current_branch()
    raw_bytes = await git_output(
        "for-each-ref",
        "--format=%(refname) %(upstream) %(upstream:track,nobracket)",
        "refs/heads",
    )
    return [
        Branch(name=name, upstream=upstream, is_current=(name == current_branch))
        for name, upstream, track in (
            line.split(b" ", maxsplit=2) for line in raw_bytes.splitlines()
        )
        if upstream.startswith(b"refs/remotes/") and track != b"gone"
    ]


@dataclass
class Remote:
    name: bytes
    url: str


async def get_remotes() -> list[Remote]:
    raw_bytes = await git_output(
        "config", "--get-regexp", r"remote\..*\.url", check_return=False
    )
    return [
        Remote(name=name[7:-4], url=url.decode("ascii"))
        for (name, url) in (line.split(b" ") for line in raw_bytes.splitlines())
    ]


async def get_remote_branches(remote: bytes) -> list[bytes]:
    raw_bytes = await git_output(
        "for-each-ref", "--format=%(refname)", b"refs/remotes/" + remote
    )
    return raw_bytes.splitlines()


async def fetch_and_fast_forward_to_upstream(branches: Iterable[Branch]) -> None:
    if any(b.is_current for b in branches):
        await git("pull", "--all")
    else:
        await git("fetch", "--all")
    locked_branches = await get_branches_locked_by_worktrees()
    fetch_args = [
        b.upstream + b":" + b.name
        for b in branches
        if not b.is_current
        and b.name.removeprefix(b"refs/heads/") not in locked_branches
    ]
    if fetch_args:
        # Ignore return code as fetch will exit with a non-zero code if any
        # branch cannot be fast-forwarded, which is not a failing state for
        # this tool
        await git("fetch", ".", *fetch_args, check_return=False)


async def fast_forward_to_downstream(
    push_remote: bytes, branches: Iterable[Branch]
) -> None:
    remote_branches = set(await get_remote_branches(push_remote))
    for b in branches:
        # All branches start with refs/heads/
        short_branch_name = b.name[11:]
        remote = b"refs/remotes/" + push_remote + b"/" + short_branch_name
        if remote in remote_branches and b.upstream != remote:
            await git("push", push_remote, short_branch_name)


async def get_upstream_branch(branch_name: bytes) -> bytes | None:
    upstream = await git_output(
        "for-each-ref", "--format=%(upstream)", b"refs/heads/" + branch_name
    )
    if upstream and upstream.startswith(b"refs/heads/"):
        return upstream.removeprefix(b"refs/heads/")
    return None


async def branch_is_an_upstream(branch_name: bytes) -> bool:
    """Return true if the branch is upstream of any other branch."""
    upstreams = await git_output("for-each-ref", "--format=%(upstream)", "refs/heads")
    upstream_heads = {
        upstream.removeprefix(b"refs/heads/")
        for upstream in upstreams.strip().splitlines()
    }
    return branch_name in upstream_heads


async def has_uncommitted_changes(branch_name: bytes) -> bool:
    """Return true, and print why, if there are staged or unstaged changes."""
    any_staged_changes = await git_output(
        "diff", "--cached", "--exit-code", check_return=False
    )
    if any_staged_changes:
        print(f"Staged changes on {branch_name.decode()}, skipping fast-forward")
        return True
    any_unstaged_changes_to_committed_files = await git_output(
        "diff", "--exit-code", check_return=False
    )
    if any_unstaged_changes_to_committed_files:
        print(f"Unstaged changes on {branch_name.decode()}, skipping fast-forward")
        return True
    return False


async def get_current_branch_name() -> bytes | None:
    current_branch = await get_current_branch()
    return current_branch and current_branch[11:]


@dataclass
class Worktree:
    path: Path
    branch: bytes | None
    is_detached: bool
    is_prunable: bool


async def get_worktrees() -> list[Worktree]:
    raw_bytes = await git_output("worktree", "list", "--porcelain", "-z")
    worktrees = []
    for record in raw_bytes.split(b"\0\0"):
        # partition, not split, as some attributes (e.g. "detached") have no value
        attributes = {
            key: value
            for key, _, value in (
                attribute.partition(b" ") for attribute in record.split(b"\0")
            )
        }
        if b"worktree" not in attributes:
            continue
        branch = attributes.get(b"branch")
        worktrees.append(
            Worktree(
                path=Path(os.fsdecode(attributes[b"worktree"])),
                branch=branch and branch.removeprefix(b"refs/heads/"),
                is_detached=b"detached" in attributes,
                is_prunable=b"prunable" in attributes,
            )
        )
    return worktrees


def read_state_file(path: Path) -> bytes | None:
    try:
        return path.read_bytes().strip()
    except FileNotFoundError:
        return None


def read_rebased_branch(head_name_path: Path) -> bytes | None:
    ref = read_state_file(head_name_path)
    if ref and ref.startswith(b"refs/heads/"):
        return ref.removeprefix(b"refs/heads/")
    return None


async def get_branches_being_rebased_or_bisected(worktree_path: Path) -> set[bytes]:
    # Same state files as git's contrib/completion/git-prompt.sh
    state_file_paths = await git_output(
        "-C",
        worktree_path,
        "rev-parse",
        "--path-format=absolute",
        "--git-path",
        "rebase-merge/head-name",
        "--git-path",
        "rebase-apply/head-name",
        "--git-path",
        "BISECT_START",
    )
    rebase_merge, rebase_apply, bisect_start = (
        Path(os.fsdecode(path)) for path in state_file_paths.splitlines()
    )
    branches = {
        read_rebased_branch(rebase_merge),
        read_rebased_branch(rebase_apply),
        read_state_file(bisect_start),
    }
    return {branch for branch in branches if branch}


async def get_branches_locked_by_worktrees() -> set[bytes]:
    """Return branches that git refuses to update, except the current branch."""
    locked_branches: set[bytes] = set()
    for worktree in await get_worktrees():
        if worktree.branch:
            locked_branches.add(worktree.branch)
        elif worktree.is_detached and not worktree.is_prunable:
            locked_branches |= await get_branches_being_rebased_or_bisected(
                worktree.path
            )
    if current_branch := await get_current_branch_name():
        locked_branches.discard(current_branch)
    return locked_branches


async def update_merged_pr_branch(
    branch_name: bytes,
    merged_hash: str,
    *,
    allow_delete: bool = True,
) -> None:
    """Delete or fast-forward a merged PR branch.

    If there are any uncommitted changes on the branch, it will be skipped.
    If the branch is not an upstream of any other branch, it will be deleted.
    """
    if await get_current_branch_name() == branch_name:
        if await has_uncommitted_changes(branch_name):
            return
        if allow_delete and not await branch_is_an_upstream(branch_name):
            upstream = (await get_upstream_branch(branch_name)) or b"main"
            if upstream in await get_branches_locked_by_worktrees():
                await git("checkout", "--detach", upstream)
            else:
                await git("checkout", upstream)
            await git("branch", "-D", branch_name)
        else:
            await git("reset", "--hard", merged_hash)
    else:
        if allow_delete and not await branch_is_an_upstream(branch_name):
            await git("branch", "-D", branch_name)
        else:
            await git("branch", "--force", branch_name, merged_hash)
    print(f"Fast-forward {branch_name.decode()} to {merged_hash}")


async def update_merged_prs(
    push_remote_url: str, prs: Iterable[PullRequest], *, allow_delete: bool = True
) -> None:
    branch_hashes = await get_branch_hashes()
    locked_branches = await get_branches_locked_by_worktrees()
    for pr in prs:
        branch_name = pr.branch_name.encode("utf-8")
        merged_hash = pr.merged_hash
        if (
            merged_hash
            and branch_name in branch_hashes
            and branch_name not in locked_branches
            and (
                branch_hashes[branch_name] in pr.hashes
                or branch_hashes[branch_name] in pr.superseded_heads
            )
            and push_remote_url in pr.repo_urls
        ):
            await update_merged_pr_branch(
                branch_name=branch_name,
                merged_hash=merged_hash,
                allow_delete=allow_delete,
            )


def is_stale_merged_fork_branch(pr: PullRequest, push_remote_url: str) -> bool:
    """Return true if the PR branch is in our fork and unchanged since the merge.

    Restricted to cross-repository PRs so that we never delete a branch from a
    repository shared with colleagues.
    """
    return (
        pr.merged_hash is not None
        and pr.is_cross_repository
        and push_remote_url in pr.repo_urls
        and bool(pr.hashes)
        and pr.head_hash == pr.hashes[0]
    )


async def delete_merged_remote_branches(
    push_remote: bytes, push_remote_url: str, prs: Iterable[PullRequest]
) -> None:
    """Delete branches of merged PRs from our fork.

    GitHub is normally configured to do this on merge, but not every merge respects
    that setting.
    """
    branch_names = [
        pr.branch_name for pr in prs if is_stale_merged_fork_branch(pr, push_remote_url)
    ]
    if not branch_names:
        return
    remote = push_remote.decode()
    for branch_name in branch_names:
        print(f"Deleting {branch_name} from {remote}")
    # A branch may have been deleted since we queried the API; git will report
    # any failures itself, and the rest of the deletions still apply
    await git("push", push_remote, "--delete", *branch_names, check_return=False)


async def commit_exists(commit_hash: str) -> bool:
    proc = await create_subprocess_exec(
        "git", "cat-file", "-e", commit_hash + "^{commit}", stderr=DEVNULL
    )
    return await proc.wait() == 0


async def update_rebased_pr_branch(branch_name: bytes, head_hash: str) -> None:
    """Move a branch from a superseded PR head to the current PR head.

    If there are any uncommitted changes on the branch, it will be skipped.
    """
    if not await commit_exists(head_hash):
        return
    if await get_current_branch_name() == branch_name:
        if await has_uncommitted_changes(branch_name):
            return
        await git("reset", "--hard", head_hash)
    else:
        await git("branch", "--force", branch_name, head_hash)
    print(f"Update rebased {branch_name.decode()} to {head_hash}")


async def update_rebased_prs(push_remote_url: str, prs: Iterable[PullRequest]) -> None:
    branch_hashes = await get_branch_hashes()
    locked_branches = await get_branches_locked_by_worktrees()
    for pr in prs:
        branch_name = pr.branch_name.encode("utf-8")
        if (
            pr.hashes
            and branch_name in branch_hashes
            and branch_name not in locked_branches
            and branch_hashes[branch_name] in pr.superseded_heads
            and push_remote_url in pr.repo_urls
        ):
            await update_rebased_pr_branch(
                branch_name=branch_name, head_hash=pr.hashes[0]
            )
