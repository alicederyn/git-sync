import sys
from asyncio import create_task, run
from os import environ
from typing import Optional

from .git import (
    GitError,
    fast_forward_merged_prs,
    fast_forward_to_downstream,
    fetch_and_fast_forward_to_upstream,
    get_branches_with_remote_upstreams,
    get_default_push_remote,
    get_remotes,
)
from .github import fetch_pull_requests


def github_token(domain: str) -> Optional[str]:
    envvar = domain.split(".")[0].upper() + "_TOKEN"
    return environ.get(envvar)


async def git_sync() -> None:
    push_remote = await get_default_push_remote()
    if push_remote:
        remotes = await get_remotes()
        if remotes:
            pull_request_task = create_task(
                fetch_pull_requests(github_token, [remote.url for remote in remotes])
            )

    try:
        branches = await get_branches_with_remote_upstreams()
    except GitError as e:
        # Probably not in a git directory, or some other misconfiguration.
        # git will already have written the problem to stderr.
        sys.exit(e.returncode)
    await fetch_and_fast_forward_to_upstream(branches)

    if push_remote:
        await fast_forward_to_downstream(push_remote, branches)

        if remotes:
            pull_requests = await pull_request_task
            push_remote_url = next(
                remote.url for remote in remotes if remote.name == push_remote
            )
            await fast_forward_merged_prs(push_remote_url, pull_requests)


def main() -> None:
    run(git_sync())
