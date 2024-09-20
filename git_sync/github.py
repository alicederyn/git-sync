import re
from asyncio import Semaphore, gather
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Iterable, TypeVar

from aiographql.client import GraphQLClient  # type: ignore

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
    repo_urls: frozenset[str]
    branch_hash: str
    merged_hash: str | None


def gql_query(owner: str, name: str) -> str:
    return f"""
        repository(owner: "{owner}", name: "{name}" ) {{
            pullRequests(orderBy: {{ field: UPDATED_AT, direction: ASC }}, last: 50) {{
                nodes {{
                    headRefName
                    headRepository {{
                        sshUrl
                        url
                    }}
                    commits (last: 1) {{
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
        }}
    """


async def fetch_pull_requests_from_domain(
    token: str, domain: str, repos: list[Repository]
) -> AsyncIterator[PullRequest]:
    endpoint = (
        f"https://api.{domain}/graphql"
        if domain.count(".") == 1
        else f"https://{domain}/api/graphql"
    )
    client = GraphQLClient(
        endpoint=endpoint, headers={"Authorization": f"Bearer {token}"}
    )
    queries = [
        f"repo{i}: {gql_query(repo.owner, repo.name)}"
        for i, repo in enumerate(repos, 1)
    ]
    query = "{" + "\n".join(queries) + "}"
    response = await client.query(query)
    assert not response.errors
    for repo_data in response.data.values():
        for pr_data in repo_data["pullRequests"]["nodes"]:
            head_repo = pr_data.get("headRepository") or {}
            repo_urls = [head_repo.get("sshUrl"), head_repo.get("url")]
            if pr_data["commits"]["nodes"]:
                yield PullRequest(
                    branch_name=pr_data["headRefName"],
                    repo_urls=frozenset(url for url in repo_urls if url is not None),
                    branch_hash=pr_data["commits"]["nodes"][0]["commit"]["oid"],
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
