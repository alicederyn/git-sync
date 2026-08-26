import re
import ssl
from asyncio import Semaphore, gather
from asyncio.subprocess import PIPE, create_subprocess_exec
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

import aiohttp
import truststore
from aiographql.client import GraphQLClient

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


COMMITS_PAGE_SIZE = 100
"""Maximum records github.com permits on a single connection."""


def commits_query(*, before: str | None = None) -> str:
    cursor_arg = f', before: "{before}"' if before else ""
    return f"""
        commits (last: {COMMITS_PAGE_SIZE}{cursor_arg}) {{
            nodes {{
                commit {{
                    oid
                }}
            }}
            pageInfo {{
                hasPreviousPage
                startCursor
            }}
        }}
    """


def pr_query(owner: str, name: str) -> str:
    return f"""
        repository(owner: "{owner}", name: "{name}" ) {{
            pullRequests(orderBy: {{ field: UPDATED_AT, direction: ASC }}, last: 50) {{
                nodes {{
                    id
                    headRefName
                    headRepository {{
                        sshUrl
                        url
                    }}
                    {commits_query()}
                    mergeCommit {{
                        oid
                    }}
                }}
            }}
        }}
    """


def pr_commits_page_query(pr_node_id: str, before: str) -> str:
    return f"""
        node(id: "{pr_node_id}") {{
            ... on PullRequest {{
                {commits_query(before=before)}
            }}
        }}
    """


def join_queries(queries: Iterable[str]) -> str:
    return "{" + "\n".join(f"q{i}: {query}" for i, query in enumerate(queries)) + "}"


async def run_queries(
    client: GraphQLClient, queries: list[str]
) -> list[dict[str, Any]]:
    response = await client.query(join_queries(queries))
    if response.errors:
        msg = f"GraphQL query failed: {response.errors}"
        raise RuntimeError(msg)
    return [response.data[f"q{i}"] for i in range(len(queries))]


async def get_http_config(url: str) -> dict[str, str]:
    """Read git http.* config applicable to the given URL.

    Uses --get-urlmatch to respect domain-specific overrides.
    """
    proc = await create_subprocess_exec(
        "git", "config", "--get-urlmatch", "http", url, stdout=PIPE
    )
    assert proc.stdout
    raw = await proc.stdout.read()
    await proc.wait()
    result: dict[str, str] = {}
    for line in raw.rstrip(b"\r\n").splitlines():
        key, _, value = line.partition(b" ")
        result[key.decode("ascii").lower()] = value.decode()
    return result


def client_session(
    *, proxy: str | None = None, ssl_ca_info: str | None = None
) -> aiohttp.ClientSession:
    """Configure aiohttp to trust local SSL credentials and environment variables."""
    ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if ssl_ca_info:
        ssl_context.load_verify_locations(cafile=ssl_ca_info)
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    return aiohttp.ClientSession(trust_env=True, connector=connector, proxy=proxy)


def repo_urls(pr_data: dict[str, Any]) -> Iterator[str]:
    head_repo = pr_data.get("headRepository") or {}
    if ssh_url := head_repo.get("sshUrl"):
        yield ssh_url
    if http_url := head_repo.get("url"):
        yield http_url
        yield http_url + ".git"


@dataclass
class PartialPullRequest:
    """A pull request whose commit list may not have been fully fetched yet."""

    node_id: str
    branch_name: str
    repo_urls: frozenset[str]
    merged_hash: str | None
    oids: list[str] = field(default_factory=list)
    """Commits fetched so far, oldest first."""
    cursor: str | None = None
    """Where to resume from, if older commits remain unfetched."""

    def add_page(self, commits: dict[str, Any]) -> None:
        """Prepend a page of commits, which are older than any already fetched."""
        nodes = commits["nodes"]
        self.oids[:0] = [node["commit"]["oid"] for node in nodes]
        page_info = commits["pageInfo"]
        # An empty page would leave the cursor unchanged, so stop to avoid looping
        self.cursor = (
            page_info["startCursor"] if nodes and page_info["hasPreviousPage"] else None
        )

    def to_pull_request(self) -> PullRequest:
        return PullRequest(
            branch_name=self.branch_name,
            repo_urls=self.repo_urls,
            hashes=tuple(reversed(self.oids)),
            merged_hash=self.merged_hash,
        )


def partial_pull_request(pr_data: dict[str, Any]) -> PartialPullRequest:
    pr = PartialPullRequest(
        node_id=pr_data["id"],
        branch_name=pr_data["headRefName"],
        repo_urls=frozenset(repo_urls(pr_data)),
        merged_hash=(pr_data.get("mergeCommit") or {}).get("oid"),
    )
    pr.add_page(pr_data["commits"])
    return pr


async def fetch_remaining_commits(
    client: GraphQLClient, prs: Iterable[PartialPullRequest]
) -> None:
    """Page backwards through the commits of any PR with more than one page."""
    pending = [pr for pr in prs if pr.cursor]
    while pending:
        queries = []
        for pr in pending:
            assert pr.cursor
            queries.append(pr_commits_page_query(pr.node_id, pr.cursor))
        pages = await run_queries(client, queries)
        for pr, page_data in zip(pending, pages, strict=True):
            pr.add_page(page_data["commits"])
        pending = [pr for pr in pending if pr.cursor]


async def fetch_pull_requests_from_domain(
    token: str, domain: str, repos: list[Repository]
) -> AsyncIterator[PullRequest]:
    endpoint = (
        f"https://api.{domain}/graphql"
        if domain.count(".") == 1
        else f"https://{domain}/api/graphql"
    )

    http_config = await get_http_config(f"https://{domain}")
    proxy = http_config.get("http.proxy")
    ssl_ca_info = http_config.get("http.sslcainfo")

    async with client_session(proxy=proxy, ssl_ca_info=ssl_ca_info) as session:
        client = GraphQLClient(
            endpoint=endpoint,
            headers={"Authorization": f"Bearer {token}"},
            session=session,
        )

        queries = [pr_query(repo.owner, repo.name) for repo in repos]
        prs = [
            partial_pull_request(pr_data)
            for repo_data in await run_queries(client, queries)
            for pr_data in repo_data["pullRequests"]["nodes"]
        ]

        await fetch_remaining_commits(client, prs)

        for pr in prs:
            yield pr.to_pull_request()


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
