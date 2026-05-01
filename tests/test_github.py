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
        data={"q0": {"pullRequests": {"nodes": []}}},
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


async def test_successful_fetch_with_multiple_repos_and_prs(
    graphql_client: Mock,
) -> None:
    """Test successful fetching of PRs from multiple repositories."""
    initial_data = {
        "q0": {
            "pullRequests": {
                "nodes": [
                    {"id": "pr1", "commits": {"totalCount": 3}},
                    {"id": "pr2", "commits": {"totalCount": 1}},
                ]
            }
        },
        "q1": {
            "pullRequests": {
                "nodes": [
                    {"id": "pr3", "commits": {"totalCount": 2}},
                ]
            }
        },
    }

    details_data = {
        "q0": {
            "headRefName": "feature-branch-1",
            "headRepository": {
                "sshUrl": "git@github.com:owner1/repo1.git",
                "url": "https://github.com/owner1/repo1",
            },
            "commits": {
                "nodes": [
                    {"commit": {"oid": "commit1"}},
                    {"commit": {"oid": "commit2"}},
                    {"commit": {"oid": "commit3"}},
                ]
            },
            "mergeCommit": {"oid": "merge1"},
        },
        "q1": {
            "headRefName": "feature-branch-2",
            "headRepository": {
                "sshUrl": "git@github.com:owner1/repo1.git",
                "url": "https://github.com/owner1/repo1",
            },
            "commits": {
                "nodes": [
                    {"commit": {"oid": "commit4"}},
                ]
            },
            "mergeCommit": None,
        },
        "q2": {
            "headRefName": "feature-branch-3",
            "headRepository": {
                "sshUrl": "git@github.com:owner2/repo2.git",
                "url": "https://github.com/owner2/repo2",
            },
            "commits": {
                "nodes": [
                    {"commit": {"oid": "commit5"}},
                    {"commit": {"oid": "commit6"}},
                ]
            },
            "mergeCommit": {"oid": "merge2"},
        },
    }

    graphql_client.return_value.query.side_effect = [
        Mock(data=initial_data, errors=None),
        Mock(data=details_data, errors=None),
    ]

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
    initial_data = {
        "q0": {
            "pullRequests": {
                "nodes": [
                    {"id": "pr1", "commits": {"totalCount": 1}},
                ]
            }
        },
    }

    details_data = {
        "q0": {
            "headRefName": "feature-branch",
            "headRepository": None,  # Deleted repository
            "commits": {
                "nodes": [
                    {"commit": {"oid": "commit1"}},
                ]
            },
            "mergeCommit": None,
        },
    }

    graphql_client.return_value.query.side_effect = [
        Mock(data=initial_data, errors=None),
        Mock(data=details_data, errors=None),
    ]

    result = []
    async for pr in fetch_pull_requests_from_domain(Mock(), Mock(), [TWO_REPOS[0]]):
        result.append(pr)

    # Should still create PR but with empty repo URLs
    assert len(result) == 1
    assert result[0].repo_urls == frozenset()
    assert result[0].branch_name == "feature-branch"


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
