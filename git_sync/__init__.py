import sys
from subprocess import CalledProcessError, check_call

from .git import (
    fast_forward_to_downstream,
    fast_forward_to_upstream,
    get_branches_with_remote_upstreams,
)


def main() -> None:
    try:
        branches = get_branches_with_remote_upstreams()
    except CalledProcessError as e:
        # Probably not in a git directory, or some other misconfiguration.
        # git will already have written the problem to stderr.
        sys.exit(e.returncode)
    if any(b.is_current for b in branches):
        check_call(["git", "pull", "--all"])
    else:
        check_call(["git", "fetch", "--all"])
    fast_forward_to_upstream(b for b in branches if not b.is_current)
    fast_forward_to_downstream(branches)
