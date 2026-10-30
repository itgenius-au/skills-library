---
name: dev-quick-build
description: Build and ship ONE small, well-scoped feature end to end in a single session - worktree isolation, dated runbook doc kept updated throughout, a quick review-swarm plan review before any code (four models, about 10 minutes), TDD, full local gates, adversarial multi-agent review, dev-deploy-safely production gates, deploy-by-digest, and live browser verification via Claude in Chrome that loops back to fix, re-review and redeploy if it catches a break. Use whenever the user hands over a single concrete feature or UI tweak and wants it built AND shipped ("add a chip for X", "make this table sortable", "rename this and change what it counts", "build and deploy if the gates pass"). Triggers on - quick build, quickbuild, build and ship, ship this small change, small feature end to end, build this and deploy.
---

# Quick Build

Ship one small feature idea from request to verified production, in one session,
using a rigorous building/testing/deploy method. The whole point is *end to end*:
a quick build is not done when the code is written, or even when the deploy is
green - it is done when the change has been watched working in a real browser on
the production URL and the deploy record says so.

> **This skill is the small-scope FAST PATH.** The shared build/ship gates it runs
> (TDD, local gates, adversarial review, dev-deploy-safely, build-by-digest + integrity +
> ancestor gate, browser verification, record + merge) are the non-negotiables of a
> rigorous build method - the same gates apply on the plan-driven path (migration /
> authz / multi-phase, which the scope gate below routes out of dev-quick-build and into
> `dev-writing-plans` / `dev-brainstorming` / `dev-auto-build`). This skill owns the
> fast-path mechanics; the written playbook
> ([build-and-ship-playbook.md](../../docs/build-and-ship-playbook.md)) owns the principles
> and is canonical where the two overlap. Read it if you want the why or you are on the
> plan-driven path. Wire this skill to your project's own build/deploy playbook where one
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
> a cost-saving build misses its code budget or pass mark, or a genuine
> product/design/trust decision surfaces. "Wait for approval on a passing build" is
> never one of them. If you catch yourself asking the user to okay a green deploy,
> re-read this line and proceed instead.

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

## Reference files (read the file when its row applies)

This file holds the scope gate, the eight phases, the deploy stop list (Phase 7) and the rules that apply on every build. Edge cases, worked examples and rare branches live in `references/` beside it. Open a file when its row applies, and open it BEFORE the step it names: a row is an instruction, not a link to skim. Text past the first screens of this file is not kept after a compaction: after one, re-read Phase 6, the Phase 7 stop list and Phase 8 in this file before you deploy.

| When | Read now |
|---|---|
| The ask exists to cut cost (money, tokens or spend) | `references/cost-saving-build.md`, before Phase 3 |
| Phase 3: the change is text only or small and you want ONE combined review instead of the plan review plus the Phase 6 panel | `references/phase-3-one-pass-review.md`, before you choose it |
| Phase 3: the build introduces a NEW name that cannot be renamed in place, or a NEW cloud resource with a location | `references/phase-3-names-and-locations.md`, before Phase 4 |
| Phase 5, before the full suite: the change altered what a generated docs or fact artifact describes, or a rule or default changed; or a gate fails or times out for a reason outside your diff, or you run a mutation pass | `references/phase-5-gate-notes.md` |
| Phase 6: you launch any review or investigation agent (with the Agent tool in the usual case) | `references/phase-6-agent-panel.md`, before you launch any agent |
| Phase 6: the diff includes an ops script that changes live host state | `references/phase-6-live-host-harness.md` |
| Phase 7, before the deploy when another build may be shipping the same project, or when two builds race one project or a push to main is rejected | `references/deploy-contention.md` |
| You need the model or effort a role runs at (gate runs, plan review, one-pass review, panel agents) | `references/models.md` |

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

**A cost-saving build states its payoff and a code budget.** This applies only when the ask exists to cut cost (money, tokens or spend); every other build skips it. For such a build, read `references/cost-saving-build.md` now, before Phase 3: it sets the three runbook lines, the code budget, and the two stops that the Phase 7 stop list names.

**Refuse by default only where it is earned.** In the thing you build (not the deploy and CI
gates, which still abort), a refusal, a typed confirmation token, or a "stop until a named person
confirms" step belongs only on an action that is irreversible and destructive, or that moves money
with no human in the loop. Everywhere else: warn, log, and continue. A human-in-the-loop skill trusts
the human - the user's "go" approves the action, including a money action or a customer send; do
not add a second confirmation word. An UNKNOWN answer is a warning to show, not a reason to refuse.
Fail-closed defaults built into ops tools block normal work and have to be loosened later.

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
- Read the repo's WHOLE agent-instructions file (`CLAUDE.md` / `AGENTS.md`), never `head` or a
  partial read, plus any such file in the folders this change touches (and their parents). Copy every
  rule that constrains this kind of change (feature flags, staging-first QA, release steps, version
  bumps, review rules) into the runbook Decisions as one "Repo rules that apply" line, and plan the
  build around them. A rule near the bottom of the file ("new panel features ship behind a preview
  flag") is exactly the one a partial read misses, and a review bot can then block the merge after CI
  is green, which costs a rebuild and a second release.
- Verify data-source assumptions in the backend code, not from memory (e.g.
  "does this endpoint return suspended users?" - grep the integration).

## Phase 3 - Quick review of the plan (before any code)

The runbook is now a real plan, not a skeleton: Phase 2 filled the Decisions and
Scout findings sections. Review THAT plan BEFORE writing a line of code. A wrong
semantic or an unverified data-source assumption caught here costs a paragraph edit;
the same miss caught in the Phase 6 diff review costs a rebuild.

- **Size the review for a quick build.** Run the **`review-swarm`** skill's "Quick-build
  review" in `plan` mode on the runbook (`docs/plans/YYYY-MM-DD-<slug>-quick-build.md`): the
  swarm's quick mode (all four models, the Codex leg at its top review effort, each leg capped at
  570 s; see `references/models.md`), one round, for every quick build, including one that
  touches authz, a migration, secrets, or a write or delete of production or customer data
  (money movement included). Every model gets the runbook's "Ask (verbatim)" as THE ASK. Ask four
  questions: is the chosen semantic correct against the data model; is any data-source assumption
  still unverified; is the scope still inside the quick-build gate; and what in this plan is beyond
  the ask or would block the user's normal path (`simplify`). Why: a full four-model panel at top
  effort can take 6-14 minutes a pass, and plan reviews that run to 15-50 minutes in total
  defeat the point of a fast path. Do not lower the Codex effort to save time; quick mode's
  per-leg cap keeps the whole panel to about 10 minutes.
- **One pass for a small change.** A text-only or small change (about 100 lines or fewer) that touches no authz, migration, secrets, or production or customer data write may run ONE combined review after Phase 5 instead of this plan review plus the Phase 6 panel. Read `references/phase-3-one-pass-review.md` now, before you choose it: it holds the command, the questions to give it, and the case where one pass is NOT allowed (code that hides or checks sensitive data).
- **Time budget.** Each model gets 10 minutes. A model that has not returned is
  `unavailable`: no retry, proceed without it. Record each review's wall-clock time in
  the runbook Build log; the target is 15 minutes or less of review for the whole build.
- Cycle findings back INTO the plan, not into a debate. Adopt only MUST-FIX defects
  (the `review-swarm` must-fix rule: critical/high, or medium flagged by 2+ legs), apply
  `simplify` items that remove something outside the ask, and update
  the Decisions / Scout findings sections. List advisory items in one line in Follow-ups.
  Do NOT re-run the review unless a fix changed the approach; then re-run the same
  review once. A reviewer ENHANCEMENT (a nice-to-have feature,
  a bigger refactor, a speculative abstraction, hardening beyond the ask) does NOT
  go into the plan - log it in the runbook Follow-ups. If an enhancement would add
  new surface area beyond the ask, surface it to the user as a scope decision;
  never self-adopt it. Record the review result (models run, what changed) in the
  runbook's Build log section.
- This is a gate, not a formality. If a reviewer surfaces that the ask needs a
  migration, an authz/tier-gate change, or a multi-subsystem reach, the
  scope gate has tripped - STOP and route to `dev-writing-plans` / `dev-brainstorming`
  (the Phase 7 stop-list applies here too). If a genuine product / design / trust
  decision surfaces, escalate to the user rather than settling it inside the plan.
- **Naming and cloud location checks (immutable names only; escalate only on a miss).** When this build introduces a NEW name that cannot be renamed in place (a deployed service, service account, storage bucket, secret, data-warehouse dataset or table, database, table or column) or a NEW cloud resource with a region or location, read `references/phase-3-names-and-locations.md` now, before Phase 4. A name or location that does not conform is a STOP: escalate it in chat before Phase 4. A conforming one proceeds silently, with no pause.
- **Scope check before code.** Always write one line in the runbook Decisions: "Asked:
  X. Planned: Y." If the review made the plan bigger - a new flag, mode, guard, confirmation step, script, or dependency the
  ask did not name - STOP and show the user one line: "You asked for X. The plan now
  also adds Y." Build only what they approve. Any approval request names the size
  ("go = build <N> changes: ..."), so one word never approves hidden scope.
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

**Run the gates through a test-runner subagent.** Dispatch the full gate run to a
cheaper-model subagent (Agent tool; the model is in `references/models.md`) with the exact
commands, the repo path and any tool path it needs. It returns a pass/fail digest with each
failing test and its error, so the full output stays out of this context. Run a gate inline only to
re-run one failing test while you fix it, or when the command needs interaction. Long build sessions
that run many full test suites inline can reach very large contexts on the top model.
A full gate run that can take close to 10 minutes does not fit one foreground shell call (the usual
cap is 10 minutes). Tell the subagent to run its parts (for example each suite of a multi-suite
runner) in separate calls, so each returns its own digest. A gate run that timed out is not a pass:
run the parts that did not finish before review.

**Gate-run problems and old values.** Before the full suite, when the change altered what a generated docs or fact artifact describes (regenerate it first) or removes or flips a rule or default, and when a gate fails or times out for a reason outside your diff (Node 25 or later, a loaded shared machine), or before you run a mutation pass, read `references/phase-5-gate-notes.md` now, before you debug or review.

**Do not edit the tree while the gates run.** An edit made during a full gate run (or while a
background watcher reads the tree) gives a false red or a false green. Run the gates again on the
final head with no edits during the run, and record that run.

## Phase 6 - Adversarial review (scale to the diff)

Skip this phase when Phase 3's "One pass for a small change" option was used: that single
combined review already covered the committed diff.

Run ONE pass of a small multi-agent review over the committed diff (capped
for speed). Two finder agents, in parallel: **correctness** (framework behaviour, and the
design system plus a11y when the diff changes UI) and **test adequacy**. Give both the full
`review-swarm` shared prompt: the runbook's "Ask (verbatim)" as THE ASK, its Non-goals or
Follow-ups as NON-GOALS, the finding fields, the must-fix rule, and the `simplify` type.
Always add this question to the correctness brief: "Does this make an always-failing or dormant
call succeed, or act under a stored grant? Compare its actor guard with the sibling write
endpoints in the same module, and name any check the old failure was hiding."
When the ask makes a component load by name or from one source (a plugin called by name, a
launcher, one config source), also add: "Capture the real output it hands on in a test run (a
spawn prompt, a generated config, a command line). Does it still hold a filesystem path to code?"
A path that names the right version today still ties the trigger to one machine.
Send only critical or high findings to ONE skeptic agent each; a
refuted one is dropped. Each agent gets 10 minutes; one that has not returned is dropped,
with no retry. Adopt only MUST-FIX defects and `simplify` items outside the ask; list
the rest in one line in Follow-ups. No re-review round: verify each fix with the Phase 5
gates, and re-run one correctness agent on the fix diff only when a fix changed the
approach, or changed a guard that decides whether an action runs or a log is kept (a refusal
check, a fail-closed probe, file-open or permission logic). Such fixes break in new ways: a fix to a guard
often introduces the next round's blocker. The extra-rounds cap below still applies. **A fix to a guard or a failure
path needs a test that fails first.** Drive the failing input the finding names (a failed
command, a corrupt file, a bad argument), watch the test fail on the unfixed code, then fix it
and check that a mutation of the fix fails the test. A reviewer's "clean" on the fix diff, and
the mechanism a reviewer suggests, are hypotheses until that test passes. Example: a `set -e` fix inside an `if !` condition did nothing, a fix-diff review
called it clean, and a PR review bot found it after the merge. An ENHANCEMENT a reviewer raises (a new feature, a larger refactor, a speculative
abstraction, hardening the ask did not call for) is logged in the runbook
Follow-ups, NOT built - and if it would add new surface area beyond the ask,
surfaced to the user as a scope decision, never folded into a "fix". The diff
should stay the smallest correct change; a review is not a licence to grow it.

**Extra rounds are capped.** If you, or the brief that dispatched you, run more review rounds than this
one pass (for example repeated adversarial Codex passes on a money path), cap them at 3 and converge by
class: see `dev-auto-build` Phase 3, "Converge by class, not by finding".
Test-only follow-up commits do not require rebuilding an already-built image
(tests do not ship in the artifact) - record both shas.

**Review agents mutate the tree they run in.** Test-adequacy refuters
answer "would this test still pass if the guard were deleted?" by actually deleting
it, and they do not always revert; a Stop-hook auto-commit (if your setup has one) will happily sweep their
probes (and any `tests/test_probe_*_tmp.py`) into a `wip` commit mid-review. So
checkpoint-commit BEFORE launching the panel and, after it completes, require
`git diff <checkpoint> --stat -- src tests` to list only your intended files before any
gate, commit, or wip-squash (revert strays with `git checkout <checkpoint> -- <file>`).

**Running the panel.** Before you launch any review or investigation agent, read `references/phase-6-agent-panel.md` now. It holds the snapshot rule for each agent (a fresh `isolation: "worktree"` reviews main, not your diff), the post-panel check, the Agent-tool procedure for when a workflow-orchestration tool is not available (the usual case: it runs only after the user opts in, and Phase 6 is never skipped), the mutation brief and its traps, the fallback when agents cannot bind to their snapshots, and the own-virtualenv rule (the `.pth` rule) for each copy.

Never run Phase 5/7 gates while a panel is still running.

**An ops script that changes live host state** (it edits crontabs, sudo-owned files, systemd units, or another user's home on a live host): static review is not enough. Read `references/phase-6-live-host-harness.md` now.

## Phase 7 - Deploy (gates decide, not optimism)

**Autonomous on green - do NOT pause for a human go-ahead.** When every gate in
this skill passes (full test suite green, local build green, adversarial review
with no must-fix defect left, and every `dev-deploy-safely` gate green),
proceed straight to deploy and merge to production. Do not stop to ask the user for
approval. The gates ARE the pass/fail criteria this autonomy runs on, so any
"autonomous pipeline needs measurable pass/fail criteria" requirement is satisfied by
running them, not by a human sign-off. This is a deliberate, standing override
of a "confirm before deploy" default, scoped to the dev-quick-build flow only. (Some
projects deploy prod on merge via CI - there "deploy to production" = merge the
branch to `main` and the pipeline ships prod on that merge.)

Invoke the `dev-deploy-safely` skill (or the project's own deploy skill where one exists) and run EVERY gate it names - origin
safety, main sync (behind=0), local-main publication, wip-free range. Then the
project's deploy recipe. For a container target (e.g. Cloud Run):

- Build-then-deploy-by-digest (`gcloud builds submit --tag <repo>:<slug>-<sha>`,
  resolve the digest, deploy `--image <repo>@<digest> --no-traffic` with
  `--labels=git-branch=...,git-sha=...`). Never `--source` for prod.
- Pre-flip verify on a revision tag URL: fetch the served bundle and grep for
  marker strings that ONLY the new build contains. Zero markers = wrong image.
- **Flip traffic to 100% - this is the step that makes it live, and it is not
  optional.** `gcloud run services update-traffic <svc> --to-revisions=<new-rev>=100`.
  Until you flip, the new revision sits at 0% traffic (deployed dark) and the live
  URL still serves old code. Then the Served-Image Integrity gate: compare the built
  digest to the image of the **percent=100 traffic entry** - `status.traffic[0]` may
  be a 0% tag entry, which reads as a false MISMATCH.
- Smoke the **live production URL**, not the revision tag URL: prod URL 200 serving
  the new bundle + markers, backend /health canary, revision log review (zero
  warnings). A green check on the tag URL while the live URL still serves old code is
  the false pass behind a "deployed dark" outcome.
- Record in the project's deploy log (same entry style as prior records): revision,
  sha, digest, markers, rollback pointer (`update-traffic <prev-rev>=100`),
  suite counts, review result, persona-pass status. Update the runbook Deploy
  section to point at it. If the build shipped more than one commit (for example a
  loop-back fix after live QA), list the `git revert` steps newest first: reverting
  the older commit alone conflicts when the later one edits its files.
- Push the branch, then publish production parity: `git push origin HEAD:main`.
  If it rejects (origin/main moved), see Deploy contention below. Where production parity lands
  through a PR (a protected `main`), merge it with the `dev-deploy-safely` "PR merge gate":
  the `pr-checks-green.sh` script bundled with that skill (or its one-command wrapper
  `gate-merge.sh`) plus `--match-head-commit`, one auto-recovery pass, never
  `gh pr checks --watch`.
- **Enable the feature as part of THIS deploy - never leave it dark.** If the change
  sits behind a flag / kill-switch, ship it ON (default on, or set the env on in this
  same deploy) so production actually runs the new behaviour. A flag defaulted off, or
  an env flip "owed" to someone later, is NOT a finished quick build (see "Ship it LIVE,
  not dark" above). The flag is the rollback lever, not the reason the feature never
  goes live. The only exceptions - the user asked for a staged / dark rollout, or a gate
  blocks enabling it live - are surfaced and recorded, never assumed.

For a Cloud Functions gen2 function (a source-only deploy, no image digest), run the
`dev-deploy-safely` section "Cloud Functions gen2 (source-only deploys)" in place of the Cloud Run
recipe above.

Green means go, autonomously. Stop and surface to the user ONLY in these cases -
they are the whole exception list, and none of them is "wait for approval on a
clean build":

- **A mandatory gate fails or cannot run** this session: red tests, a failed
  build, an ancestor/Served-Image-Integrity mismatch, a confirmed correctness or
  security finding you cannot cleanly fix, or no way to run a required gate.
  Then do NOT deploy - stage everything, record why in the runbook, and hand off.
- **The scope gate trips mid-build**: scouting reveals a migration, an authz/
  tier-gate change, or a multi-subsystem reach. Stop and route to
  `dev-writing-plans` / `dev-brainstorming` - a quick build must not silently become a
  train.
- **A cost-saving build misses its code budget or its pass mark** (Scope gate, "A
  cost-saving build states its payoff and a code budget"). Do not start another
  round: park it and ask the user for a go and a new budget.
- **A genuine product, design, or trust decision surfaces** (e.g. a reviewer
  flags a trust-model choice). Escalate it rather than deciding unilaterally -
  that is a decision, not a gate.
- **A fix or finding would add new surface area beyond the ask** - a new feature,
  endpoint, flag, config setting, dependency, or abstraction. Surface it as a scope
  decision; do not fold new scope into a "fix". (The good pattern: a reviewer's
  larger suggestion is named as separate scope and routed to the user, not
  self-adopted mid-build.)

Browser verification (Phase 8) still runs, but its absence does not block the
deploy: deploy on green, then verify. A session without a local browser tool (a cloud
VM, a headless run) is not a reason to skip the pass: Phase 8 can always route it
to `dev-qa-verify`, which runs it on a remote or headless browser. Record the persona
pass as OWED only when no browser can run at all (the standing convention).

## Phase 8 - Verify (invoke dev-qa-verify)

Deploy is not "done". Hand off to **`dev-qa-verify`** - the verification-before-completion
gate. It runs the interactive browser/persona pass (Claude in Chrome, the preferred tool:
interact, do not just look - click every new control, check counts/orders against what the
data implies, screenshot the evidence) against the **live production URL** (Phase 7 already
deployed and merged), and triages any defect by severity:

- **Build bug** (rendered break, wrong count/order, a dead control) -> loops back
  through Phase 4 (failing test -> fix -> Phase 5 gates -> one Phase 6 correctness
  agent on the fix diff only -> Phase 7 redeploy), **bounded to 2 cycles**. If it survives 2 cycles, roll back
  to the previous good revision (`update-traffic <prev-rev>=100`, the rollback
  pointer in the deploy record) and surface it. Production already serves the
  build, so a browser-caught defect is a redeploy now, not a note for later.
- **Plan-level** miss -> routes to `dev-writing-plans`; **wrong-concept** ->
  `dev-brainstorming`.

`dev-qa-verify` owns the SSO/credentials rule (never type credentials; hand the
account-pick to the user) and the OWED convention. Without a local browser tool it
runs the pass on a remote or headless browser; only when no browser can run at all
does it record the pass as OWED, and it does not block - the deploy on green
(Phase 7) already happened. Do not write OWED yourself for "no browser": route the
pass to `dev-qa-verify` and let it decide. The quick build is done only when this
gate is green or explicitly recorded OWED. Update the deploy log's persona-pass line
from OWED to DONE with what was verified.

## Deploy contention - two quick builds racing the same project

Read `references/deploy-contention.md` now, before Phase 7, when another build may be shipping the same project, when two quick builds race one project, when `git push origin HEAD:main` rejects, when a PR merge is refused as `BLOCKED` with green CI, or when a loop-back fix follows a squash-merged PR. It holds the ancestor-gate rules, the fetch-before-flip serialization, and the no-force-push recovery.

## Wrap

**Output style.** Write the final summary in the reader's active output style. If none is set, default to: lead with the answer, short sentences, plain words, no idiom.

Final summary leads with what shipped and where, the verified evidence, the
rollback pointer, and anything owed. Close out via `session-wrap` (squashing your
wip commits into one clean commit, e.g. `git reset --soft <base> && git commit`) as
usual; the worktree merge to main already happened as part of Phase 7.

**Parking a build that stopped before it was safe.** Do not leave it as loose worktree edits. Commit
with a message that starts `WIP DO NOT RUN: <why, open defect count>`, set the runbook Status line to
`PAUSED <date>: <reason>; resume when <trigger>`, push the branch, and end with a three-line report
(branch, sha, state), so a later session does not run or merge it by mistake.
