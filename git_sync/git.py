from asyncio.subprocess import PIPE, create_subprocess_exec
from dataclasses import dataclass
from typing import Iterable, List, Optional, Union

_ExecArg = Union[bytes, str]


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


async def get_current_branch() -> Optional[bytes]:
    raw_bytes = await git_output("symbolic-ref", "-q", "HEAD", check_return=False)
    return raw_bytes or None


async def get_default_push_remote() -> Optional[bytes]:
    raw_bytes = await git_output("config", "remote.pushdefault", check_return=False)
    return raw_bytes or None


async def get_branches_with_remote_upstreams() -> List[Branch]:
    current_branch = await get_current_branch()
    raw_bytes = await git_output(
        "for-each-ref", "--format=%(refname) %(upstream)", "refs/heads"
    )
    return [
        Branch(name=name, upstream=upstream, is_current=(name == current_branch))
        for name, upstream in (line.split(b" ") for line in raw_bytes.splitlines())
        if upstream.startswith(b"refs/remotes/")
    ]


async def get_remote_branches(remote: bytes) -> List[bytes]:
    raw_bytes = await git_output(
        "for-each-ref", "--format=%(refname)", b"refs/remotes/" + remote
    )
    return raw_bytes.splitlines()


async def fetch_and_fast_forward_to_upstream(branches: Iterable[Branch]) -> None:
    if any(b.is_current for b in branches):
        await git("pull", "--all")
    else:
        await git("fetch", "--all")
    fetch_args = [b.upstream + b":" + b.name for b in branches]
    if fetch_args:
        # Ignore return code as fetch will exit with a non-zero code if any
        # branch cannot be fast-forwarded, which is not a failing state for
        # this tool
        await git("fetch", ".", *fetch_args, check_return=False)


async def fast_forward_to_downstream(branches: Iterable[Branch]) -> None:
    push_remote = await get_default_push_remote()
    if not push_remote:
        return
    remote_branches = set(await get_remote_branches(push_remote))
    for b in branches:
        # All branches start with refs/heads/
        short_branch_name = b.name[11:]
        remote = b"refs/remotes/" + push_remote + b"/" + short_branch_name
        if remote in remote_branches and b.upstream != remote:
            await git("push", push_remote, short_branch_name)
