# Build & Ship Playbook

**Scope:** Cross-project. The house method for building and shipping software
changes. Load on demand before non-trivial build work.

This is the canonical statement of *how to build and ship*. Workflow **skills**
(`dev-quick-build`, `dev-auto-build`, `dev-brainstorming`, `dev-writing-plans`,
`dev-qa-verify`, `deploy-safely`) are the triggered mechanics; this doc is the
standing set of **gates and principles** they all share, plus the map of which
path to take. When a skill and this doc overlap, the skill owns the
step-by-step; this doc owns the *why* and the non-negotiables.

## Pick a path

Two paths, **same gates**. The only difference is how much planning and
coordination the change needs.

| Path | Use when | Flow |
|---|---|---|
| **Quick build** | ONE small feature, one project, ≤ ~a day, **no schema migration, no authz/tier-gate change, no new external integration** | `dev-quick-build` skill (self-contained: worktree → runbook → scout → plan review → TDD → gates → diff review → deploy-safely → browser verify → merge) |
| **Plan-driven** | Migration, authz/security change, multi-phase, multi-subsystem, or anything that trips the dev-quick-build scope gate | `dev-brainstorming` → `dev-writing-plans` → build runbook → per-phase build → **quad review** → `deploy-safely` → post-deploy smoke + persona QA → merge |

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
3. **Local gates green before review.** Backend: lint + full test suite.
   Frontend: full test run + production build (typecheck + bundler). Record
   the counts.
4. **Adversarial review before deploy.** Scale to the diff (see Quad review
   below). Adopt confirmed DEFECTS; adopt cheap test-hardening nits even when
   refuted. A reviewer ENHANCEMENT (a new feature, a bigger refactor, a
   speculative abstraction, hardening beyond the ask) is logged as a
   follow-up, not built - see Scope discipline below.
5. **`deploy-safely` gates, every one.** Origin-safety, main-sync
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

## Quad review (the standard for anything non-trivial)

Independent multi-model review before deploy: four different models at
maximum review effort - see the `codex-review`, `gemini-review`,
`zai-review`, and `fable-review` skills (`ai-debate` for higher-stakes
disputes). Run all four over the *isolated feature diff* (compute it from
the merge-base, not the raw target branch, so unrelated in-flight work
doesn't pollute the review). Then:

- **Synthesize** into one table (finding × model × verdict). Areas all four
  confirm clear are done.
- **Apply the clear fixes**, then re-verify.
- **Run the defect-until-clean loop autonomously.** Fold the confirmed
  DEFECTS, re-run, repeat until no must-fix defect remains or the bound is
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
change. Overbuild rarely enters through the review loop (reviewers find
defects, not features); it enters through the build agent going off-ask.
Hold these:

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
- **Defect vs enhancement in review.** A DEFECT (correctness, security,
  breakage, missing test) is fixed and drives the loop. An ENHANCEMENT (a
  new feature, a bigger refactor, a speculative abstraction, hardening
  beyond the ask) is logged as a follow-up, never built without the owner's
  go-ahead; if it would add new surface area, it is surfaced as a scope
  decision, not folded into a "fix". The good pattern: a reviewer's larger
  suggestion is named as separate scope and routed to the owner, not
  self-adopted mid-build.

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
from source" for a prod service; go through the project's `deploy-safely`
skill or its documented pipeline. If a project's docs still describe a
source-based deploy as the prod path, they are superseded by this section.

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

## Where the deeper detail lives

**Deploy specifics** (commands, service names, integrity gate, migration
procedure, persona roster) are **project-scoped** - keep them in each
project's own `docs/deploy-safely.md` and skills. Do not hoist
project-specific deploy commands into a cross-project doc like this one.

## Why two paths, not one skill

A single "building" skill cannot be both the fast path for a chip-sized
change *and* the entry point for a migration + authz feature - the
dev-quick-build scope gate (which routes the latter out) is the whole value
of the fast path. So: **dev-quick-build stays the small-scope skill; the
plan-driven path is a composition of existing skills; both cite this doc for
the shared gates.** Principles are standing rules (this doc); workflows are
triggered actions (the skills).
