git sync
========

Utility script that synchronizes a local repository with all remotes:

 - fetches all remotes
 - fast-forwards all local branches that have a remote upstream
 - pushes upstream changes to the default push remote

Not all git configuration is taken into account; please open an issue if this causes problems.

[![Validation status page](https://github.com/alicederyn/git-sync/actions/workflows/validation.yml/badge.svg?branch=main)](https://github.com/alicederyn/git-sync/actions/workflows/validation.yml?query=branch%3Amain)


Details
-------

As an example, suppose you have a local repository with a main branch, your main branch has upstream/main as its upstream, and your remote.pushdefault config is origin. What happens when you run `git sync`?

If you are currently working on `main`, it will use `git pull --all` to fetch all remotes and update `main` in a single step; otherwise, it will run `git fetch --all`, then use `git fetch . upstream/main:main` to fast-forward in changes. Finally, in both cases it will run `git push origin main`.


Installing
----------

To install, use [pipx]:

```bash
pip install pipx
export PATH="$PATH:$HOME/.local/bin"
pipx install git+https://github.com/alicederyn/git-sync.git
```

[pipx]: https://pipxproject.github.io/pipx/
