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
  swarm's quick mode (all four models, Codex at `xhigh`, each leg capped at 570 s), one round,
  for every quick build, including one that touches authz, a migration,
  secrets, or a write or delete of production or customer data (money movement included).
  Every model gets the runbook's "Ask (verbatim)" as THE ASK. Ask four questions: is the
  chosen semantic correct against the data model; is any data-source assumption still
  unverified; is the scope still inside the quick-build gate; and what in this plan is beyond
  the ask or would block the user's normal path (`simplify`). Why: a full four-model panel at
  `xhigh` can take 6-14 minutes a pass, and plan reviews that run to 15-50 minutes in total
  defeat the point of a fast path. Keep Codex at `xhigh` (do not drop it to `high` to save
  time); quick mode's per-leg cap keeps the whole panel to about 10 minutes.
- **One pass for a small change.** When the change is text only or small (about
  100 lines or fewer) and touches no authz, migration, secrets, or production or customer
  data write, you may run ONE combined review after Phase 5 instead of this plan review
  plus the Phase 6 panel: commit a checkpoint, then run `review-with-codex`'s
  `snapshot-review.sh` on it with `--effort high --timeout 600` (a plain copy plus a
  merge-base diff; see that skill). Give it the runbook's "Ask (verbatim)", the four questions above, and the
  Phase 6 test-adequacy question. Record "one pass" and the reason in the runbook Build log;
  Phase 6 is then done. The rule is one review pass sized to the risk.
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
  migration, an authz/tier-gate change, or a multi-subsystem blast radius, the
  scope gate has tripped - STOP and route to `dev-writing-plans` / `dev-brainstorming`
  (the Phase 7 stop-list applies here too). If a genuine product / design / trust
  decision surfaces, escalate to the user rather than settling it inside the plan.
- **Naming check (immutable names only; escalate only on a miss).** Phase 2
  surfaced where the code lives and what precedents exist. Before writing code,
  check every NEW name this build introduces that cannot be renamed in place, where
  a rename means delete-and-recreate or a data migration: a deployed service,
  service account, storage bucket, secret, data-warehouse dataset and table, database,
  table and column names, etc. Check infra names against your project's naming
  conventions and schema names against its existing patterns. Mutable names (files,
  modules, the branch, functions, UI components, routes) never pause the build: follow
  the project's existing patterns and go on. An immutable name that conforms proceeds
  silently - this stays the no-pause fast path. But a name that does NOT conform, or
  has no precedent to follow, is a genuine design decision: STOP and escalate it to the
  user for a naming call before Phase 4 (the same escalation this phase already makes
  for a design/trust decision). Ask in chat: show each candidate name as exact text in
  a code span and take the reply in chat. Do NOT put a name choice in a multiple-choice
  question pop-up: its short option labels make the agent shorten or rewrite names, so
  the exact spelling is lost. Record the chosen names in the runbook Decisions section.
- **Cloud location check (same rule: escalate only on a miss).** For every NEW cloud
  resource with a region or location (a deployed service, database instance, data-warehouse
  dataset, storage bucket, registry repository), write its location in the runbook beside
  its name and check it against your project's location rules (in short: co-locate with the
  resources it talks to, measured live with your cloud CLI; a regional service never takes a
  multi-region location). A conforming location proceeds silently. Any other location is a
  design decision: STOP and escalate it in chat with its reason, before Phase 4.
  A location cannot change after create. Pass it explicitly (`--region` /
  `--location`) on every create command; never let a tool's default decide.
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
cheaper-model subagent (Agent tool) with the exact commands, the repo path and any tool path it
needs. It returns a pass/fail digest with each failing test and its error, so the full output
stays out of this context. Run a gate inline only to re-run one failing test while you fix it, or
when the command needs interaction. Long build sessions that run many full test suites inline can
reach very large contexts on the top model.

On Node 25 or later, run vitest with jsdom as `NODE_OPTIONS=--no-experimental-webstorage npm test`.
Node's own `localStorage` global hides jsdom's, so every test that touches storage fails with
"Cannot read properties of undefined (reading 'getItem')". A flag on `node` alone does not reach
the vitest workers. Check `node --version` and the CI Node version before you treat a mass storage
failure as your change.

On a shared machine under load (check `uptime`), a full test run can time out tests in areas your
diff never touched. Before you debug them, run a control: run the failing files alone, then run the
same full suite on an unmodified copy of `origin/<default-branch>` on the same machine
(`git archive origin/<default-branch> | tar -x -C <empty tmp dir>`, reusing the installed
dependencies read-only, for example a symlinked `node_modules`). If the default branch times out the
same way, record both results in the runbook and let CI's runner decide. Never raise per-test
timeouts to make a loaded local run pass.

If your change altered anything a machine-checked docs/fact artifact describes (endpoints,
migration/schema head, scheduled jobs, page-access columns, etc.), regenerate that artifact
before running the full suite - a stale one fails a drift test unrelated to your change and
reads as a surprise red instead of an expected step.

**Old values after a rule change.** When the change removes or flips a rule or default (a payment term,
a switch's default), grep the whole repo for the old value before the first review: `docs/`,
`docs/plans/` runbooks, skill text, script `--help` text and test names. Fix each hit or add a
supersede note, and list the hits in the runbook. (Otherwise an adversarial pass keeps finding the
stale text, a different file each round.)

**Mutation testing runs on a copy.** If you run a mutation pass, run it on a plain copy of the
checkpoint with its own virtualenv, never in the build worktree. An in-place pass rewrites source
files, so it cannot overlap the full suite or a review, and a review that reads mutated source reports
false findings.

## Phase 6 - Adversarial review (scale to the diff)

Skip this phase when Phase 3's "One pass for a small change" option was used: that single
combined review already covered the committed diff.

Run ONE pass of a small multi-agent review over the committed diff (capped
for speed). Two finder agents, in parallel: **correctness** (framework behaviour, and the
design system plus a11y when the diff changes UI) and **test adequacy**. Give both the full
`review-swarm` shared prompt: the runbook's "Ask (verbatim)" as THE ASK, its Non-goals or
Follow-ups as NON-GOALS, the finding fields, the must-fix rule, and the `simplify` type. Send only critical or high findings to ONE skeptic agent each; a
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
**A fresh `isolation: "worktree"` branches from `origin/<default-branch>` by default** - it does NOT
contain your feature branch's committed changes, so an agent given that isolation would silently
review main instead of your diff. So the DEFAULT is: checkpoint-commit, then run each agent in its
own detached snapshot of that commit (`git worktree add --detach .claude/worktrees/review-<slug>-<agent>
<checkpoint>`), with its FIRST action `EnterWorktree(path=<its snapshot>)`, never in the build
worktree. A subagent starts in your working directory, and a prose "read-only" does not stop an
agent that has a shell: read-only agents have been seen to check out another branch in the
build worktree, or to commit, push and open a PR (see
`review-swarm` on giving each leg a snapshot). The same rule covers every investigation agent this skill dispatches (recon, an
impact map, a live-state read): a snapshot or a tool list with no Bash, Edit or Write, never the
build worktree. After ANY panel or investigation agent returns, run the `review-swarm`
**post-panel check** (branch, reflog and status here; each snapshot's reflog; a remote-branch
diff against the pre-panel baseline; `gh pr list --author @me --state all` and a cross-repo
`gh search prs --author @me`). An unexpected commit, push or PR is
out-of-process work: review it before you keep it, and never merge it on the agent's word.
Never run Phase 5/7 gates while a panel is still running.

**When a workflow-orchestration tool is not available.** Such a tool may run only after the
user opts in to multi-agent orchestration, so a quick build often cannot call it. Do not skip
Phase 6. Run the same panel with the Agent tool instead:

1. Checkpoint-commit the diff first.
2. Launch one background Agent per dimension, in the same message, so they run in parallel.
3. Bind each agent to its own snapshot from above (first action: `EnterWorktree(path=<snapshot>)`),
   never the build worktree. Tell it it must not commit, push, open a PR, or touch a production
   system. To probe behaviour, it copies the repo first (`cp -R <repo> "$(mktemp -d)/copy"`) and
   mutates only the copy. A mutation it
   leaves behind in the copy cannot reach your branch or an auto-commit. It also runs every
   probe with `HOME` set to a sandbox dir, and it never sources or line-extracts an installer or
   config script (for example a hook installer) outside that script's own test harness. A copied
   line range from a file that has since shifted can hold the real side-effect code, which then
   writes the live user config (for example, hook config merged into a live settings file). While a panel runs, a cheap
   guard is a background watcher on the live config file's hash.
4. Give the test-adequacy agent a mutation brief: delete or invert each guard in the copy. For
   every guard whose removal no test catches, report whether THE ASK needs that guard: if yes, it
   is a missing test (a defect); if no, it is a `simplify` finding to delete the guard, not a test
   to add. Also have it force one suite to fail, and
   check that the test runner exits non-zero and names that suite. **Run the unmutated control
   first, and count no kill unless it passes:** a harness that fails for its own reason kills every
   mutation. Changing `HOME` for the run hides the user's site-packages, so keep them on
   `PYTHONPATH` (`python3 -c "import site; print(site.getusersitepackages())"`). For example,
   a mutation re-run can print every mutation KILLED while its control failed with "No module named
   pytest"; only the control proves the result.
   **When the change deletes or writes data** (branches, records, files, money), the mutation
   result must come from an EXECUTED run, never from reading the code. A Codex leg in its
   read-only sandbox cannot create the copies, so its table comes back all `BLOCKED`; that is
   no result. Run the mutation script yourself, or give Codex `--sandbox workspace-write` with
   `-C` set to a scratch copy only, and run any long harness outside Codex's 600 s cap. Then
   spot-check the two most important gates yourself: remove each in a copy and confirm a test
   fails. A static pass that reads as all
   `BLOCKED` can hide safety checks that no test covers; only the executed run shows them.
   Two traps when reviewing an ops run-wrapper script:
   - **Prove a new test against the previous commit's code.** Copy the old file into scratch
     (`git show <prev>:<path> > <scratch>/<path>`), run the new tests with `PYTHONPATH=<scratch>`, and
     expect red. A control made by deleting text from the script is invalid when it removes a string
     the test searches for: the test then fails for the wrong reason.
   - **A refusal test must check the guard's OWN message** and that the child never ran (a marker
     file), not only the exit code. When a later check refuses the same case, deleting the guard
     still gives a refusal, so an exit-code-only test stays green (a fake green). Pin the message, or record the redundancy as intentional.
5. Treat an evidenced mutation result as self-verifying (it already shows a test that stays
   green). Send a critical or high finding without that evidence to ONE skeptic agent before you
   adopt it; a medium or lower finding gets no skeptic and follows the must-fix rule.
6. After the agents return, run the post-panel check above, then remove the snapshots
   (`git worktree remove --force <snapshot>`).

If the agents cannot bind to their snapshots (their shells lock after `EnterWorktree`; see
`review-swarm`, "If a leg cannot bind to its snapshot"), do not retry the bind. Launch the Phase 6
agents WITHOUT `EnterWorktree`, under hard rules in the prompt: read-only on the build worktree, all
probes and mutations only in `/tmp` copies, never commit, push, open a PR, or touch production.
Checkpoint-commit first and record the remote-ref baseline, then run the post-panel check when they
return. Give each agent its OWN plain copy of the checkpoint (`git archive <checkpoint> | tar -x -C
/tmp/<run>/<agent>`, not a git worktree), and have it run commands through a `/tmp` script that
`cd`s into that copy. After the panel, `git diff <checkpoint> --stat -- src tests` on the build
tree must be empty.
Give each copy its OWN virtualenv too (`uv venv` + `uv sync`, or a full copy of `.venv`), never a
symlink to the build worktree's `.venv`. Running `uv run` in the copy re-syncs the editable install
and rewrites the SHARED `site-packages/_editable_impl_<package>.pth` to the copy's `src`. The build
tree's own interpreter then imports scratch code (gates, other agents, live read-only runs). After
the panel, check that the `.pth` still names the build worktree's `src` (a mutation
agent has caused this before; checksum the file to catch it).

**A script that changes live host state gets an executed harness leg.** When the diff
includes an ops script that edits crontabs, sudo-owned files, systemd units, or another user's home
on a live host, static review is not enough. The test-adequacy agent (not an extra agent) also RUNS
the script's real stages on a
disposable Linux host that simulates the target: the happy path, rollback, an abort midway then
rollback, a re-run after an interruption, every guard, and injected read failures. Simulate the
target for real (its users, cron, sudo, flock, file modes); stub only external services (the CLI
the script drives, your git host, cloud APIs, SaaS APIs). Choose the host in this order:
1. An ephemeral spot / preemptible cloud VM in a sandbox project of your own (for example on
   GCE: `--provisioning-model=SPOT`, `--max-run-duration=2h` and
   `--instance-termination-action=DELETE`), so it deletes itself even if the session dies.
   Delete it when the panel ends and confirm it is gone.
2. A CI runner (a manually triggered workflow in a scratch repo).
3. Local Docker, only when the operator agrees.

Never the operator's laptop by default, and never the production host. Execution finds what
reading cannot (a rollback-then-retry deadlock, a non-atomic backup, a gate that passes on a
failed read), so re-run the harness after each fix.

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

## Deploy contention - two dev-quick-build runs racing the same project

The clobber risk is *tree omission*: flipping to an image whose git tree does not
contain what production already serves. The **ancestor gate** (Phase 7, part of the
build-then-deploy integrity checks - marker verify + Served-Image Integrity + ancestor; see the
"integrity trio" in [build-and-ship-playbook.md](../../docs/build-and-ship-playbook.md))
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
