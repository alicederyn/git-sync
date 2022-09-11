import sys
from asyncio import run
from subprocess import CalledProcessError

from .git import (
    fast_forward_to_downstream,
    fetch_and_fast_forward_to_upstream,
    get_branches_with_remote_upstreams,
)


async def git_sync() -> None:
    try:
        branches = get_branches_with_remote_upstreams()
    except CalledProcessError as e:
        # Probably not in a git directory, or some other misconfiguration.
        # git will already have written the problem to stderr.
        sys.exit(e.returncode)
    fetch_and_fast_forward_to_upstream(branches)
    fast_forward_to_downstream(branches)


def main() -> None:
    run(git_sync())
