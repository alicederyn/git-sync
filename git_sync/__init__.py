import sys
from argparse import ArgumentParser, Namespace
from asyncio import create_task, run
from os import environ

from .git import (
    GitError,
    Remote,
    fast_forward_to_downstream,
    fetch_and_fast_forward_to_upstream,
    get_branches_with_remote_upstreams,
    get_default_push_remote,
    get_remotes,
    in_git_repo,
    update_merged_prs,
)
from .github import fetch_pull_requests, repos_by_domain


def github_token_envvar(domain: str) -> str:
    return domain.split(".")[0].upper() + "_TOKEN"


def github_token(domain: str) -> str | None:
    return environ.get(github_token_envvar(domain))


def get_description(
    is_in_git_repo: bool,
    push_remote: bytes | None,
    remotes: list[Remote],
    domains: list[str],
) -> str:
    description = "Synchronize with remote repositories."
    if not is_in_git_repo:
        description += "\nRun --help inside a git repository to see what will be done."
        return description

    description += "\nPulls all remotes, including updating the current branch if safe."
    if push_remote and any(remote.name != push_remote for remote in remotes):
        description += f"\nPushes any upstream changes to {push_remote.decode()}."
    if domains:
        domains_with_tokens = sorted(
            domain for domain in domains if github_token(domain)
        )
        domains_without_tokens = sorted(
            domain for domain in domains if not github_token(domain)
        )
        if domains_with_tokens:
            description += (
                "\nMerged PR branches will be fast-forwarded or, if safe, deleted."
            )
        if domains_without_tokens:
            description += "\n"
            description += "Full github" if domains_with_tokens else "Github"
            description += " integration can be enabled by setting "
            env_vars = [
                "$" + github_token_envvar(domain) for domain in domains_without_tokens
            ]
            description += ", ".join(env_vars)
            description += "."
    description += (
        "\n(NOTE: These behaviours are based on the current repository and environment"
        " variables. Run --help inside another repository to determine the behaviour"
        " there.)"
    )
    return description


def get_command_line_args(description: str) -> Namespace:
    parser = ArgumentParser(description=description)
    parser.add_argument(
        "--no-delete",
        action="store_false",
        help="Never delete branches",
        default=True,
        dest="allow_delete",
    )
    return parser.parse_args()


async def git_sync() -> None:
    is_in_git_repo = await in_git_repo()

    push_remote = (await get_default_push_remote()) if is_in_git_repo else None
    remotes: list[Remote] = []
    remote_urls: list[str] = []
    if push_remote:
        remotes = await get_remotes()
        remote_urls = [remote.url for remote in remotes]
    domains = sorted(repos_by_domain(remote_urls).keys())

    description = get_description(is_in_git_repo, push_remote, remotes, domains)
    args = get_command_line_args(description)

    if not is_in_git_repo:
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(2)

    if remote_urls:
        pull_request_task = create_task(fetch_pull_requests(github_token, remote_urls))

    try:
        branches = await get_branches_with_remote_upstreams()
    except GitError as e:
        # Probably not in a git directory, or some other misconfiguration.
        # git will already have written the problem to stderr.
        sys.exit(e.returncode)
    await fetch_and_fast_forward_to_upstream(branches)

    if push_remote:
        await fast_forward_to_downstream(push_remote, branches)

        if remote_urls:
            pull_requests = await pull_request_task
            push_remote_url = next(
                remote.url for remote in remotes if remote.name == push_remote
            )
            await update_merged_prs(
                push_remote_url, pull_requests, allow_delete=args.allow_delete
            )


def main() -> None:
    run(git_sync())
