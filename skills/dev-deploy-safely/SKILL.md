---
name: dev-deploy-safely
description: "Use before production, shared staging, or preview deploys. Verifies environment class, branch freshness, worktree state, tested commits, deploy manifest, smoke checks, and rollback path. Triggers on: dev deploy safely, dev-deploy-safely, deploy safely, deploy-safely, safe deploy, deploy gates, pre-deploy checks, deploy to production safely."
argument-hint: "<service-or-surface> [production|staging|preview] [backend|frontend|infra|cms|container|static|worker]"
---

# Dev Deploy Safely

Use this skill before production, shared staging, or preview deploys.

The core production rule: the branch doing a production deploy must contain every change that is already live or already production-bound.

For shared staging, decide first whether the environment is a production mirror,
QA/demo target, or release-candidate environment. Production mirrors and release
candidates should follow production gates. QA/demo staging can intentionally
diverge, but the deploy record must say what branch/commit is deployed and why
drift is acceptable.

For ephemeral previews, the goal is traceability rather than production parity:
record the branch, commit or artifact, URL, checks run, skipped checks, owner,
and cleanup path.

Fetching tells you what exists remotely. It does not prove your local deploy tree is safe. Deployment tools often publish the files or image from the current worktree, so stale local state can overwrite live fixes from another branch.

## Non-Negotiable Gates

1. Classify the target environment before choosing gates: production, shared staging, or ephemeral preview.
2. Fetch and prune before production or shared staging deploy planning.
3. For production, prove the deploy branch includes the latest remote default branch.
4. For production, check whether local default branch has unpushed production-parity commits.
5. For shared staging, branch freshness and local-default parity are mandatory only when staging mirrors production or is being used as a release candidate. Otherwise record intentional drift.
6. For ephemeral preview, record the branch/commit/artifact and target URL. Default-branch parity is not required unless the preview is used as a release candidate.
7. Audit active worktrees before multi-file or high-risk production/shared-staging deploys.
8. Commit and push the exact tree that passed tests before production deploy. For shared staging, strongly prefer a pushed commit. For preview, at minimum record the local commit or artifact digest.
9. Do not deploy production from a dirty worktree. Staging/preview dirty deploys are allowed only when intentionally testing local changes and the record says so.
10. If another branch has deployed first to the same production or shared staging surface, merge that branch or the live environment diff into the deploy branch, retest, then deploy.
11. Write a deploy manifest for file-based deploys.
12. Pull and diff live files before overwriting production or shared staging files.
13. Back up live files or retain an artifact rollback pointer before replacing production or shared staging.
14. Verify the target environment with smoke checks immediately after deploy.
15. Record what was deployed, how it was verified, which gates were skipped, and how to roll back or clean up.
16. On platforms that split traffic across revisions (Cloud Run, App Engine, Lambda aliases), a production deploy is NOT complete until the new revision serves **100% of live traffic** and you have smoked the **live production URL**. A revision deployed with no traffic and never flipped is **deployed dark**, not a finished deploy - see "Definition of done" below.
17. Before merging any change you classify as non-deploy (docs, skills, config), prove the merge does not deploy. See "Does merging this deploy?" below. If it does deploy, it IS a production deploy: run these gates or get explicit approval.

## Definition of done: live means 100% traffic, not just a new revision

"Deploy to production" and "put it straight to live" mean one thing: **the new revision serves 100% of production traffic on the real production URL, and you verified it there.** They do NOT mean "a new revision exists in production."

On traffic-split platforms the safe recipe deploys the new revision with **no traffic** first (a dormant revision), verifies it, then **flips traffic to it**. That flip is the step that makes the change live. Skip it - or stop after a green check on the revision's own tag/preview URL - and the new revision sits at **0% traffic** while the live URL keeps serving the old code. That is "deployed dark": present in production, serving nobody.

- Leaving a revision at 0% traffic is valid ONLY when a staged, canary, or dark rollout was explicitly requested. Then say so, record it, and hand over the single traffic flip that is still owed.
- Absent that request, flipping to 100% and smoking the live URL is mandatory before you call the deploy done.

> **Word of caution on "dark".** Teams often also use "dark" for a feature shipped behind an OFF flag (code live at 100% traffic, feature switched off). That is a different thing from a 0%-traffic revision. Both are "not actually live"; say which one you mean.

**The deploy's own record is part of "done", in the same run.** A doc that only records or reflects the deploy you just shipped and verified (writing the deploy record, flipping a deploy-log entry from PENDING to LIVE, an OWED-to-DONE QA line) is completed in the SAME run as the deploy, not left as a follow-up. It never covers new code or any other change.

## A permission wall is not a stop signal

On a headless or shared machine the ambient cloud identity is often narrow on purpose, so a gate read (build history, revision describe, image digest, logs) can fail with 403 / `PERMISSION_DENIED`, or return an empty list. Before you mark a gate as blocked, hand off, or ask the owner to log in with a personal account:

1. Check whether your environment provides an elevated, read-capable impersonation identity (your machine runbook or environment names it). Use only the identity it names. Never look up or guess other service accounts you might be able to impersonate. If there is none, the normal hand-off applies.
2. If there is one, re-run the read as that identity: `--impersonate-service-account=<sa>` on gcloud, or the `CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT=<sa>` prefix, which also covers `gcloud storage` and bq. Python Google clients ignore both: build impersonated credentials in-process (`google.auth.impersonated_credentials`). Confirm the re-run printed the impersonation warning (or otherwise ran as the elevated identity); if it did not, the tool ignored the setting.
3. An empty result from the narrow identity is not proof that nothing exists. Re-run it impersonated before you trust it.
4. Impersonation gives capability, not approval. Every gate in this skill still applies, and so does your confirm-first list (authz, secrets, data, migrations, anything irreversible, external comms). Never log in with a personal account on a headless box: it cannot reauthenticate unattended, and it can poison a shared config.

## Does merging this deploy?

A merge to a default branch can deploy production even when the repo shows nothing: cloud build push triggers live in the cloud project, not in `.github/`. A docs-only merge can redeploy production this way. Check all three before calling a merge non-deploy:

1. **Repo:** CI workflow push triggers, their `paths` / `paths-ignore`, and any change-detection job that decides which deploy legs run.
2. **Git host evidence (no cloud access needed):** the check runs from your cloud build app on recent default-branch commits (for GitHub: `gh api repos/<owner>/<repo>/commits/<sha>/check-runs`). `success` with "Build <id> successful" means that push built. `neutral` with "Changed files did not match file filter" means a trigger filter skipped it. No build run at all means no connected trigger fired. Check a commit you know shipped first, as the positive control.
3. **Authoritative:** in the target project, list the build triggers (read `includedFiles` / `ignoredFiles`) and the builds for the commit. This needs build read access; use an admin identity if yours lacks it. **List triggers once per region.** Without a region flag the command lists only global triggers and returns an empty list, with no error, for regional ones. Cover `global` and every region the project deploys in, and run the same command on a project you know has triggers as the positive control before you trust an empty result.

To stop docs-only merges deploying, add `ignoredFiles` to the trigger, but only for paths the image never contains: check the Dockerfile `COPY` list first (some images copy a docs subfolder). Change the trigger once (describe, edit, import); the describe output is the rollback.

## PR merge gate: gate, auto-recover, merge

When a deploy or integration lands through a PR (for example a merge to a `main` that auto-deploys), gate the merge on the check results of the PR's head commit, and merge only that commit. Two scripts bundled with this skill do the gating. `<DEPLOY_SKILL_DIR>` below is this skill's "Base directory for this skill", pasted literally; the scripts need `gh` and `python3`.

- `<DEPLOY_SKILL_DIR>/scripts/pr-checks-green.sh` waits for the PR's checks and prints the head SHA (the only stdout line) only when it is safe to merge that commit. Exit codes: 0 green, 1 red, 2 no checks registered, 3 checks still running at the time limit, 4 usage error, `gh` error, merge conflict or behind, 5 GitHub could not be reached (a `STOP: NETWORK` line: the checks were not read, so this is not a red check; run it again).
- `<DEPLOY_SKILL_DIR>/scripts/gate-merge.sh` runs that gate, updates a behind branch (a merge, never a force-push) and gates again up to 3 times, refuses to merge onto a red base branch, merges only the gated commit with `--match-head-commit`, and confirms the PR state is `MERGED`. It is the one-command form of everything in this section. It exits 0 merged, 1 not merged, 4 usage error, and 5 when GitHub could not be reached (a read is retried first; after a network error on the merge call it reads the PR state before it calls the merge refused). Set `GATE_MERGE_EXPECT_HEAD=<full 40-character sha>` when a caller proved one head (for example a check that the merge deploys nothing): a push after that proof then stops the merge instead of merging the new head. When it reads the base branch for the red-base check, it leaves out a failed Dependabot updater run (a crashed dependency update is not CI); every other failure on the base still counts.

What "green" means to the gate: every check on the head commit finished with SUCCESS (SKIPPED, CANCELLED and every other result is red); an optional check that came back NEUTRAL (a bot that declined to run) and is not a required check of the base branch counts as passed, while a required NEUTRAL check stays red; every check the base branch requires is present (a job that waits on another job registers its check late, so a list that looks green too early is possible: the gate sees the same head commit green on two polls in a row); every GitHub Actions run for the head commit is complete; the PR has no merge conflict and is not behind a base that requires up-to-date branches.

Run the gate and the merge as ONE background Bash call (the gate waits up to 30 minutes, and `SHA` does not survive into a later call):

```bash
SHA=$(bash "<DEPLOY_SKILL_DIR>/scripts/pr-checks-green.sh" --repo <owner>/<repo> <pr>) \
  && gh pr merge <pr> --repo <owner>/<repo> --squash --match-head-commit "${SHA:?gate did not pass}"
```

or, in the same way, `bash "<DEPLOY_SKILL_DIR>/scripts/gate-merge.sh" <pr> --repo <owner>/<repo>`, which prints `MERGED <pr>` or `STOP: <why>`.

**In a harness that refuses a `$(...)` plus `bash <script>` line** (for example a worktree-bound agent session), split the one-call form into two calls:

1. Run the gate in the background, by the script's literal absolute path (no `bash` in front, no variables), with output to files: `<DEPLOY_SKILL_DIR>/scripts/pr-checks-green.sh --repo <owner>/<repo> <pr> > <scratch>/gate.txt 2> <scratch>/gate.err`
2. When it exits 0, read the head SHA from the first line of `gate.txt` and the `GREEN:` line from `gate.err`, then merge that exact commit: `gh pr merge <pr> --repo <owner>/<repo> --squash --match-head-commit <sha from gate.txt>`.

`--match-head-commit` still refuses the merge if a push moved the head after the gate. Never gate on `gh pr checks --watch`: it can exit 0 on a CANCELLED check, and started right after a push it can finish on the PREVIOUS head's checks.

**Read the PR's inline review comments before every merge, even when branch protection does not require it.** The green gate sees checks only. An automated PR review bot posts its findings as inline review comments, and it can post a blocking finding after CI is green. Where a bot reviews your PRs, wait for it to finish (poll the PR's comments every 60 seconds, for up to 15 minutes, until its summary shows the review completed for the PR's head commit), then read `gh api --paginate repos/<owner>/<repo>/pulls/<pr>/comments` and the PR reviews before `gh pr merge`. Do this again after each push, because a push starts a new review. In such a repo, do not use the one-call forms above: use the split form (gate alone, then wait for and triage the bot's review of the gated commit, then merge with `--match-head-commit`). If the review does not complete in 15 minutes, do not merge on it: run an independent review of the gated commit and merge only when it has no critical or high finding, or ask the owner. Fix a critical or high finding before the merge; reply on the thread for any finding you decline.

**A repo with no CI** (no workflows, no required checks) shows 0 checks on every PR. Without `--allow-none` the gate waits its full 30 minutes, then stops with exit 2, "no checks registered". Add `--allow-none` to the gate line there. It is safe on any repo: the script passes a PR with no checks only after a short grace period, and only when the repo has no workflows and no required checks; anywhere else it still waits for real checks. (A PR with no checks also passes by itself when the base branch demonstrably requires none and the merge state is clean.)

The gate is stricter than the watch, so a non-green result is NOT a stop by itself. Recover ONCE, then gate again:

- **A CANCELLED check, or a known infra flake** (for example a docker build failing on a package-index read timeout): `gh run rerun <run-id> --failed`, then gate again.
- **`BEHIND`:** merge the base branch into the PR branch (`gh pr update-branch`), push, then gate again (the push restarts the checks). `gate-merge.sh` does this itself.
- **The head moved** (`--match-head-commit` refused, or a new push landed): gate again on the new head.
- **Only SKIPPED checks are not SUCCESS, and none of them is a required check of the base branch:** treat it as green and merge with the head SHA (`gh pr view <pr> --json headRefOid`).
- **An optional NEUTRAL check** (for example "review declined" from a bot that is out of credit): the gate already counts a NEUTRAL check that is not a required check of the base branch as passed, and says so in its output. A required check that comes back NEUTRAL stays red.

Stop only when a check still fails after that one recovery pass (a genuine failing test or build). That is a broken change, so report it with the failing job's log excerpt; do not merge around it. Unresolved review threads are the next section.

`gate-merge.sh` also takes `--admin` (self-merge as a ruleset bypass actor; use it only on your own non-deploy PR, and never as the first answer to a BLOCKED merge: see the next section), `--delete-branch` (not from inside a worktree of that repo) and `--allow-red-base` (merge although the base branch is red, only for the PR that fixes it).

## Merge refused as BLOCKED with green CI

When `gh pr merge` refuses and `gh pr view <n> --json mergeStateStatus` prints `BLOCKED` while every required check is green and no approval is required, do this before you reach for an admin override:

1. **Check your repo's own notes first** (a gotchas or runbook doc): another session may already have solved it.
2. **Check for unresolved review threads.** A branch ruleset with `required_review_thread_resolution: true` blocks the merge while any review thread is open, and GitHub's error does not say so. Review bots post inline review comments on PRs, so this recurs:
   ```bash
   gh api repos/<owner>/<repo>/rules/branches/<base> --jq '.[] | select(.type=="pull_request") | .parameters.required_review_thread_resolution'
   gh api graphql -f query='query{repository(owner:"<owner>",name:"<repo>"){pullRequest(number:<n>){reviewThreads(first:20){nodes{id isResolved comments(first:1){nodes{author{login} body}}}}}}}'
   ```
3. **Treat each thread as review input:** fix a valid point (push the fix and let CI re-run), or answer it. Then resolve it:
   ```bash
   gh api graphql -f query='mutation{resolveReviewThread(input:{threadId:"<thread id>"}){thread{isResolved}}}'
   ```
4. **Merge normally**, without an admin override. Re-check the threads after each push, because the bot can review the new commit.

`BEHIND` is a different state: merge the base branch into the PR branch, push, and wait for the checks to re-run.

## Serving revision built from a branch that was later squash-merged

On revision-based platforms (Cloud Run), a revision's `git-sha` label is the commit of the branch it was **built** from. If that branch's PR is later **squash-merged**, `main` holds the same content under a new sha. The serving sha is then never an ancestor of `main`, so the anti-clobber check `git merge-base --is-ancestor <serving-sha> HEAD` fails on every later deploy, even when nothing live is missing.

Do not stub or skip the check. Prove containment **by content**, inside the same `set -e` block as the traffic flip:

1. Fetch the commit: a short sha cannot be fetched by itself, so run `git fetch origin refs/pull/<n>/head`.
2. Pin the exact serving revision and its sha. Abort if either changed since you checked.
3. Confirm the squash commit is an ancestor of HEAD.
4. Diff every **build input** (take the list from the Dockerfile `COPY` lines) between the serving sha and HEAD: `git diff --quiet <serving-sha> HEAD -- Dockerfile <manifests> src ':(exclude)<your changed files>'`. It must be empty apart from this change's own files.
5. Say in the deploy record that the content check replaced the ancestor check, and why.

**Prevention:** when a PR's revision is already serving (you deployed from the branch, then merge), merge that PR with a **merge commit** (`gh pr merge --merge`), not a squash. The serving sha then stays an ancestor of `main`, and the next deploy's ancestor check passes on its own. Repos whose CI builds from `main` after the merge do not hit this.

## Environment Classes

| Environment | Use case | Required posture |
|---|---|---|
| Production | Customer-facing app, live API, live CMS/plugin files, production infrastructure | All gates mandatory |
| Shared staging | Long-lived staging, QA, demo, or release-candidate environment used by multiple people | Fetch, test, manifest, active-worktree awareness, smoke checks, and rollback pointer required; default-branch parity depends on whether staging mirrors production |
| Ephemeral preview | Short-lived branch preview or local validation target | Record branch/commit/artifact, URL, checks run, skipped checks, owner, and cleanup path |

Treat staging as production for any surface that uses production data,
production credentials, customer-visible URLs, shared live files, or shared
mutable infrastructure.

## Cloud Functions gen2 (source-only deploys)

A gen2 function deploys from source: `gcloud functions deploy <fn> --gen2 --source=<dir>`. A digest deploy does not apply. The integrity proof is the served source. Run Steps 1-4 first. Then run these gates.

**Before the deploy**

1. Capture the live config: `gcloud functions describe <fn> --gen2 --region=<r> --format=json`. Save the file.
2. Download the live source zip (the bucket and object are in `buildConfig.source.storageSource`). Check that the function's files in the zip are byte-identical to `origin/<default>`. If they differ, someone shipped something that is not on the default branch. Stop.
3. Deploy from the pushed, tested tree. Pin `--service-account` to the live runtime service account. Never pass `--set-env-vars` or `--set-secrets`: they replace the live config.

**After the deploy**

1. Download the served zip again. Check that it is byte-identical to the deployed commit and contains the change marker.
2. Diff the describe JSON from before and after. Only the build, the source generation, the revision and `updateTime` may change.
3. Run the function once. For a scheduler-triggered function, run `gcloud scheduler jobs run <job>`. Read its result line from the logs. It may be in `jsonPayload`, not `textPayload`.

A gen2 deploy serves 100% on the new revision at once. There is no dark step to flip.

**Rollback:** check out the previous source and run the same deploy command.

## Step 1: Branch Freshness Gate

Run from the deploy worktree:

```bash
git fetch origin --prune
git status --short
git branch --show-current

DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|^refs/remotes/||')
[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH="origin/main"

git rev-list --left-right --count "$DEFAULT_BRANCH"...HEAD
git log --oneline --decorate -10
```

Interpretation:

- The first number from `rev-list` is commits behind the remote default branch.
- Behind must be `0` before production deployment.
- If deploying from the default branch, run `git pull --ff-only`.
- If deploying from a feature branch, merge or rebase the remote default branch into the feature branch and rerun tests.
- If the branch is ahead, those commits are part of the deploy. Confirm that is intended.
- For shared staging, enforce `behind = 0` only when staging mirrors production or is being used as a release candidate. Otherwise record the intentional drift and reason.
- For ephemeral preview, `behind > 0` can be acceptable. Record the branch base so reviewers know what is and is not included.

Any branch update invalidates earlier test and deploy checks. Rerun them.

## Step 2: Local Default Branch Parity Gate

This catches a common failure mode: local default branch contains production fixes that have not been pushed, while the deploy branch has merged only `origin/main`.

Run:

```bash
git rev-list --left-right --count "$DEFAULT_BRANCH"...main
git log --oneline --decorate "$DEFAULT_BRANCH"..main
git merge-base --is-ancestor main HEAD && echo "deploy branch contains local main" || echo "DEPLOY BRANCH MISSING LOCAL MAIN"
```

Interpretation:

- If local `main` is not ahead of `origin/main`, continue.
- If local `main` is ahead and you are deploying from `main`, push `main` before deploying unless an approved local-only deploy process exists.
- If local `main` is ahead and you are deploying from another branch, the deploy branch must include those local commits or those commits must be pushed and merged.
- If local `main` has unrelated work, stop and split, push, merge, or defer before deploying.

Adapt `main` to your repository's default branch name when needed.

This gate is mandatory for production. For shared staging, run it when staging is
meant to mirror production or when staging can overwrite shared/live files. For
ephemeral preview, record local-main divergence only if the preview is being used
as a release candidate.

## Step 3: Active Worktree Gate

Before a production or shared-staging deploy that can overwrite multiple files or shared infrastructure, list active worktrees:

```bash
git worktree list --porcelain
for wt in $(git worktree list --porcelain | awk '/^worktree / {print $(2)}'); do
  echo "== $wt =="
  git -C "$wt" status --short --branch
  git -C "$wt" log --oneline --decorate "$DEFAULT_BRANCH"..HEAD --max-count=12 || true
done
```

Your tooling may refuse `git -C <other-worktree>` calls (some agent harnesses bind a session to one worktree). Then audit the other worktrees through refs instead, from your own worktree, one plain command per call:

```bash
git worktree list
git log --oneline origin/main..<other-branch>      # what the other worktree has that main lacks
git diff --stat origin/main...<other-branch>       # which files it touches
```

This sees committed work only; an uncommitted change in another worktree is invisible here, so ask its owner if the deploy surface overlaps.

Stop and reconcile if:

- Another worktree is dirty and touches deploy files.
- Another worktree is ahead and has already deployed.
- Another branch contains production-bound or shared-staging-bound changes that are not in this deploy branch.
- A teammate is actively working on the same deployment surface.

For isolated preview environments with separate URLs and no shared file targets,
this gate is optional. Still record the preview branch and target URL.

## Step 4: Test The Exact Tree

Run the project's normal checks before deploy.

Examples:

```bash
npm test
npm run lint
pytest -q
ruff check .
terraform plan
```

Then verify:

```bash
git diff --check
git status --short
```

A raw wip (or placeholder) commit inside the deploy range blocks a MANUAL build-from-working-tree deploy, because it can ship straight into the built artifact. It does NOT block a pipeline that squash-merges the PR to the default branch (for example `gh pr merge --squash`): the squash collapses every branch commit, wip included, into one commit before the image is built, so the wip never reaches the deployed artifact. Check which path applies before treating a wip commit as a blocking finding.

For production build-artifact deploys, record the artifact digest, image tag, package version, or release ID. For production source deploys, commit and push the exact source tree that passed checks:

```bash
git add <changed-files>
git commit -m "Describe production change"
git push -u origin HEAD
```

For shared staging, run the relevant subset of tests for the changed surface and
record skipped production checks. For release-candidate staging, run production
checks. For ephemeral preview, a pushed commit is preferred but not mandatory if
the target is isolated and short-lived; record the exact local commit, artifact
digest, and dirty-file status.

## Step 5: Deploy Manifest

For file-based, static-site, serverless, CMS, or manual upload deploys, write a manifest before uploading.

Include:

| Field | Required detail |
|---|---|
| Local files or artifact | Every file, image, package, or revision being deployed |
| Environment target | Production, shared staging, staging-only, or preview |
| Target | Service name, bucket path, host path, function, worker, route, or preview URL |
| Live baseline | Current environment revision, pulled live copy, or artifact digest |
| Config dependencies | Required secrets, feature flags, environment variables, or constants |
| Target class | Active production, shared staging, staging-only, legacy, archive, mirror, or isolated preview |
| Smoke checks | URLs, commands, logs, metrics, or workflows that prove success |
| Rollback | Backup path, previous revision, image digest, or restore command |

Do not deploy files that are not in the manifest.

## Step 6: Live Pull And Diff For File Deploys

If production or shared staging deploys replace live files, pull the current live target and diff it against local before upload.

Generic pattern:

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
live_file="/tmp/$(basename "$REMOTE_FILE").live.$STAMP"

# Replace this command with your host, bucket, or provider-specific read.
ssh "$DEPLOY_HOST" "cat '$REMOTE_FILE'" > "$live_file"

diff -u "$live_file" "$LOCAL_FILE" | sed -n '1,200p'
```

Interpretation:

- Only intended feature changes: proceed.
- Live contains another branch's work: merge that branch or patch from live, retest, then deploy.
- Local is missing an emergency hotfix: back-port it locally first.
- The file is legacy or unused: verify the active production route before treating the diff as blocking.
- The live source is unknown: stop and identify it before overwriting.
- The target is isolated preview: live diffing is optional only when the preview does not share files with production or shared staging.

## Step 7: Backup, Upload, Verify

For production or shared-staging file replacement deploys:

1. Back up the live file or ensure the provider keeps restorable revisions.
2. Upload to a temporary path first when the platform allows it.
3. Run syntax checks on the temporary file for interpreted languages.
4. Swap into place.
5. Hash-verify local and remote content.

Example:

```bash
local_hash=$(shasum -a 256 "$LOCAL_FILE" | awk '{print $(1)}')
ssh "$DEPLOY_HOST" "cp '$REMOTE_FILE' '$REMOTE_FILE.bak.$STAMP'"
ssh "$DEPLOY_HOST" "cat > '$REMOTE_FILE.tmp.$STAMP'" < "$LOCAL_FILE"
ssh "$DEPLOY_HOST" "mv '$REMOTE_FILE.tmp.$STAMP' '$REMOTE_FILE'"
remote_hash=$(ssh "$DEPLOY_HOST" "shasum -a 256 '$REMOTE_FILE' | awk '{print \$(1)}'")
[ "$local_hash" = "$remote_hash" ] || { echo "Hash mismatch"; exit 1; }
```

For platform deploys, capture provider output:

- Cloud service revision.
- Container image digest.
- Function version.
- Static hosting deploy ID.
- Database migration version.

## Step 8: Smoke Check

Run checks that prove the changed behavior works in the target environment.

Examples:

```bash
curl -fsS https://example.com/health
curl -fsS https://example.com/api/version
npm run smoke:prod
npm run smoke:staging
provider logs read --freshness=15m
```

Smoke checks should cover:

- Health endpoint or equivalent.
- The route or workflow changed.
- Error logs for the deployed service/environment.
- Metrics or queues if the deploy touches async work.

**Smoke the LIVE production URL, not a revision-tag or preview URL.** On traffic-split platforms you deploy the new revision with no traffic and get a per-revision tag URL. A green check on that tag URL proves the image works; it does NOT prove live traffic serves it. So: flip traffic to the new revision first (for Cloud Run, `gcloud run services update-traffic <svc> --to-revisions=<new>=100`, or the platform equivalent), then smoke the service's real production URL, and confirm the revision now at 100% traffic is the one you built. A tag-URL check that passes while the live URL still serves old code is the classic false pass behind a "deployed dark" outcome (gate 16).

Do not rely on "deploy command exited successfully" as the only verification. A health endpoint returns 200 on the OLD revision too, so `/health` alone never proves your change is live - smoke a route or marker that ONLY the new build serves.

## Step 9: Cache And Propagation

Do not run broad cache purges as a routine deploy step.

Use targeted purges only when:

- A stale URL is reproduced.
- The changed asset or route is known.
- The purge command and target are recorded.

## Step 10: Deployment Record

Report:

- Branch and commit deployed.
- Artifact, revision, or file list deployed.
- Environment class and target changed.
- Tests run before deploy.
- Smoke checks and results.
- Any skipped staging/preview gates and why they were acceptable.
- Backups or rollback pointers.
- Cache purges, if any.
- Any branches or worktrees that still need reconciliation.

When the record lives in a checked-in doc (for example a deploy log), write it to that doc in the same run, not only to chat. If a PENDING record line for this deploy is already on the default branch, flip it to LIVE in the same run (a one-line docs PR). Record-only doc work for a deploy that already shipped is inside "done", never a separate follow-up.

Don't `git worktree add` a second worktree just to edit the deployment record on the default branch - it nests inside the current one. Instead switch the current worktree's branch in place: `git checkout -b docs/<slug> origin/main`, edit, commit, push, open the docs PR.

If deploy was blocked, report the exact gate that failed and the safest next action.
