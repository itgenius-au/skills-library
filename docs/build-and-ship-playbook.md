# Build & Ship Playbook

**Scope:** Cross-project. The house method for building and shipping software
changes. Load on demand before non-trivial build work.

This is the canonical statement of *how to build and ship*. Workflow **skills**
(`dev-quick-build`, `dev-auto-build`, `dev-brainstorming`, `dev-writing-plans`,
`dev-qa-verify`, `dev-deploy-safely`) are the triggered mechanics; this doc is the
standing set of **gates and principles** they all share, plus the map of which
path to take. When a skill and this doc overlap, the skill owns the
step-by-step; this doc owns the *why* and the non-negotiables.

## Pick a path

Two paths, **same gates**. The only difference is how much planning and
coordination the change needs.

| Path | Use when | Flow |
|---|---|---|
| **Quick build** | ONE small feature, one project, ≤ ~a day, **no schema migration, no authz/tier-gate change, no new external integration** | `dev-quick-build` skill (self-contained: worktree → runbook → scout → plan review → TDD → gates → diff review → dev-deploy-safely → browser verify → merge) |
| **Plan-driven** | Migration, authz/security change, multi-phase, multi-subsystem, or anything that trips the dev-quick-build scope gate | `dev-brainstorming` → `dev-writing-plans` → build runbook → per-phase build → **review swarm** → `dev-deploy-safely` → post-deploy smoke + persona QA → merge |

**The scope gate is load-bearing.** If a "quick" build turns out to need a
migration or an authz change while scouting, STOP and switch to the
plan-driven path. Do not let a quick build silently become a multi-phase
train.

Both paths end the same way: **watched working in a real browser on the
production URL, deploy recorded, merged to main.** A build is not done when
the code is written, or even when the deploy is green. **"Deployed to
production" / "straight to live" means the new revision serves 100% of live
traffic on the production URL, verified there** - not merely that a new
revision exists. A revision deployed with no traffic and never flipped to
100% is **deployed dark**: present in production, serving nobody. That is not
a finished deploy unless a staged/canary rollout was explicitly requested
(then say so, record it, and hand over the single owed flip).

## Shared gates (non-negotiable, both paths)

1. **Plan first.** Non-trivial work produces a plan/runbook file before
   implementation (`docs/plans/YYYY-MM-DD-<slug>.md` in the project repo).
   The plan is the working state and the mid-session handoff. Confirm the
   date from the environment - never infer it.
2. **TDD.** Failing tests first, confirm they fail for the right reason, then
   implement to green. Mirror the existing test file's mocking and helpers;
   make fixtures *discriminate* (distinct observable output per behavior).
   **Never weaken a test to go green** - no skip/xfail to silence a gap, no
   timeout raised without proof the operation completes, no loosened or
   excluded assertion; disclose any change that reduces what is verified in
   the commit message. **Test the real code:** the test calls the production
   function/handler, never a hand-mirrored copy of its logic (extract the
   logic if it is not callable in isolation).
3. **Local gates green before review.** Backend: lint + full test suite.
   Frontend: full test run + production build (typecheck + bundler). Record
   the counts. Run gates with the **pinned interpreter and locked deps the
   container uses** (or inside the built image), not a bare runner against
   whatever the dev machine has; treat a drop in tests-run (new skips) as a
   regression. **"No gate" is not a passing gate** - a repo with no test
   suite or no CI is a blocking finding to surface, never a silent pass.
4. **Adversarial review before deploy.** Scale to the diff (see Review swarm
   below). Adopt only MUST-FIX defects (critical/high, or medium flagged by
   2+ models; the `review-swarm` must-fix rule) and `simplify` items that
   remove something outside the ask. A quick build reviews its plan with
   `review-swarm` quick mode and its code with two finder agents, one pass
   each. A reviewer ENHANCEMENT (a new feature, a bigger refactor, a
   speculative abstraction, hardening beyond the ask) is logged as a
   follow-up, not built - see Scope discipline below.
5. **`dev-deploy-safely` gates, every one.** Origin-safety, main-sync
   (`behind=0`), local-main publication, wip-free commit range. Rebase onto
   `origin/main` and **re-run the gates + tests after** the rebase.
6. **Build-then-deploy-by-digest + Served-Image Integrity + ancestor gate**
   (container deploys). Never hand-write an ad-hoc "deploy from source" for
   prod. Details below.
7. **Browser verification.** CLI smokes pass while a rendered page is
   broken; the browser pass is what catches that. Interact with every new
   control, don't just look.
8. **Record + merge.** Keep a deploy record (revision, commit sha, image
   digest, markers checked, rollback pointer, suite counts, review result,
   persona-pass status) somewhere durable in the project (a `docs/deployment.md`
   or equivalent log works well). Then publish production parity:
   `git push origin HEAD:main`. Writing that record is part of the same run
   as the deploy, not a deferred chore - a deploy isn't "done" with green
   checks and an unwritten record.
9. **Reference docs land with the change.** For projects with a
   `docs/reference/` tree, a behaviour change updates its reference page in
   the same PR as the code.

## Driving a build agent through a runbook (plan-driven builds)

Plan-driven work is built per phase against a TDD runbook, whether the build
engine is Claude, Codex, or another coding agent.

- **Scope each run.** "Implement Task N (or phase N), touch nothing else.
  TDD: tests first." Group small independent tasks by phase; **isolate
  security/authz tasks into their own carefully-reviewed run.** Disjoint-file
  phases can run in parallel; overlapping ones stay sequential.
- **Scale reasoning effort to risk.** Routine, pre-decomposed execution needs
  less effort than a model can burn (over-thinking a well-scoped task can
  measurably *hurt* test-pass rate and cause over-editing). Reserve your
  highest effort setting for genuinely hard execution - data-plane
  migrations, security/authz changes, architectural work - and for **all
  reviews**.
- **Verify independently - never trust the agent's self-report.** After each
  run: read the diff yourself, confirm scope, run the tests yourself. "Agent
  reports success" is not "verified."
- The runbook is the durable artifact. Keep it updated as phases complete;
  squash working commits into a clean commit at the end.

## Review swarm (the standard for anything non-trivial)

**Quick builds are sized for speed.** `dev-quick-build` reviews its plan with
`review-swarm` quick mode (four models, one round, each capped at about ten
minutes, for every quick build including authz, migration, secrets or
data-write changes) and its code with one pass of two finder agents. The
four-model panel and the defect-until-clean loop below are the
`dev-auto-build` and `dev-writing-plans` path.

Independent multi-model review before deploy: four different models at
maximum review effort - see the `review-with-codex`, `review-with-gemini`,
`review-with-glm`, and `review-with-claude` skills (`review-debate` for
higher-stakes disputes). Run all four over the *isolated feature diff* (compute it from
the merge-base, not the raw target branch, so unrelated in-flight work
doesn't pollute the review). Then:

- **Synthesize** into one table (finding × model × verdict). Areas all four
  confirm clear are done.
- **Apply the clear fixes**, then re-verify.
- **Run the defect-until-clean loop autonomously.** Fold the MUST-FIX
  defects, re-run, repeat until no must-fix defect remains or the bound is
  hit (the build skills cap the cycles). The exit is the absence of defects,
  NOT the reviewers running out of suggestions - four models always propose
  more; advisory enhancements do not hold the gate open. The gate returns
  its findings to the calling build/plan skill, which keeps looping; it does
  NOT stop to hand the owner a follow-up menu.
- **Escalate to the owner - and only for these two things - from inside the
  loop:** a genuine design / trust decision (e.g. a trust-model choice a
  reviewer flags), and an enhancement whose adoption would add new surface
  area beyond the ask/plan (a feature, endpoint, flag, dependency, or
  abstraction). Don't fold a decision or new scope into a "fix." Everything
  else the loop handles itself.
- Watch for **false positives from a truncated diff** - if the review bundle
  omitted tests or the migration, discount "missing tests/migration"
  findings after confirming they exist.

## Scope discipline (both paths)

The house method is thorough on correctness; it is NOT a licence to grow the
change. Overbuild enters two ways: the build agent going off-ask, and the
review loop folding in every finding (builds can come out several times the
size of the ask and over-restricted). So reviewers get THE ASK, only
must-fix defects drive a loop (the `review-swarm` must-fix rule), and
reviewers also report what to remove (`simplify`). Hold these:

- **Simplest path.** Build the simplest change that satisfies the ask/plan
  and passes the gates. The ask (quick build) or plan (plan-driven) is the
  scope ceiling, not a floor: smallest correct diff, no gold-plating, no
  abstraction for a future the ask did not name, no hardening code the
  change did not touch.
- **The ask is the fence.** Do not start unrequested work mid-build: no
  ripple-fixing unrelated files, no "while I am here" cleanups, no
  refactoring or re-homing the task did not ask for. Spot something worth
  doing? Log it as a follow-up; do it only if the owner says yes.
- **Unsupervised means tighter, not looser.** The longer the owner is away,
  the narrower you stay. An OK for task X is not an OK for the adjacent
  thing you noticed on the way.
- **Defect vs enhancement in review.** A MUST-FIX defect (critical/high, or
  medium flagged by 2+ models) is fixed and drives the loop; other defects
  are advisory. An ENHANCEMENT (a
  new feature, a bigger refactor, a speculative abstraction, hardening
  beyond the ask) is logged as a follow-up, never built without the owner's
  go-ahead; if it would add new surface area, it is surfaced as a scope
  decision, not folded into a "fix". The good pattern: a reviewer's larger
  suggestion is named as separate scope and routed to the owner, not
  self-adopted mid-build.
- **Refuse by default only where it is earned.** In the thing you build (not
  the deploy and CI gates, which still abort), a refusal, a typed
  confirmation token, or a "stop until a named person confirms" step
  belongs only on an action that is irreversible and destructive, or that
  moves money with no human in the loop. Everywhere else: warn, log, and
  continue. A human-in-the-loop skill trusts the human - the user's "go"
  approves the action, including a money action or a customer send; do not
  add a second confirmation word. An UNKNOWN answer is a warning to show,
  not a reason to refuse. Fail-closed defaults built into ops tools block
  normal work and have to be loosened later.

## Stuck loops and escalation (both paths)

- **Second identical failure: stop attempting, start diagnosing.** A failure
  that repeats for the same root cause (not just the same test name) means
  the current approach will not fix it. Before spending another bounded
  attempt, diagnose off the failing path - one hypothesis, proven against
  live state (the `dev-debugging` discipline) - then let that drive the next
  attempt. The numeric cap (fix-runs, review cycles) is a ceiling, not
  permission to re-try an unchanged cause.
- **A delivered-nothing outcome is escalated, not silently closed.** A task
  whose gates pass but whose measurable objective came back flat or worse is
  a negative outcome: state the before/after plainly and hand it up with
  options, never mark it done. A plan's conditional wording authorizes
  trying, not silently dropping the objective.
- **An unattended-run STOP must reach a human.** In a scheduled or
  dispatched run with no one watching, an escalation posts an active
  notification (team chat / push) in the same run - not just a flipped
  status field nobody is polling.

## Database migrations (plan-driven only; dev-quick-build excludes them)

Migrations do **not** run on deploy - apply them **manually, before** the
code deploy, and **inspect before upgrading**:

- Connect through your database's secure tunnel or proxy; pull credentials
  from your secret manager (never print a full connection string to logs or
  chat).
- Check what production is currently at and what "upgrade to head" would
  apply (e.g. `alembic current` + `alembic history -r current:head`, or your
  migration tool's equivalent). **Confirm the only pending revision is
  yours** before running the upgrade. If anything unexpected is pending,
  STOP.
- Keep migrations **additive** where possible (a new table/column is dormant
  under old code, so it is safe to apply before the deploy and safe to leave
  if you roll back the code). Record the exact downgrade target as the
  rollback pointer.
- The shared-DB caveat: a migration is a production data change even when
  you are "just deploying staging" if the environments share a database.
  Confirm first.

## Container deploy gates (the integrity trio)

**Applies to every service that deploys as a container image** (Cloud Run,
ECS, Kubernetes, or similar). Never hand-write an ad-hoc "deploy straight
from source" for a prod service; go through the shared `dev-deploy-safely`
skill (or the project's own deploy skill where one exists) or its documented
pipeline. If a project's docs still describe a
source-based deploy as the prod path, they are superseded by this section.

**Gold standard: deploy from CI.** Every container deployable ships from a CI
pipeline (for example GitHub Actions) in one shape: a `staging` branch
deploys staging and the default branch deploys production, both on `push`;
one deployer identity per environment, bound by workload identity federation
to its branch, no long-lived keys; build once, deploy **by digest** with no
traffic, then the ancestor gate, flip, Served-Image Integrity and smoke, each
gate aborting; branch rulesets require a PR and the full CI suite; a merge
allowlist on the default branch wherever people outside engineering hold
write. The checks below are what those workflows run. Running them by hand
(or via `dev-deploy-safely`) is for a repo that has not moved yet, or a
rollback. A build-system trigger that deploys a tag straight to 100% traffic
is **not** the standard.

A deploy-from-source shortcut can pin a **stale image digest** - a green
"deployed" that silently serves old code with a health check still passing.
Defend with checks structured to **abort, not print**:

1. **Build-then-deploy-by-digest.** Build the image and tag it with the
   commit sha, resolve the build system's *manifest* digest (not a
   log-grepped layer digest), then deploy that image **by digest** with
   **no traffic yet**, labelled with the branch and sha it came from.
2. **Content-verify the built image** before flipping any traffic - pull a
   file or hit an internal endpoint on the *new, untrafficked* revision and
   grep for a marker only the new build contains (a new route in an API
   schema, or a code string if the change adds no route).
3. **Ancestor gate - the anti-clobber invariant.** Immediately before the
   flip: the sha of the revision **currently serving 100% of traffic** (not
   any 0%-traffic tag) must be an ancestor of the HEAD you just built. Then
   flip traffic, then re-assert **Served-Image Integrity** (the digest
   actually serving 100% of traffic equals the digest you built). Most
   platforms do **not** auto-migrate traffic to a new revision - flip it to
   100% explicitly, then smoke a feature route on the **live URL** (not a
   per-revision preview URL). Until that flip, the new revision sits at 0%
   traffic (**deployed dark**) and the live URL still serves old code; a
   green check against the preview URL is the false pass that hides it. The
   deploy is not done until the 100%-traffic entry is your new revision and
   the live URL serves it.
4. **For any service with scheduled/cron jobs: verify after the next
   scheduled run, not only at deploy time.** A deploy-time check proves the
   image is serving; it does not prove the next scheduled run agrees with
   it. Trigger the job on demand or wait out the schedule, **then** re-read
   the data. Where the change encodes a decision (a classifier, a guard, a
   remap), pair it with a monitor whose predicates mirror the guard
   **exactly** - a monitor narrower than the guard is a blind spot.

> **The gate must ABORT, not echo.** Run the deploy as one script where each
> check exits non-zero on failure and the traffic flip physically follows
> the checks in code, not in a human reading a printed warning. An
> echo-only gate has caused a real production revert in the wild. Structure,
> not vigilance.

**Where a project has push-to-deploy CI** (merge to the main branch deploys
via a pipeline that codifies these gates, protected by branch rules and a
required reviewer), the manual recipe is break-glass only: build → PR →
merge; the pipeline deploys. Migrations stay a separate manually-approved
step; browser and persona verification stay a post-deploy pass.

**Further container-deploy correctness checks** worth keeping in your own
checklist, each keyed to an incident in your history: manual-vs-auto-deploy
races, env-var replace-vs-merge, smoking through the deployed service's own
identity, background-work durability, the per-service ingress/auth contract,
full-tree rebase, CI `concurrency:` groups, and dependency/supply-chain
scanning.

## Docs and skill edits are not a build

A change that only touches docs, agent skills, agent config or notes does not
run the build path (no quick-build ceremony, no review swarm). Open a
short-lived PR and merge it once the repo's required checks pass. First prove
the merge does not deploy (see the `dev-deploy-safely` section "Does merging this deploy?"): a merge that deploys is a production deploy,
whatever it touches.

**Give push-to-deploy repos a docs route.** Where every merge to the default
branch deploys, a docs-only merge rebuilds and redeploys production for
nothing. The pattern:

- Keep `on: push` with **no** `paths` / `paths-ignore` filter. A first
  `changes` job decides, and the deploy job runs unless that job succeeded
  and said "no deploy" (a failed job still publishes its outputs, so check
  its result too).
- Diff from the `git-sha` label of the revision serving **100%**, not from the
  push's `before` sha. Code stranded by a failed or cancelled deploy then
  ships with the next merge, docs-only or not.
- **Fail closed.** Skip only when every changed path is on a narrow docs
  allow-list that is disjoint from the image's `COPY` set. No label, a cloud
  CLI error, bad output, or any manual re-run means deploy. A re-run keeps
  the same commit, so it is the redeploy-without-a-commit lever. Add no
  manual-dispatch trigger on the production branch: it bypasses the merge
  allowlist.
- CI stays unfiltered: the required PR checks run on every PR, and `changes`
  is never a required check (a check that goes green without running tests
  is how untested code reaches prod).
- After a traffic rollback, revert the default branch to match. Otherwise the
  next merge, docs-only included, redeploys the rolled-back code.

## Browser / persona verification

- Use your agent's browser integration in your own signed-in session. Never
  type credentials - hand SSO account-picks to the human.
- Verify each acceptance point by **interacting** (click every new control,
  check counts and orders against what the data implies), screenshot
  evidence.
- **View-only for side-effecting actions.** Confirm a gated control *renders
  and opens*, but do not submit an action that creates real infra or data on
  a real account as a "smoke test". Find real qualifying data (a read-only
  query) to make the render check meaningful and safe.
- Impersonation/persona rosters are project-scoped - keep them in the
  project's own QA skill or a `docs/test-protocol.md`.
- If no browser is available this session, record the persona pass as
  **OWED** (standing convention) and say so in the summary.
- **A failed check is not automatically a product defect.** Before routing a
  browser/QA failure back to the build, confirm the check actually reached
  the target on the real surface and that the rendered result - not a
  timeout, stale selector, or tooling hiccup - is what failed. Never resolve
  a tooling failure by loosening a wait or an assertion.
- **Do not fake the journey.** Exercise the real control under test; never
  substitute a direct DB write, an internal-only endpoint, or a deep link for
  the action being verified (setup/teardown around it is fine).
- **Rendered evidence rules.** A backend/log/DB check corroborates but never
  overrides a contradictory screenshot; when they disagree, the rendered page
  is the finding.
- **No test-only backdoors in production code** - no hidden route, flag, or
  field added just so a checker can observe something a real user could not
  (a stable `data-testid` is fine).

## Where the deeper detail lives

**Deploy specifics** (commands, service names, integrity gate, migration
procedure, persona roster) are **project-scoped** - keep them in each
project's own `docs/dev-deploy-safely.md` and skills. Do not hoist
project-specific deploy commands into a cross-project doc like this one.

## Why two paths, not one skill

A single "building" skill cannot be both the fast path for a chip-sized
change *and* the entry point for a migration + authz feature - the
dev-quick-build scope gate (which routes the latter out) is the whole value
of the fast path. So: **dev-quick-build stays the small-scope skill; the
plan-driven path is a composition of existing skills; both cite this doc for
the shared gates.** Principles are standing rules (this doc); workflows are
triggered actions (the skills).
