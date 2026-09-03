---
name: quick-build
description: Build and ship ONE small, well-scoped feature end to end in a single session - worktree isolation, dated runbook doc kept updated throughout, triple review of the plan (Codex+Gemini+GLM) before any code, TDD, full local gates, adversarial multi-agent review, deploy-safely production gates, deploy-by-digest, and live browser verification via Claude in Chrome. Use whenever the user hands over a single concrete feature or UI tweak and wants it built AND shipped ("add a chip for X", "make this table sortable", "rename this and change what it counts", "build and deploy if the gates pass"). Triggers on - quick build, quickbuild, build and ship, ship this small change, small feature end to end, build this and deploy.
---

# Quick Build

Ship one small feature idea from request to verified production, in one session,
using rigorous building/testing/deploy practices. The whole point is *end to end*:
a quick build is not done when the code is written, or even when the deploy is
green - it is done when the change has been watched working in a real browser on
the production URL and the deploy record says so.

> **This skill is the small-scope FAST PATH.** The shared build/ship gates it runs -
> TDD, local gates, adversarial (triple/multi-model) review, worktree isolation,
> deploy-safely, build-then-deploy-by-digest + Served-Image Integrity + ancestor gate,
> browser verification, deploy record + merge - are the non-negotiable gates of a rigorous
> build method; keep them in sync with your project's own build/deploy playbook if you have
> one. The plan-driven path (migration / authz / multi-phase) routes out of quick-build via
> the scope gate below - use `writing-plans` / `brainstorming` / `auto-build` for that.

> **Deploy is part of the job, not a separate approval.** Invoking Quick Build IS
> the decision to ship on green. A request that fits the scope gate runs the FULL
> pipeline *through production deploy* the moment every gate passes - you do NOT
> pause to ask "should I deploy?" on a clean build. The word "deploy" does not have
> to appear: **"fix this", "quick fix", "tweak this", "sort the table", "build X"**
> all mean build-AND-ship here. This is a deliberate, standing override of the
> global "confirm before deploy" guardrail, scoped to this flow (full detail +
> the exhaustive stop-list in Phase 7). The ONLY reasons to stop are: a mandatory
> gate fails or cannot run, the scope gate trips mid-build (migration / authz /
> multi-subsystem), or a genuine product/design/trust decision surfaces. "Wait for
> approval on a passing build" is never one of them. If you catch yourself asking
> the user to okay a green deploy, re-read this line and proceed instead.

## Scope gate (run this first, in your head)

Quick Build fits: one feature, one project, roughly ≤ a day of work, no schema
migrations, no authz/tier-gate changes, no new external integrations. Frontend
tweaks, a new filter/chip/column, a small endpoint addition, copy + behavior
changes.

If scouting reveals the ask actually needs a migration, an authz change, or
touches several subsystems, STOP and say so - route to `writing-plans` /
`brainstorming` instead. Do not let a "quick" build silently become a train.

## Phase 0 - Worktree + context

- Work in an isolated git worktree, not your main checkout: create/enter one and
  bind the session to it. Verify `git rev-parse --show-toplevel` IS the worktree
  path before any edit, and address every file by the worktree path for the rest
  of the session.
- Confirm today's date from the environment (`currentDate` or `date`) NOW - the
  runbook filename and every doc header depend on it. Never infer the date.

## Phase 1 - Runbook doc (create BEFORE building, update as you go)

Create `docs/plans/YYYY-MM-DD-<slug>-quick-build.md` in the project repo (inside
the worktree) with a `**Date:** YYYY-MM-DD` header and these sections:

```
# <Feature> - Quick Build
**Date:** YYYY-MM-DD  |  **Branch:** wt/<name>  |  **Status:** in progress
## Ask (verbatim)
## Decisions          <- semantics you chose + why (data-model grounding)
## Scout findings     <- where the code lives, patterns reused, key facts
## Build log          <- updated at each phase: tests red -> green, gates, review
## Deploy             <- pointer to the docs/deployment.md entry + rollback
## Follow-ups
```

The runbook is the working state and the handoff if the session dies mid-flight.
Update it at every phase transition (a one-line append is enough) - not
retrospectively at the end. Commit it with the feature.

## Phase 2 - Scout (read before writing)

- Read the actual page/module you are changing and the components it uses.
- Ground every semantic decision in the data model, not the label. ("Inactive"
  meant nothing until the backend showed pips = green <30d / yellow 30-89d /
  red 90+d and that suspended users were excluded server-side.) Write the
  chosen definition into the runbook's Decisions section.
- Hunt for an existing precedent before inventing UI: the design system usually
  already has the pattern (e.g. `c-sortable`/`c-sort-button`/`c-sort-arrow` on
  the Devices page). Reusing it is both faster and the design-system rule.
- Read the project's required docs (e.g. its design-system reference and any
  architecture pointers in its CLAUDE.md).
- Verify data-source assumptions in the backend code, not from memory (e.g.
  "does this endpoint return suspended users?" - grep the integration).

## Phase 3 - Triple review of the plan (before any code)

The runbook is now a real plan, not a skeleton: Phase 2 filled the Decisions and
Scout findings sections. Review THAT plan with the full triple - Codex +
Gemini + GLM - BEFORE writing a line of code. A wrong semantic or an unverified
data-source assumption caught here costs a paragraph edit; the same miss caught in
the Phase 6 diff review costs a rebuild.

- Run all three in parallel over the runbook file, each pointed at
  `docs/plans/YYYY-MM-DD-<slug>-quick-build.md`: the `codex-review`,
  `gemini-review`, and `zai-review` (GLM) skills. Ask each the same four
  questions: is the chosen semantic correct against the data model; is any
  data-source assumption still unverified; is the scope still inside the
  quick-build gate; is anything material missing or wrong.
- Cycle findings back INTO the plan, not into a debate. Adopt confirmed
  corrections, update the Decisions / Scout findings sections, and re-run a model
  only if a fix changed the approach materially. Record the review result (models
  run, what changed) in the runbook's Build log section.
- This is a gate, not a formality. If a reviewer surfaces that the ask needs a
  migration, an authz/tier-gate change, or a multi-subsystem blast radius, the
  scope gate has tripped - STOP and route to `writing-plans` / `brainstorming`
  (the Phase 7 stop-list applies here too). If a genuine product / design / trust
  decision surfaces, escalate to the user rather than settling it inside the plan.
- Keep it proportional: a one-file tweak gets a quick three-model pass; a
  cross-cutting change gets a thorough one. Three independent models is the floor,
  not the ceiling.
- This stays the FAST PATH - it is NOT the plan-driven / auto-build loop. You do
  NOT stop to write a formal plan, and you do NOT hand the runbook to an
  autonomous cycle-until-clean loop. It is a single sanity pass over the
  lightweight runbook: read the three verdicts, apply the corrections yourself,
  move on to Phase 4. That single human-driven pass over a small runbook is
  exactly what differentiates a quick build from `auto-build`. (The Phase 6 diff
  review is a separate, later gate over the built code.)

## Phase 4 - TDD

Failing tests first (superpowers:test-driven-development). Mirror the existing
test file's mocking and helper patterns rather than importing new tooling. Run
the new tests, confirm they fail FOR THE RIGHT REASON, then implement, then
green. Fixtures should discriminate: if two sort orders can coincide, redesign
the fixture so each behavior produces a distinct observable order.

## Phase 5 - Local gates

Frontend: full `npm test` + `npm run build` (tsc + bundler). Backend touched:
`uv run --extra dev ruff check src` + full pytest. All green before review.
Fresh worktrees need `npm ci` first. Record counts in the runbook.

## Phase 6 - Adversarial review (scale to the diff)

Run a multi-agent Workflow review over the committed diff: dimension finders
(correctness / framework behavior / design-system+a11y / test adequacy) then
2-3 independent skeptics per finding, majority-refute kills it. Scale the panel
to the change - a one-file tweak gets 2 dimensions, a cross-cutting change gets
4. Adopt confirmed findings; adopt cheap test-hardening nits even when refuted
if they cost minutes. Test-only follow-up commits do not require rebuilding an
already-built image (tests do not ship in the artifact) - record both shas.

**Review agents mutate the tree they run in.** Test-adequacy refuters
answer "would this test still pass if the guard were deleted?" by actually deleting
it, and they do not always revert; the Stop-hook auto-commit will happily sweep their
probes (and any `tests/test_probe_*_tmp.py`) into a `wip` commit mid-review. Run the
panel with `isolation: "worktree"` on each `agent()` call, or, if it must run in the
session worktree, checkpoint-commit BEFORE launching it and, after it completes,
require `git diff <checkpoint> --stat -- src tests` to list only your intended files
before any gate, commit, or squash (revert strays with `git checkout <checkpoint> -- <file>`).
Never run Phase 5/7 gates while a panel is still running.

## Phase 7 - Deploy (gates decide, not optimism)

**Autonomous on green - do NOT pause for a human go-ahead.** When every gate in
this skill passes (full test suite green, local build green, adversarial review
clean or all confirmed findings fixed, and every `deploy-safely` gate green),
proceed straight to deploy and merge to production. Do not stop to ask the user for
approval. The gates ARE the pass/fail criteria this autonomy runs on, so the
"autonomous pipeline needs measurable pass/fail criteria" rule is satisfied by
running them, not by a human sign-off. This is a deliberate, standing override
of the global "confirm before deploy" guardrail, scoped to the quick-build flow
only. (In some projects "deploy to production" = merge the branch to `main` and a
CI pipeline deploys prod on that merge.)

Invoke the project's `deploy-safely` skill and run EVERY gate it names - origin
safety, main sync (behind=0), local-main publication, wip-free range. Then the
project's deploy recipe. For Cloud Run:

- Build-then-deploy-by-digest (`gcloud builds submit --tag <repo>:<slug>-<sha>`,
  resolve the digest, deploy `--image <repo>@<digest> --no-traffic` with
  `--labels=git-branch=...,git-sha=...`). Never `--source` for prod.
- Pre-flip verify on a revision tag URL: fetch the served bundle and grep for
  marker strings that ONLY the new build contains. Zero markers = wrong image.
- Flip traffic, then the Served-Image Integrity gate: compare the built digest
  to the image of the **percent=100 traffic entry** - `status.traffic[0]` may
  be a 0% tag entry, which reads as a false MISMATCH.
- Smoke: prod URL 200 serving the new bundle + markers, backend /health canary,
  revision log review (zero warnings).
- Record in `docs/deployment.md` (same entry style as prior records): revision,
  sha, digest, markers, rollback pointer (`update-traffic <prev-rev>=100`),
  suite counts, review result, persona-pass status. Update the runbook Deploy
  section to point at it.
- Push the branch, then publish production parity: `git push origin HEAD:main`.
  If it rejects (origin/main moved), see Deploy contention below.

Green means go, autonomously. Stop and surface to the user ONLY in these cases -
they are the whole exception list, and none of them is "wait for approval on a
clean build":

- **A mandatory gate fails or cannot run** this session: red tests, a failed
  build, an ancestor/Served-Image-Integrity mismatch, a confirmed correctness or
  security finding you cannot cleanly fix, or no way to run a required gate.
  Then do NOT deploy - stage everything, record why in the runbook, and hand off.
- **The scope gate trips mid-build**: scouting reveals a migration, an authz/
  tier-gate change, or a multi-subsystem blast radius. Stop and route to
  `writing-plans` / `brainstorming` - a quick build must not silently become a
  train.
- **A genuine product, design, or trust decision surfaces** (e.g. a reviewer
  flags a trust-model choice). Escalate it rather than deciding unilaterally -
  that is a decision, not a gate.

Browser verification (Phase 8) still runs, but its absence does not block the
deploy: if no browser is available this session, deploy on green and record the
persona pass as OWED (the standing convention), same as before.

## Phase 8 - Browser verification (Claude in Chrome)

CLI smokes pass while rendered pages are broken - the browser pass is what
catches that. Using the Claude-in-Chrome extension (the user's preferred browser
tool - use it freely):

- `tabs_context_mcp` first; batch actions with `browser_batch`.
- If the app is signed out: click the SSO button, but the extension cannot act
  on accounts.google.com (and must not) - hand the account-pick to the user with
  one clear sentence, then continue after he confirms. NEVER type credentials.
- Verify each acceptance point of the ask by interacting, not just looking:
  click every new control, check counts/orders against what the data implies,
  screenshot evidence.
- Update the deployment.md persona-pass line from OWED to DONE with what was
  verified. If no browser is available this session, record the pass as OWED
  (the standing convention) and say so in the final summary.

## Deploy contention - two quick-builds racing the same project

The clobber risk is *tree omission*: flipping to an image whose git tree does not
contain what production already serves. The **ancestor gate** (Phase 7, part of the
integrity trio: build-by-digest + Served-Image Integrity + ancestor gate) is the
invariant that prevents it - and it must **abort, not echo** (a `set -e` script with `|| exit 1`, flip physically
after the checks). Contention-specific operational rules:

- Deploy from a pushed worktree branch, never through the shared main checkout.
- `git fetch origin` immediately before the ancestor check + flip - that is the
  serialization point. First to flip wins; the loser merges the winner (usually a
  disjoint-file merge), reruns tests, rebuilds, flips. This terminates (each round
  is forward progress, not wait-and-retry), so a race costs one rebuild round, never
  a regression.
- If `push origin HEAD:main` rejects, someone else pushed: merge `origin/main` and
  push again - your deploy is already serving and its sha is in the merge.
- Known contention up front → prefer a deploy train (one session ships both branches).
  Check the Claude Live Monitor for another active deploy before Phase 7.
- WordPress files have no revisions: deploy-safely's pull-live-and-diff gate is the
  equivalent invariant - live is the baseline, always.

## Wrap

Final summary leads with what shipped and where, the verified evidence, the
rollback pointer, and anything owed. Close out via `session-wrap` (squash your
wip commits into one clean commit before pushing) as usual; the worktree merge
to main already happened as part of Phase 7.
