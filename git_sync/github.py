import re
import ssl
from asyncio import Semaphore, gather
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, TypeVar

import aiohttp
import truststore
from aiographql.client import GraphQLClient  # type: ignore[import-untyped]

T = TypeVar("T")


@dataclass(frozen=True)
class Repository:
    domain: str
    owner: str
    name: str


HTTPS_URL = re.compile(r"^https://([^/]*)/([^/]*)/([^/]*)\.git$")
GIT_URL = re.compile(r"^git@([^:]*):([^/]*)/([^/]*)\.git$")


def parse_repo_url(url: str) -> Repository | None:
    """Parse a GitHub repository URL

    >>> parse_repo_url("https://github.com/alicederyn/git-sync.git")
    Repository(domain='github.com', owner='alicederyn', name='git-sync')
    >>> parse_repo_url("git@github.com:alicederyn/git-graph-branch.git")
    Repository(domain='github.com', owner='alicederyn', name='git-graph-branch')
    """
    m = HTTPS_URL.match(url)
    if m:
        return Repository(*m.groups())
    m = GIT_URL.match(url)
    if m:
        return Repository(*m.groups())
    return None


def repos_by_domain(urls: Iterable[str]) -> dict[str, list[Repository]]:
    result: dict[str, list[Repository]] = {}
    for url in urls:
        repo = parse_repo_url(url)
        if repo:
            result.setdefault(repo.domain, []).append(repo)
    return result


@dataclass(frozen=True)
class PullRequest:
    branch_name: str
    """Name of the branch that backed the PR."""
    repo_urls: frozenset[str]
    """Git and SSH URLs of the repository where the PR is located."""
    hashes: tuple[str, ...]
    """All commits pushed to the PR, newest first."""
    merged_hash: str | None
    """The commit hash of the PR merge commit, if it exists."""


def pr_initial_query(owner: str, name: str) -> str:
    return f"""
        repository(owner: "{owner}", name: "{name}" ) {{
            pullRequests(orderBy: {{ field: UPDATED_AT, direction: ASC }}, last: 50) {{
                nodes {{
                    id
                    commits (last: 1) {{
                        totalCount
                    }}
                }}
            }}
        }}
    """


def pr_details_query(pr_node_id: str, commit_count: int) -> str:
    return f"""
        node(id: "{pr_node_id}") {{
            ... on PullRequest {{
                headRefName
                headRepository {{
                    sshUrl
                    url
                }}
                commits (last: {commit_count}) {{
                    nodes {{
                        commit {{
                            oid
                        }}
                    }}
                }}
                mergeCommit {{
                    oid
                }}
            }}
        }}
    """


def join_queries(queries: Iterable[str]) -> str:
    return "{" + "\n".join(f"q{i}: {query}" for i, query in enumerate(queries)) + "}"


def client_session() -> aiohttp.ClientSession:
    """Configure aiohttp to trust local SSL credentials and environment variables."""
    connector = aiohttp.TCPConnector(ssl=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    return aiohttp.ClientSession(trust_env=True, connector=connector)


def repo_urls(pr_data: dict[str, Any]) -> Iterator[str]:
    head_repo = pr_data.get("headRepository") or {}
    if ssh_url := head_repo.get("sshUrl"):
        yield ssh_url
    if http_url := head_repo.get("url"):
        yield http_url
        yield http_url + ".git"


async def fetch_pull_requests_from_domain(
    token: str, domain: str, repos: list[Repository]
) -> AsyncIterator[PullRequest]:
    endpoint = (
        f"https://api.{domain}/graphql"
        if domain.count(".") == 1
        else f"https://{domain}/api/graphql"
    )

    async with client_session() as session:
        client = GraphQLClient(
            endpoint=endpoint,
            headers={"Authorization": f"Bearer {token}"},
            session=session,
        )

        # Query for PRs and commit counts
        initial_queries = [
            pr_initial_query(repo.owner, repo.name) for i, repo in enumerate(repos, 1)
        ]
        initial_response = await client.query(join_queries(initial_queries))
        if initial_response.errors:
            msg = f"GraphQL query failed: {initial_response.errors}"
            raise RuntimeError(msg)

        # Determine what follow-up queries to make
        details_queries = [
            pr_details_query(pr_data["id"], pr_data["commits"]["totalCount"])
            for repo_data in initial_response.data.values()
            for pr_data in repo_data["pullRequests"]["nodes"]
        ]

        # If there are no PRs, make no follow-up query
        if not details_queries:
            return

        # Query for detailed PR information
        details_response = await client.query(join_queries(details_queries))
        if details_response.errors:
            msg = f"GraphQL query failed: {details_response.errors}"
            raise RuntimeError(msg)

        # Yield response data as PullRequest objects
        for pr_data in details_response.data.values():
            hashes = tuple(
                commit["commit"]["oid"]
                for commit in reversed(pr_data["commits"]["nodes"])
            )
            yield PullRequest(
                branch_name=pr_data["headRefName"],
                repo_urls=frozenset(repo_urls(pr_data)),
                hashes=hashes,
                merged_hash=(pr_data.get("mergeCommit") or {}).get("oid"),
            )


async def fetch_pull_requests(
    tokens: Callable[[str], str | None],
    urls: Iterable[str],
    *,
    max_concurrency: int = 5,
) -> list[PullRequest]:
    """Fetch the last 50 PRs for each repo

    Issues calls to separate domains concurrently
    """
    semaphore = Semaphore(max_concurrency)

    async def fetch(domain: str, repos: list[Repository]) -> list[PullRequest]:
        async with semaphore:
            token = tokens(domain)
            if not token:
                return []
            return [
                pr async for pr in fetch_pull_requests_from_domain(token, domain, repos)
            ]

    tasks = []
    for domain, repos in repos_by_domain(urls).items():
        tasks.append(fetch(domain, repos))
    pr_lists = await gather(*tasks)
    return [pr for pr_list in pr_lists for pr in pr_list]
