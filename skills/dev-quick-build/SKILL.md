---
name: dev-quick-build
description: Build and ship ONE small, well-scoped feature end to end in a single session - worktree isolation, dated runbook doc kept updated throughout, quad review of the plan (Codex+Gemini+GLM+Fable) before any code, TDD, full local gates, adversarial multi-agent review, deploy-safely production gates, deploy-by-digest, and live browser verification via Claude in Chrome that loops back to fix, re-review and redeploy if it catches a break. Use whenever the user hands over a single concrete feature or UI tweak and wants it built AND shipped ("add a chip for X", "make this table sortable", "rename this and change what it counts", "build and deploy if the gates pass"). Triggers on - quick build, quickbuild, build and ship, ship this small change, small feature end to end, build this and deploy.
---

# Quick Build

Ship one small feature idea from request to verified production, in one session,
using a rigorous building/testing/deploy method. The whole point is *end to end*:
a quick build is not done when the code is written, or even when the deploy is
green - it is done when the change has been watched working in a real browser on
the production URL and the deploy record says so.

> **This skill is the small-scope FAST PATH.** The shared build/ship gates it runs
> (TDD, local gates, adversarial review, deploy-safely, build-by-digest + integrity +
> ancestor gate, browser verification, record + merge) are the non-negotiables of a
> rigorous build method - the same gates apply on the plan-driven path (migration /
> authz / multi-phase, which the scope gate below routes out of dev-quick-build and into
> `dev-writing-plans` / `dev-brainstorming` / `dev-auto-build`). This skill owns the
> fast-path mechanics; wire it to your project's own build/deploy playbook where one
> exists.

> **Deploy is part of the job, not a separate approval.** Invoking Quick Build IS
> the decision to ship on green. A request that fits the scope gate runs the FULL
> pipeline *through production deploy* the moment every gate passes - you do NOT
> pause to ask "should I deploy?" on a clean build. The word "deploy" does not have
> to appear: **"fix this", "quick fix", "tweak this", "sort the table", "build X"**
> all mean build-AND-ship here. This is a deliberate, standing override of a
> "confirm before deploy" default, scoped to this flow (full detail + the exhaustive
> stop-list in Phase 7). The ONLY reasons to stop are: a mandatory gate fails or
> cannot run, the scope gate trips mid-build (migration / authz / multi-subsystem),
> or a genuine product/design/trust decision surfaces. "Wait for approval on a
> passing build" is never one of them. If you catch yourself asking the user to okay
> a green deploy, re-read this line and proceed instead.

> **Ship it LIVE, not dark.** "Done" means the change is serving real users in
> production, observably doing its job. "Dark" has TWO forms and BOTH are banned as a
> dev-quick-build end state: **(1) a 0%-traffic revision** - a Cloud Run (or other
> traffic-split) revision deployed with no traffic and never flipped to 100%, so the
> live production URL still serves old code; and **(2) a feature behind an OFF flag** -
> code live at 100% traffic but the switch off. Form (1) is the one that quietly bites:
> the deploy reads green on the revision's tag URL while nothing changed on the live URL.
> Neither is a finished quick build: you MUST flip traffic to 100% and smoke the live
> URL (form 1) AND ship any flag you introduced ON (form 2).
> A feature flag or kill-switch is welcome (it is how you roll back in one env-only
> step), but it must ship ENABLED: its default is on, or you set it on as part of THIS
> deploy, and Phase 8 verifies the behaviour live with the flag on. Shipping "dark" (the
> flag off, a flip owed to someone later) is NOT a valid dev-quick-build end state - dark
> code sits un-flipped and the feature never actually lands. The ONLY exceptions: the
> user explicitly asks for a dark / staged rollout, or a mandatory gate genuinely blocks
> enabling it live this session (e.g. a live dependency only a shadow pass can confirm) -
> and then you SAY so, record why, and hand the user the single flip that is left.
> Absent that, a flag you introduced is enabled before you call the build done.

## Scope gate (run this first, in your head)

Quick Build fits: one feature, one project, roughly ≤ a day of work, no schema
migrations, no authz/tier-gate changes, no new external integrations. Frontend
tweaks, a new filter/chip/column, a small endpoint addition, copy + behavior
changes.

If scouting reveals the ask actually needs a migration, an authz change, or
touches several subsystems, STOP and say so - route to `dev-writing-plans` /
`dev-brainstorming` instead. Do not let a "quick" build silently become a train.

**Simplest path, and the ask is the fence.** Build the simplest change that satisfies the ask and
passes the gates. The ask is the scope ceiling, not a floor: prefer the smallest correct diff, do not
gold-plate, do not add abstraction for a future the ask did not name, do not harden code this change
did not touch. And do not start unrequested work mid-build - no ripple-fixing unrelated files, no
"while I am here" cleanups, no refactoring or re-homing the task did not ask for. Spot something worth
doing? LOG it in the runbook Follow-ups and move on; do it only if the user says yes. This holds
double when the user is away: unsupervised means tighter scope, never looser - an OK for this feature
is not an OK for the adjacent thing you noticed.

## Phase 0 - Worktree + context

- Work in an isolated worktree. If your setup has a context-switch skill that
  creates the worktree, pushes the branch, and binds the session (via
  EnterWorktree), use it; otherwise create the worktree yourself. Either way:
  verify `git rev-parse --show-toplevel` IS the worktree path before any edit,
  and address every file by the worktree path for the rest of the session.
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
## Deploy             <- pointer to the project's deploy-log entry + rollback
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
  a devices page). Reusing it is both faster and the design-system rule.
- Read the project's required docs (e.g. a design-system reference and any
  architecture/rewrite pointers named in its CLAUDE.md).
- Verify data-source assumptions in the backend code, not from memory (e.g.
  "does this endpoint return suspended users?" - grep the integration).

## Phase 3 - Quad review of the plan (before any code)

The runbook is now a real plan, not a skeleton: Phase 2 filled the Decisions and
Scout findings sections. Review THAT plan with the full quad review panel - Codex +
Gemini + GLM + Fable - BEFORE writing a line of code. A wrong semantic or an unverified
data-source assumption caught here costs a paragraph edit; the same miss caught in
the Phase 6 diff review costs a rebuild.

- Invoke the **`quad-review`** skill in `plan` mode on the runbook
  (`docs/plans/YYYY-MM-DD-<slug>-quick-build.md`). It fans Codex + Gemini + GLM + Fable
  out in parallel and returns one synthesized, consensus-tagged verdict - no
  hand-rolled fan-out. Ask it the same four questions: is the chosen semantic
  correct against the data model; is any data-source assumption still unverified;
  is the scope still inside the dev-quick-build gate; is anything material missing or
  wrong.
- Cycle findings back INTO the plan, not into a debate. Adopt confirmed
  DEFECTS (a wrong semantic, an unverified data-source assumption, a real gap),
  update the Decisions / Scout findings sections, and re-run a model only if a fix
  changed the approach materially. A reviewer ENHANCEMENT (a nice-to-have feature,
  a bigger refactor, a speculative abstraction, hardening beyond the ask) does NOT
  go into the plan - log it in the runbook Follow-ups. If an enhancement would add
  new surface area beyond the ask, surface it to the user as a scope decision;
  never self-adopt it. Record the review result (models run, what changed) in the
  runbook's Build log section.
- This is a gate, not a formality. If a reviewer surfaces that the ask needs a
  migration, an authz/tier-gate change, or a multi-subsystem blast radius, the
  scope gate has tripped - STOP and route to `dev-writing-plans` / `dev-brainstorming`
  (the Phase 7 stop-list applies here too). If a genuine product / design / trust
  decision surfaces, escalate to the user rather than settling it inside the plan.
- Keep it proportional: a one-file tweak gets a quick single-model pass; a
  cross-cutting change gets the full panel. Three independent external models plus
  Fable is the standard for a substantive review, not a ceiling to always max out.
- This stays the FAST PATH - it is NOT the plan-driven / `dev-auto-build` loop. You do
  NOT stop to write a formal plan, and you do NOT hand the runbook to an
  autonomous cycle-until-clean loop. It is a single sanity pass over the
  lightweight runbook: read the verdicts, apply the corrections yourself,
  move on to Phase 4. That single human-driven pass over a small runbook is
  exactly what differentiates a quick build from `dev-auto-build`. (The Phase 6 diff
  review is a separate, later gate over the built code.)

## Phase 4 - TDD (test-driven development)

Write the failing test FIRST, before the implementation - the standard Red-Green-Refactor
discipline, inlined here (no external sub-skill needed):

1. **Red** - write the test(s) for the new behaviour against the real data
   shape. Mirror the existing test file's mocking and helper patterns rather
   than importing new tooling. Run them and confirm they fail FOR THE RIGHT
   REASON (the behaviour is genuinely missing), not from a typo or a bad import.
2. **Green** - implement the minimum that makes them pass. Do not gold-plate.
3. **Refactor** - clean up with the tests green as the safety net.

Fixtures must discriminate: if two sort orders (or two states) can coincide,
redesign the fixture so each behaviour produces a distinct observable result - a
test that passes for the wrong reason is worse than no test. And exercise any
write path the default run does not (a dry-run/apply split, a path behind an
`if apply:` guard): add a test that runs the REAL path against the REAL payload
shape, or it can ship broken while the suite stays green.

## Phase 5 - Local gates

Frontend: full `npm test` + `npm run build` (tsc + bundler). Backend touched:
`uv run --extra dev ruff check src` + full pytest. All green before review.
Fresh worktrees need `npm ci` first. Record counts in the runbook.

If your change altered anything a machine-checked docs/fact artifact describes (endpoints,
migration/schema head, scheduled jobs, page-access columns, etc.), regenerate that artifact
before running the full suite - a stale one fails a drift test unrelated to your change and
reads as a surprise red instead of an expected step.

## Phase 6 - Adversarial review (scale to the diff)

Run a multi-agent Workflow review over the committed diff: dimension finders
(correctness / framework behavior / design-system+a11y / test adequacy) then
2-3 independent skeptics per finding, majority-refute kills it. Scale the panel
to the change - a one-file tweak gets 2 dimensions, a cross-cutting change gets
4. Adopt confirmed DEFECTS (correctness, security, breakage, missing tests);
adopt cheap test-hardening nits even when refuted if they cost minutes. An
ENHANCEMENT a reviewer raises (a new feature, a larger refactor, a speculative
abstraction, hardening the ask did not call for) is logged in the runbook
Follow-ups, NOT built - and if it would add new surface area beyond the ask,
surfaced to the user as a scope decision, never folded into a "fix". The diff
should stay the smallest correct change; a review is not a licence to grow it.
Test-only follow-up commits do not require rebuilding an already-built image
(tests do not ship in the artifact) - record both shas.

**Review agents mutate the tree they run in.** Test-adequacy refuters
answer "would this test still pass if the guard were deleted?" by actually deleting
it, and they do not always revert; a Stop-hook auto-commit (if your setup has one) will
happily sweep their probes (and any `tests/test_probe_*_tmp.py`) into a `wip` commit
mid-review. Run the panel with `isolation: "worktree"` on each `agent()` call, or, if it
must run in the session worktree, checkpoint-commit BEFORE launching it and, after it
completes, require `git diff <checkpoint> --stat -- src tests` to list only your
intended files before any gate, commit, or wip-squash (revert strays with
`git checkout <checkpoint> -- <file>`).
**A fresh `isolation: "worktree"` branches from `origin/<default-branch>` by default** - it does NOT
contain your feature branch's committed changes, so an agent given that isolation would silently
review main instead of your diff. For the normal dev-quick-build case (reviewing a feature branch's
actual diff), checkpoint-commit-then-review-in-the-session-worktree is the DEFAULT path, not a
fallback; reserve `isolation: "worktree"` for a probe that must branch off the feature HEAD itself.
Never run Phase 5/7 gates while a panel is still running.

## Phase 7 - Deploy (gates decide, not optimism)

**Autonomous on green - do NOT pause for a human go-ahead.** When every gate in
this skill passes (full test suite green, local build green, adversarial review
clean or all confirmed findings fixed, and every `deploy-safely` gate green),
proceed straight to deploy and merge to production. Do not stop to ask the user for
approval. The gates ARE the pass/fail criteria this autonomy runs on, so any
"autonomous pipeline needs measurable pass/fail criteria" requirement is satisfied by
running them, not by a human sign-off. This is a deliberate, standing override
of a "confirm before deploy" default, scoped to the dev-quick-build flow only. (Some
projects deploy prod on merge via CI - there "deploy to production" = merge the
branch to `main` and the pipeline ships prod on that merge.)

Invoke the project's `deploy-safely` skill and run EVERY gate it names - origin
safety, main sync (behind=0), local-main publication, wip-free range. Then the
project's deploy recipe. For a container target (e.g. Cloud Run):

- Build-then-deploy-by-digest (build a tagged image `<repo>:<slug>-<sha>`,
  resolve the digest, deploy the image by `<repo>@<digest>` with no traffic and
  `git-branch` / `git-sha` labels). Never deploy from source for prod.
- Pre-flip verify on a revision tag URL: fetch the served bundle and grep for
  marker strings that ONLY the new build contains. Zero markers = wrong image.
- **Flip traffic to 100% - this is the step that makes it live, and it is not
  optional.** Until you flip, the new revision sits at 0% traffic (deployed dark) and
  the live URL still serves old code. Then the Served-Image Integrity gate: compare
  the built digest to the image of the **percent=100 traffic entry** - the traffic
  list's first entry may be a 0% tag entry, which reads as a false MISMATCH.
- Smoke the **live production URL**, not the revision tag URL: prod URL 200 serving
  the new bundle + markers, backend /health canary, revision log review (zero
  warnings). A green check on the tag URL while the live URL still serves old code is
  the false pass behind a "deployed dark" outcome.
- Record in the project's deploy log (same entry style as prior records): revision,
  sha, digest, markers, rollback pointer (`update-traffic <prev-rev>=100`),
  suite counts, review result, persona-pass status. Update the runbook Deploy
  section to point at it.
- Push the branch, then publish production parity: `git push origin HEAD:main`.
  If it rejects (origin/main moved), see Deploy contention below.
- **Enable the feature as part of THIS deploy - never leave it dark.** If the change
  sits behind a flag / kill-switch, ship it ON (default on, or set the env on in this
  same deploy) so production actually runs the new behaviour. A flag defaulted off, or
  an env flip "owed" to someone later, is NOT a finished quick build (see "Ship it LIVE,
  not dark" above). The flag is the rollback lever, not the reason the feature never
  goes live. The only exceptions - the user asked for a staged / dark rollout, or a gate
  blocks enabling it live - are surfaced and recorded, never assumed.

Green means go, autonomously. Stop and surface to the user ONLY in these cases -
they are the whole exception list, and none of them is "wait for approval on a
clean build":

- **A mandatory gate fails or cannot run** this session: red tests, a failed
  build, an ancestor/Served-Image-Integrity mismatch, a confirmed correctness or
  security finding you cannot cleanly fix, or no way to run a required gate.
  Then do NOT deploy - stage everything, record why in the runbook, and hand off.
- **The scope gate trips mid-build**: scouting reveals a migration, an authz/
  tier-gate change, or a multi-subsystem blast radius. Stop and route to
  `dev-writing-plans` / `dev-brainstorming` - a quick build must not silently become a
  train.
- **A genuine product, design, or trust decision surfaces** (e.g. a reviewer
  flags a trust-model choice). Escalate it rather than deciding unilaterally -
  that is a decision, not a gate.
- **A fix or finding would add new surface area beyond the ask** - a new feature,
  endpoint, flag, config setting, dependency, or abstraction. Surface it as a scope
  decision; do not fold new scope into a "fix". (The good pattern: a reviewer's
  larger suggestion is named as separate scope and routed to the user, not
  self-adopted mid-build.)

Browser verification (Phase 8) still runs, but its absence does not block the
deploy: if no browser is available this session, deploy on green and record the
persona pass as OWED (the standing convention), same as before.

## Phase 8 - Verify (invoke dev-qa-verify)

Deploy is not "done". Hand off to **`dev-qa-verify`** - the verification-before-completion
gate. It runs the interactive browser/persona pass (Claude in Chrome, the preferred tool:
interact, do not just look - click every new control, check counts/orders against what the
data implies, screenshot the evidence) against the **live production URL** (Phase 7 already
deployed and merged), and triages any defect by severity:

- **Build bug** (rendered break, wrong count/order, a dead control) -> loops back
  through Phase 4 (failing test -> fix -> Phase 5 gates -> Phase 6 review ->
  Phase 7 redeploy), **bounded to 2 cycles**. If it survives 2 cycles, roll back
  to the previous good revision (`update-traffic <prev-rev>=100`, the rollback
  pointer in the deploy record) and surface it. Production already serves the
  build, so a browser-caught defect is a redeploy now, not a note for later.
- **Plan-level** miss -> routes to `dev-writing-plans`; **wrong-concept** ->
  `dev-brainstorming`.

`dev-qa-verify` owns the SSO/credentials rule (never type credentials; hand the
account-pick to the user) and the OWED convention: if no browser is available
this session it records the pass as OWED and does not block - the deploy on green
(Phase 7) already happened. The quick build is done only when this gate is green
or explicitly recorded OWED. Update the deploy log's persona-pass line from OWED
to DONE with what was verified.

## Deploy contention - two dev-quick-build runs racing the same project

The clobber risk is *tree omission*: flipping to an image whose git tree does not
contain what production already serves. The **ancestor gate** (Phase 7, part of the
build-then-deploy integrity checks - marker verify + Served-Image Integrity + ancestor)
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
- Known contention up front → prefer a deploy train (one session ships both branches).
  Check whether another session is already deploying the project before Phase 7.
- WordPress files have no revisions: deploy-safely's pull-live-and-diff gate is the
  equivalent invariant - live is the baseline, always.

## Wrap

**Output style.** Write the final summary in the reader's active output style. If none is set, default to: lead with the answer, short sentences, plain words, no idiom.

Final summary leads with what shipped and where, the verified evidence, the
rollback pointer, and anything owed. Close out via `session-wrap` (squashing your
wip commits into one clean commit, e.g. `git reset --soft <base> && git commit`) as
usual; the worktree merge to main already happened as part of Phase 7.
