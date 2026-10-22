---
name: cleanup-git
description: "ALIAS - renamed to repo-cleanup. Forwards to `repo-cleanup`. Kept so `/cleanup-git` and older references still resolve. Triggers on: cleanup-git, clean up git, tidy branches, git is a mess, audit my branches."
---

# Git Cleanup -> renamed to Repo Cleanup

This skill was renamed to **`repo-cleanup`**.

**Do this now:** invoke the **`repo-cleanup`** skill with the exact same request the caller gave you, and follow it end to end.

`/cleanup-git <args>` is equivalent to `/repo-cleanup <args>`. This alias exists only for back-compatibility. New work should call `repo-cleanup` directly.
