git sync
========

Utility script that synchronizes a local repository with all remotes:

 - pulls all remotes
 - fast-forwards all local branches that have a remote upstream
 - pushes upstream changes to the default push remote

For instance, if you have a local repository with a main branch, your main branch has upstream/main as its upstream, and your remote.pushdefault config is origin, then `git sync` will fast-forward main to include any upstream changes, and push them to origin.

Not all git configuration is taken into account; please open an issue if this causes problems.

[![Validation status page](https://github.com/alicederyn/git-sync/actions/workflows/validation.yml/badge.svg?branch=main)](https://github.com/alicederyn/git-sync/actions/workflows/validation.yml?query=branch%3Amain)


Installing
----------

To install, use [pipx]:

```bash
pip install pipx
export PATH="$PATH:$HOME/.local/bin"
pipx install git+https://github.com/alicederyn/git-sync.git
```

[pipx]: https://pipxproject.github.io/pipx/
