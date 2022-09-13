# git sync

Utility script that synchronizes a local repository with all remotes:

 - fetches all remotes
 - fast-forwards all local branches that have a remote upstream
 - pushes upstream changes to the default push remote
 - fast-forwards branches associated with merged PRs to the merge commit

Not all git configuration is taken into account; please open an issue if this causes problems.

[![Validation status page](https://github.com/alicederyn/git-sync/actions/workflows/validation.yml/badge.svg?branch=main)](https://github.com/alicederyn/git-sync/actions/workflows/validation.yml?query=branch%3Amain)


## Details

As an example, suppose you have a local repository with a main branch, your main branch has upstream/main as its upstream, and your remote.pushdefault config is origin. What happens when you run `git sync`?

If you are currently working on `main`, it will use `git pull --all` to fetch all remotes and update `main` in a single step; otherwise, it will run `git fetch --all`, then use `git fetch . upstream/main:main` to fast-forward in changes. Finally, in both cases it will run `git push origin main`.


### Merged PRs

Git understands merge commits and handles them nicely. For instance, if a branch F is merged to main with a merge commit, the git command `git branch -d F` will succeed without warning, as it knows F is merged to main. If you have further work on a child branch, `git pull` will know to drop any merged commits automatically.

Squash commits break this model, as they deliberately do not record the information git needs to determine that a branch commit is in the history of main. This means having to do `branch -D` and risking mistakenly deleting unmerged commits if you have misremembered which branches have merged.

If you have `remote.pushdefault` set and `$GITHUB_TOKEN` in your environment, `git sync` will query the last 50 PRs from each remote, and if it finds a merge commit for a local branch, will fast-forward that branch to the merge commit. This gives git enough information to reenable the safer workflows.


## Installing

To install, use [pipx]:

```bash
pip install pipx
python -m pipx ensurepath  # Permanently updates your $PATH
pipx install git+https://github.com/alicederyn/git-sync.git
```

[pipx]: https://pipxproject.github.io/pipx/
