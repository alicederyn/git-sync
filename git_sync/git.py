from asyncio.subprocess import DEVNULL, PIPE, create_subprocess_exec
from collections.abc import Iterable
from dataclasses import dataclass

from .github import PullRequest

_ExecArg = bytes | str


class GitError(Exception):
    def __init__(self, args: Iterable[_ExecArg], returncode: int) -> None:
        def tostr(arg: _ExecArg) -> str:
            return arg if isinstance(arg, str) else arg.decode(errors="replace")

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
        "for-each-ref", "--format=%(refname) %(upstream)", "refs/heads"
    )
    return [
        Branch(name=name, upstream=upstream, is_current=(name == current_branch))
        for name, upstream in (line.split(b" ") for line in raw_bytes.splitlines())
        if upstream.startswith(b"refs/remotes/")
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


async def is_ancestor(commit1: _ExecArg, commit2: _ExecArg) -> bool:
    """Return true if commit1 is an ancestor of commit2."""
    try:
        await git("merge-base", "--is-ancestor", commit1, commit2)
        return True
    except GitError as e:
        if e.returncode == 1:
            return False
        raise


async def fetch_and_fast_forward_to_upstream(branches: Iterable[Branch]) -> None:
    if any(b.is_current for b in branches):
        await git("pull", "--all")
    else:
        await git("fetch", "--all")
    fetch_args = [b.upstream + b":" + b.name for b in branches if not b.is_current]
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
    current_branch = await get_current_branch()
    current_branch = current_branch and current_branch[11:]
    if current_branch == branch_name:
        any_staged_changes = await git_output(
            "diff", "--cached", "--exit-code", check_return=False
        )
        if any_staged_changes:
            print(f"Staged changes on {branch_name.decode()}, skipping fast-forward")
            return
        any_unstaged_changes_to_committed_files = await git_output(
            "diff", "--exit-code", check_return=False
        )
        if any_unstaged_changes_to_committed_files:
            print(f"Unstaged changes on {branch_name.decode()}, skipping fast-forward")
            return
        if allow_delete and not await branch_is_an_upstream(branch_name):
            upstream = (await get_upstream_branch(branch_name)) or b"main"
            await git("checkout", upstream)
            await git("branch", "-D", branch_name)
        else:
            await git("reset", "--hard", merged_hash)
    else:  # noqa: PLR5501
        if allow_delete and not await branch_is_an_upstream(branch_name):
            await git("branch", "-D", branch_name)
        else:
            await git("branch", "--force", branch_name, merged_hash)
    print(f"Fast-forward {branch_name.decode()} to {merged_hash}")


async def update_merged_prs(
    push_remote_url: str, prs: Iterable[PullRequest], *, allow_delete: bool = True
) -> None:
    branch_hashes = await get_branch_hashes()
    for pr in prs:
        branch_name = pr.branch_name.encode("utf-8")
        merged_hash = pr.merged_hash
        if (
            merged_hash
            and branch_name in branch_hashes
            and merged_hash != branch_hashes[branch_name]
            and push_remote_url in pr.repo_urls
        ):
            try:
                branch_is_ancestor = await is_ancestor(branch_name, pr.branch_hash)
            except GitError:
                pass  # Probably no longer have the commit hash
            else:
                if branch_is_ancestor:
                    await update_merged_pr_branch(
                        branch_name=branch_name,
                        merged_hash=merged_hash,
                        allow_delete=allow_delete,
                    )
