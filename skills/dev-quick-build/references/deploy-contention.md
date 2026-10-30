# Deploy contention: two quick builds racing the same project

The clobber risk is *tree omission*: flipping to an image whose git tree does not
contain what production already serves. The **ancestor gate** (Phase 7, part of the
build-then-deploy integrity checks - marker verify + Served-Image Integrity + ancestor; see the
"integrity trio" in [build-and-ship-playbook.md](../../../docs/build-and-ship-playbook.md))
is the invariant that prevents it - and it must **abort, not echo** (a `set -e` script
with `|| exit 1`, flip physically after the checks). Contention-specific operational
rules:

- Deploy from a pushed worktree branch, never through the shared main checkout.
- `git fetch origin` immediately before the ancestor check + flip - that is the
  serialization point. First to flip wins; the loser merges the winner (usually a
  disjoint-file merge), reruns tests, rebuilds, flips. This terminates (each round
  is forward progress, not wait-and-retry), so a race costs one rebuild round, never
  a regression.
- If `push origin HEAD:main` rejects, someone else pushed: merge `origin/main` and
  push again - your deploy is already serving and its sha is in the merge.
- If the PR merge is refused as `BLOCKED` with green CI, follow the `dev-deploy-safely`
  section on a merge refused as BLOCKED with green CI: resolve any open review threads
  (a review bot's included). Do not reach for an admin override first.
- **Do not force-push to catch up.** If you rebased a branch that is already on
  origin, a push would need `--force`. Instead, reset to the pushed tip
  (`git reset --hard origin/<branch>` on a clean tree), then `git merge origin/main`,
  re-run the gates, and push normally. A squash-merged PR makes the extra merge
  commit invisible on `main`. Check that the merged tree equals the tested rebase
  (`git diff --quiet <rebased-sha> HEAD`) before you push.
- **A loop-back fix after a squash-merged PR goes on a FRESH branch from
  `origin/main`** (`git checkout -b <new-branch> origin/main`). The old branch's
  history is not an ancestor of the squash commit, so a second PR from it shows the
  whole earlier diff again. Uncommitted edits carry over when the old tip's tree
  equals `origin/main`; check with `git diff --quiet HEAD origin/main` first.
- Known contention up front → prefer a deploy train (one session ships both branches).
  Check whether another session is already deploying the project before Phase 7.
- Files on a CMS host have no revisions: `dev-deploy-safely`'s pull-live-and-diff gate is the
  equivalent invariant - live is the baseline, always.
