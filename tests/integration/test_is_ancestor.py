import pytest

from git_sync.git import is_ancestor

from .gitutils import create_commit


@pytest.mark.asyncio
async def test_is_ancestor_simple() -> None:
    # Given two commits
    base = create_commit("HEAD", foo="a")
    second = create_commit(base, foo="b")
    # Then base is an ancestor of second
    assert await is_ancestor(base, second) is True
    # And second is not an ancestor of base
    assert await is_ancestor(second, base) is False
