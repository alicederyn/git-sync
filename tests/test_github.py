from collections.abc import Iterator
from unittest.mock import AsyncMock, Mock, patch

import pytest

from git_sync.github import PullRequest, Repository, fetch_pull_requests_from_domain

MOCK_HTTP_CONFIG = "git_sync.github.get_http_config"

TWO_REPOS = [
    Repository(domain="github.com", owner="owner1", name="repo1"),
    Repository(domain="github.com", owner="owner2", name="repo2"),
]


@pytest.fixture(autouse=True)
def graphql_client() -> Iterator[Mock]:
    mock_client = AsyncMock(name="graphql-client")
    mock_client.query.return_value = Mock(
        data={
            "q0": {"pullRequests": {"nodes": []}},
            "q1": {"pullRequests": {"nodes": []}},
        },
        errors=None,
    )
    with patch("git_sync.github.GraphQLClient") as mock:
        mock.return_value = mock_client
        yield mock


@pytest.fixture(autouse=True)
def http_config() -> Iterator[Mock]:
    with patch(MOCK_HTTP_CONFIG, new_callable=AsyncMock, return_value={}) as mock:
        yield mock


@pytest.fixture(autouse=True)
def client_session_factory() -> Iterator[Mock]:
    session = Mock(name="client_session")
    with patch("git_sync.github.client_session") as mock:
        mock.return_value.__aenter__ = AsyncMock(return_value=session)
        mock.return_value.__aexit__ = AsyncMock(return_value=None)
        yield mock


@pytest.fixture(autouse=True)
def client_session(client_session_factory: Mock) -> Mock:
    session: Mock = client_session_factory.return_value.__aenter__.return_value
    return session


def commits(*oids: str, has_previous_page: bool = False) -> dict[str, object]:
    return {
        "nodes": [{"commit": {"oid": oid}} for oid in oids],
        "pageInfo": {
            "hasPreviousPage": has_previous_page,
            "startCursor": f"cursor-{oids[0]}" if oids else None,
        },
    }


async def test_successful_fetch_with_multiple_repos_and_prs(
    graphql_client: Mock,
) -> None:
    """Test successful fetching of PRs from multiple repositories."""
    pr_data = {
        "q0": {
            "pullRequests": {
                "nodes": [
                    {
                        "id": "pr1",
                        "headRefName": "feature-branch-1",
                        "headRepository": {
                            "sshUrl": "git@github.com:owner1/repo1.git",
                            "url": "https://github.com/owner1/repo1",
                        },
                        "headRef": {"target": {"oid": "commit3"}},
                        "isCrossRepository": True,
                        "commits": commits("commit1", "commit2", "commit3"),
                        "mergeCommit": {"oid": "merge1"},
                    },
                    {
                        "id": "pr2",
                        "headRefName": "feature-branch-2",
                        "headRepository": {
                            "sshUrl": "git@github.com:owner1/repo1.git",
                            "url": "https://github.com/owner1/repo1",
                        },
                        "headRef": {"target": {"oid": "commit4"}},
                        "isCrossRepository": False,
                        "commits": commits("commit4"),
                        "mergeCommit": None,
                    },
                ]
            }
        },
        "q1": {
            "pullRequests": {
                "nodes": [
                    {
                        "id": "pr3",
                        "headRefName": "feature-branch-3",
                        "headRepository": {
                            "sshUrl": "git@github.com:owner2/repo2.git",
                            "url": "https://github.com/owner2/repo2",
                        },
                        "headRef": None,  # Branch deleted on merge
                        "isCrossRepository": True,
                        "commits": commits("commit5", "commit6"),
                        "mergeCommit": {"oid": "merge2"},
                    },
                ]
            }
        },
    }

    graphql_client.return_value.query.return_value = Mock(data=pr_data, errors=None)

    # Execute the function
    result = []
    async for pr in fetch_pull_requests_from_domain(Mock(), "github.com", TWO_REPOS):
        result.append(pr)

    # Verify results
    assert len(result) == 3

    # First PR - with merge commit, commits in reverse order (newest first)
    assert result[0] == PullRequest(
        branch_name="feature-branch-1",
        repo_urls=frozenset(
            [
                "git@github.com:owner1/repo1.git",
                "https://github.com/owner1/repo1",
                "https://github.com/owner1/repo1.git",
            ]
        ),
        hashes=("commit3", "commit2", "commit1"),  # Newest first
        merged_hash="merge1",
        head_hash="commit3",
        is_cross_repository=True,
    )

    # Second PR - without merge commit
    assert result[1] == PullRequest(
        branch_name="feature-branch-2",
        repo_urls=frozenset(
            [
                "git@github.com:owner1/repo1.git",
                "https://github.com/owner1/repo1",
                "https://github.com/owner1/repo1.git",
            ]
        ),
        hashes=("commit4",),
        merged_hash=None,
        head_hash="commit4",
        is_cross_repository=False,
    )

    # Third PR - from different repo
    assert result[2] == PullRequest(
        branch_name="feature-branch-3",
        repo_urls=frozenset(
            [
                "git@github.com:owner2/repo2.git",
                "https://github.com/owner2/repo2",
                "https://github.com/owner2/repo2.git",
            ]
        ),
        hashes=("commit6", "commit5"),
        merged_hash="merge2",
        head_hash=None,
        is_cross_repository=True,
    )


async def test_public_github_endpoint(
    graphql_client: Mock, client_session: Mock
) -> None:
    async for _ in fetch_pull_requests_from_domain(
        "test-token", "github.com", TWO_REPOS
    ):
        pass

    graphql_client.assert_called_once_with(
        endpoint="https://api.github.com/graphql",
        headers={"Authorization": "Bearer test-token"},
        session=client_session,
    )


async def test_github_enterprise_endpoint(
    graphql_client: Mock, client_session: Mock
) -> None:
    async for _ in fetch_pull_requests_from_domain(
        "test-token", "github.example.com", TWO_REPOS
    ):
        pass

    graphql_client.assert_called_once_with(
        endpoint="https://github.example.com/api/graphql",
        headers={"Authorization": "Bearer test-token"},
        session=client_session,
    )


async def test_no_pull_requests_found(graphql_client: Mock) -> None:
    graphql_client.return_value.query.return_value.data = {
        "q0": {"pullRequests": {"nodes": []}},
        "q1": {"pullRequests": {"nodes": []}},
    }

    async for _ in fetch_pull_requests_from_domain(Mock(), Mock(), TWO_REPOS):
        raise AssertionError("Should not yield any pull requests")

    graphql_client.return_value.query.assert_called_once()


async def test_pr_without_head_repository(graphql_client: Mock) -> None:
    """Test handling of PR without head repository (e.g. from deleted fork)."""
    pr_data = {
        "q0": {
            "pullRequests": {
                "nodes": [
                    {
                        "id": "pr1",
                        "headRefName": "feature-branch",
                        "headRepository": None,  # Deleted repository
                        "commits": commits("commit1"),
                        "mergeCommit": None,
                    },
                ]
            }
        },
    }

    graphql_client.return_value.query.return_value = Mock(data=pr_data, errors=None)

    result = []
    async for pr in fetch_pull_requests_from_domain(Mock(), Mock(), [TWO_REPOS[0]]):
        result.append(pr)

    # Should still create PR but with empty repo URLs
    assert len(result) == 1
    assert result[0].repo_urls == frozenset()
    assert result[0].branch_name == "feature-branch"


def one_pr_with_commits(commits: dict[str, object]) -> dict[str, object]:
    return {
        "q0": {
            "pullRequests": {
                "nodes": [
                    {
                        "id": "pr1",
                        "headRefName": "feature-branch",
                        "headRepository": None,
                        "commits": commits,
                        "mergeCommit": {"oid": "merge1"},
                    },
                ]
            }
        },
    }


async def test_commits_paginated_over_multiple_pages(graphql_client: Mock) -> None:
    graphql_client.return_value.query.side_effect = [
        Mock(
            data=one_pr_with_commits(
                commits("commit3", "commit4", has_previous_page=True)
            ),
            errors=None,
        ),
        Mock(
            data={"q0": {"commits": commits("commit1", "commit2")}},
            errors=None,
        ),
    ]

    result = [
        pr
        async for pr in fetch_pull_requests_from_domain(Mock(), Mock(), [TWO_REPOS[0]])
    ]

    assert len(result) == 1
    assert result[0].hashes == ("commit4", "commit3", "commit2", "commit1")
    assert graphql_client.return_value.query.call_count == 2


async def test_pagination_stops_on_empty_page(graphql_client: Mock) -> None:
    """An empty page cannot advance the cursor, so paging must stop regardless."""
    graphql_client.return_value.query.side_effect = [
        Mock(
            data=one_pr_with_commits(commits("commit1", has_previous_page=True)),
            errors=None,
        ),
        Mock(data={"q0": {"commits": commits(has_previous_page=True)}}, errors=None),
    ]

    result = [
        pr
        async for pr in fetch_pull_requests_from_domain(Mock(), Mock(), [TWO_REPOS[0]])
    ]

    assert result[0].hashes == ("commit1",)
    assert graphql_client.return_value.query.call_count == 2


async def test_graphql_errors(graphql_client: Mock) -> None:
    graphql_client.return_value.query.return_value = Mock(errors=["Some GraphQL error"])

    with pytest.raises(RuntimeError, match="GraphQL query failed:"):
        async for _ in fetch_pull_requests_from_domain(Mock(), Mock(), TWO_REPOS):
            pass


async def test_git_config_proxy_passed_to_session(
    http_config: Mock, client_session_factory: Mock
) -> None:
    http_config.return_value = {
        "http.proxy": "http://proxy:8080",
        "http.sslcainfo": "/path/to/ca.pem",
    }

    async for _ in fetch_pull_requests_from_domain(
        "test-token", "github.com", TWO_REPOS
    ):
        pass

    http_config.assert_called_once_with("https://github.com")
    client_session_factory.assert_called_once_with(
        proxy="http://proxy:8080", ssl_ca_info="/path/to/ca.pem"
    )


async def test_git_config_no_proxy_passed_as_none(
    client_session_factory: Mock,
) -> None:
    async for _ in fetch_pull_requests_from_domain(
        "test-token", "github.com", TWO_REPOS
    ):
        pass

    client_session_factory.assert_called_once_with(proxy=None, ssl_ca_info=None)
