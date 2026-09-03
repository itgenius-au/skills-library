---
name: deploy-safely
description: "Use before production, shared staging, or preview deploys. Verifies environment class, branch freshness, worktree state, tested commits, deploy manifest, smoke checks, and rollback path."
argument-hint: "<service-or-surface> [production|staging|preview] [backend|frontend|infra|cms|container|static|worker]"
---

# Deploy Safely

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

## Environment Classes

| Environment | Use case | Required posture |
|---|---|---|
| Production | Customer-facing app, live API, live CMS/plugin files, production infrastructure | All gates mandatory |
| Shared staging | Long-lived staging, QA, demo, or release-candidate environment used by multiple people | Fetch, test, manifest, active-worktree awareness, smoke checks, and rollback pointer required; default-branch parity depends on whether staging mirrors production |
| Ephemeral preview | Short-lived branch preview or local validation target | Record branch/commit/artifact, URL, checks run, skipped checks, owner, and cleanup path |

Treat staging as production for any surface that uses production data,
production credentials, customer-visible URLs, shared live files, or shared
mutable infrastructure.

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
for wt in $(git worktree list --porcelain | awk '/^worktree / {print $2}'); do
  echo "== $wt =="
  git -C "$wt" status --short --branch
  git -C "$wt" log --oneline --decorate "$DEFAULT_BRANCH"..HEAD --max-count=12 || true
done
```

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
local_hash=$(shasum -a 256 "$LOCAL_FILE" | awk '{print $1}')
ssh "$DEPLOY_HOST" "cp '$REMOTE_FILE' '$REMOTE_FILE.bak.$STAMP'"
ssh "$DEPLOY_HOST" "cat > '$REMOTE_FILE.tmp.$STAMP'" < "$LOCAL_FILE"
ssh "$DEPLOY_HOST" "mv '$REMOTE_FILE.tmp.$STAMP' '$REMOTE_FILE'"
remote_hash=$(ssh "$DEPLOY_HOST" "shasum -a 256 '$REMOTE_FILE' | awk '{print \\$1}'")
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

Do not rely on "deploy command exited successfully" as the only verification.

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

If deploy was blocked, report the exact gate that failed and the safest next action.
