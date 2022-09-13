import sys
from subprocess import CalledProcessError, check_call

from .git import (
    branches_with_remote_upstreams,
    fast_forward_to_downstream,
    fast_forward_to_upstream,
    get_current_branch,
)


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
