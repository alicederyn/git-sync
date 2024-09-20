import os
import re
import sys
from subprocess import check_output

import toml
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from packaging import version

# Fetch version information
new_pyproject = toml.load("pyproject.toml")
new_name = new_pyproject["project"]["name"]
new_version = version.parse(new_pyproject["project"]["version"])
old_pyproject_s = check_output(
    ["git", "show", "origin/main:pyproject.toml"], encoding="utf-8"
)
old_pyproject = toml.loads(old_pyproject_s)
old_name = old_pyproject["project"]["name"]
old_version = version.parse(old_pyproject["project"]["version"])
print(f"Old {old_name} version: {old_version}")
print(f"New {new_name} version: {new_version}")


def fetch_pr_labels() -> set[str]:
    # https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#pull_request
    PR = int(re.match(r"refs/pull/(\d+)/merge", os.environ["GITHUB_REF"]).group(1))

    OWNER, REPO = os.environ["GITHUB_REPOSITORY"].split("/")
    GITHUB_TOKEN = sys.argv[1]
    transport = AIOHTTPTransport(
        url=os.environ["GITHUB_GRAPHQL_URL"],
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
    )
    client = Client(transport=transport, fetch_schema_from_transport=True)
    result = client.execute(
        gql(
            """
    query getLabels($repo: String!, $owner: String!, $pr: Int!) {
      repository(name: $repo, owner: $owner) {
        pullRequest(number: $pr) {
          labels(first: 100) {
            nodes {
              name
            }
          }
        }
      }
    }
  """
        ),
        variable_values={"repo": REPO, "owner": OWNER, "pr": PR},
    )
    return {n["name"] for n in result["repository"]["pullRequest"]["labels"]["nodes"]}


norelease = "norelease" in fetch_pr_labels()

if old_name != new_name:
    if norelease:
        print("norelease PRs cannot change the project name", file=sys.stderr)
        sys.exit(1)
elif old_version > new_version:
    print("Version is older in this PR than on destination branch", file=sys.stderr)
    sys.exit(1)
elif old_version == new_version:
    if not norelease:
        print(
            "PRs must bump the project version prior to merging,"
            " or be tagged norelease",
            file=sys.stderr,
        )
        sys.exit(1)
elif norelease:
    print("norelease PRs must not bump the project version", file=sys.stderr)
    sys.exit(1)
