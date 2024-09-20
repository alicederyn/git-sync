from asyncio.subprocess import PIPE, create_subprocess_exec
from collections.abc import Iterable
from dataclasses import dataclass

from .github import PullRequest

_ExecArg = bytes | str


class GitError(Exception):
    def __init__(self, args: Iterable[_ExecArg], returncode: int):
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
    """Return true if commit1 is an ancestor of commit2

    For instance, 2d406492de55 is merge #11 and 8ee9b133bb73 #12:
    >>> from asyncio import run
    >>> run(is_ancestor("2d406492de55", "8ee9b133bb73"))
    True
    >>> run(is_ancestor("8ee9b133bb73", "2d406492de55"))
    False
    """
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


async def fast_forward_merged_prs(
    push_remote_url: str, prs: Iterable[PullRequest]
) -> None:
    current_branch = await get_current_branch()
    current_branch = current_branch and current_branch[11:]
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
                branch_is_ancestor = await is_ancestor(branch_name, pr.branch_name)
            except GitError:
                pass  # Probably no longer have the commit hash
            else:
                if branch_is_ancestor:
                    print(f"Fast-forward {pr.branch_name} to {pr.merged_hash}")
                    if branch_name == current_branch:
                        await git("reset", "--hard", merged_hash)
                    else:
                        await git("branch", "--force", branch_name, merged_hash)
