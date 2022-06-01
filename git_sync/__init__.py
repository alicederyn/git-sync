import sys
from dataclasses import dataclass
from subprocess import PIPE, CalledProcessError, check_call, check_output, run
from typing import Iterable, List, Optional


@dataclass
class Branch:
    name: bytes
    upstream: bytes


def get_current_branch() -> Optional[bytes]:
    raw_bytes = run(["git", "symbolic-ref", "-q", "HEAD"], stdout=PIPE).stdout.strip()
    return raw_bytes if raw_bytes else None


def get_default_push_remote() -> Optional[bytes]:
    raw_bytes = run(["git", "config", "remote.pushdefault"], stdout=PIPE).stdout.strip()
    return raw_bytes if raw_bytes else None


def branches_with_remote_upstreams() -> List[Branch]:
    raw_bytes = check_output(["git", "branch", "--format=%(refname) %(upstream)"])
    return [
        Branch(name=name, upstream=upstream)
        for name, upstream in (line.split(b" ") for line in raw_bytes.splitlines())
        if upstream.startswith(b"refs/remotes/")
    ]


def get_remote_branches(remote: bytes) -> List[bytes]:
    return check_output(
        ["git", "branch", "--list", "-r", remote + b"/*", "--format=%(refname)"]
    ).splitlines()


def fast_forward_to_upstream(branches: Iterable[Branch]) -> None:
    fetch_args = [b.upstream + b":" + b.name for b in branches]
    if fetch_args:
        # Use run rather than check_call as fetch will exit with a non-zero code
        # if any branch cannot be fast-forwarded, which is not a failing state
        # for this tool
        run(["git", "fetch", ".", *fetch_args])


def fast_forward_to_downstream(branches: Iterable[Branch]) -> None:
    push_remote = get_default_push_remote()
    if not push_remote:
        return
    remote_branches = set(get_remote_branches(push_remote))
    for b in branches:
        # All branches start with refs/heads/
        short_branch_name = b.name[11:]
        remote = b"refs/remotes/" + push_remote + b"/" + short_branch_name
        if remote in remote_branches and b.upstream != remote:
            check_call(["git", "push", push_remote, short_branch_name])


def main() -> None:
    try:
        branches = branches_with_remote_upstreams()
    except CalledProcessError as e:
        # Probably not in a git directory, or some other misconfiguration.
        # git will already have written the problem to stderr.
        sys.exit(e.returncode)
    current_branch = get_current_branch()
    if any(b.name == current_branch for b in branches):
        check_call(["git", "pull", "--all"])
    else:
        check_call(["git", "fetch", "--all"])
    fast_forward_to_upstream(b for b in branches if b.name != current_branch)
    fast_forward_to_downstream(branches)
