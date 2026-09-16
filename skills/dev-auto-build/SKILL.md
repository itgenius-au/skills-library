---
name: dev-auto-build
description: "Autonomously execute a plan/runbook end to end using the house method: an AI build agent (e.g. Codex) builds per phase, Claude verifies independently, quad review (four independent models: Codex+Gemini+GLM+Fable) cycles findings back to the build agent until clean, then a final browser pass whose defects loop back through build + review. Stops at a PUSH-READY worktree by default (never pushes/merges/deploys); deploys to production on green only when that is authorised at kickoff. Use when the user hands over a plan and wants it built autonomously without babysitting. Triggers on: auto build, autobuild, run the plan, execute this plan autonomously, build this plan, build to push-ready, autonomous build."
---

# Auto-Build: Autonomous Plan-Driven Build Engine

Take a plan/runbook and drive it, unattended, using a rigorous, multi-model build method (an AI build agent runs the phases; `quad-review` reviews the diff). `dev-quick-build` is the small, human-present fast path that always ships to prod; `dev-auto-build` is the plan-driven, autonomous engine that stops at push-ready by default and deploys to prod only when authorised at kickoff.

> **The non-negotiable gates are the same on every path** and this skill enforces them: TDD, full local gates, the `quad-review` multi-model review, worktree isolation, and build-then-deploy-by-digest + Served-Image Integrity + ancestor gate for any deploy. This skill owns the autonomous mechanics; wire it to your own project's build/deploy playbook where one exists.

**The terminus depends on the kickoff deploy-authorisation choice (Phase 0).**

- **Not authorised (the default):** dev-auto-build STOPS at a **push-ready worktree** - branch committed, gates green, quad review clean (or a design decision escalated), browser pass done, PR drafted. It never pushes, merges, or deploys; the user owns that gate. This is the historical behaviour.
- **Authorised:** dev-auto-build runs the same build + review, then **deploys to production on green** through the `deploy-safely` gates (like `dev-quick-build`), verifies live in the browser, and merges to main. Authorisation is decided ONCE at kickoff (Phase 0) and is never inferred mid-run.

Either way the browser pass is the **final gate**, and a browser-caught defect loops back to the build agent and quad review before the run can end (Phase 5, via `dev-qa-verify`).

## Lanes (what dev-auto-build may do autonomously)

Classify the plan before running.

- **Green** (reversible, low-risk: dep bumps, lint/format, test backfill, doc fixes, self-contained features): run to push-ready autonomously.
- **Yellow** (feature builds, refactors): run to push-ready autonomously; the push-ready PR is the gate.
- **Red** (authz, schema migration, secrets, external comms, money movement, publishing): **STOP and escalate.** Never done autonomously, even if a task claims to be "reversible" (a refund is reversible but is a transfer; a sent notification cannot be recalled). If any plan task is red-lane and the invocation did not explicitly authorize it, stop in Phase 0 and report.
- **Deploying the built feature to production** is NOT auto-red here: it is gated by the Phase 0 deploy-authorisation choice. Authorised at kickoff -> the end-of-run deploy proceeds on green. Not authorised -> push-ready terminus, no deploy. Every OTHER red-lane task above stays red regardless of that choice.

## Invariants (hold throughout)

- **Deploy only if authorised at kickoff.** With authorisation, push / merge / deploy happen ONLY at the end, through `deploy-safely` gates, after the browser pass. Without it (the default), never push, merge, or deploy - all work stays on a feature branch in an isolated worktree.
- **Never** edit secrets/authz/migrations autonomously unless the plan + invocation explicitly authorize it (then use `xhigh` and flag for the user).
- **Never trust an agent's self-report.** After every build-agent run, Claude reads the diff, confirms scope, and re-runs the gates itself.
- **Simplest path; the plan is the fence.** Build the simplest change that satisfies the plan and passes the gates. The plan is the scope ceiling: implement what a task names and no more - no features, endpoints, flags, dependencies, or abstractions the plan did not call for, no ripple-fixing unrelated files, no "while I am here" cleanups, no hardening code the task did not touch. Something worth doing that the plan did not name is a Follow-up you log, not work you start. Unsupervised (this whole engine) means tighter scope, never looser.
- **Reviews find defects, not features.** A review-cycle DEFECT (correctness, security, breakage, missing test) is fixed and re-reviewed. A review ENHANCEMENT (a new feature, a bigger refactor, a speculative abstraction, hardening beyond the plan) is logged as a Follow-up, NOT built; if it would add new surface area beyond the plan, it is escalated to the user as a scope decision, never folded into a "fix".
- **Every loop is bounded** with a checkable stop condition and a cost cap that aborts.
- **Cost / model dispatch:** use a fast/cheap model (e.g. Claude Sonnet) for orchestration and gate-running; dispatch your build agent (e.g. Codex CLI) at **`high`** reasoning effort for builds (`xhigh` only for security/authz/migration/architectural tasks). The `quad-review` skill handles its own reviewer dispatch. Set per-run and total token ceilings (default ~200k per plan; abort on breach).

## Phase 0: Intake and guardrail classification

1. Read the plan file completely. Confirm today's date from the environment (never infer it).
2. Classify each task green / yellow / red-lane. **Any unauthorized red-lane task -> STOP, report, do not proceed.**
3. **Decide prod-deploy authorisation - once, now.** Set `deploy_authorised`:
   - **yes** only if the invocation explicitly authorises deploying to production ("build and deploy", "ship it on green", "deploy to prod").
   - If the invocation is silent or ambiguous, **ASK the user once**: "Deploy to production on green, or stop at push-ready?"
   - **Default no.** An unanswered or ambiguous choice = NOT authorised = push-ready terminus (the historical behaviour).
   Record the decision in the runbook. A `yes` is the standing approval that lets the end-of-run deploy proceed autonomously on green; it does NOT authorise any other red-lane task (authz / migration / secrets / comms stay red).
4. Ensure an isolated worktree (`EnterWorktree`, or verify you are already in one that matches the target repo). Verify `git rev-parse --show-toplevel` is the worktree path before any edit.
5. Create the runbook doc `docs/plans/YYYY-MM-DD-<slug>-auto-build.md` with a `**Date:**` header and sections: Ask, Decisions, Deploy authorisation, Build log, Review, Deploy. Update it at every phase transition (a one-line append is enough), not retrospectively.

## Phase 1: Per-phase build (build loop)

For each phase/task in the plan, in dependency order (disjoint-file phases may run in parallel; overlapping phases stay sequential):

1. **Scope the build-agent run.** Write a focused prompt: "Implement Task N, touch nothing else, and implement the MINIMUM that makes the tests pass - no features, abstractions, or hardening the task did not name. TDD: write failing tests first, confirm they fail for the right reason, then implement to green." Include the empirical grounding note (verify against the live code, do not trust doc claims).
2. **Invoke your build agent** (e.g. the Codex CLI in a headless/exec mode), build tier not review:
   ```bash
   codex exec --dir "$REPO" -- "$PROMPT"
   # high reasoning effort for normal tasks; raise it ONLY for security/authz/migration/architectural tasks
   ```
   Handle a wedge: a timeout / stuck-agent signal means relaunch attached, do not passively wait.
3. **Verify independently (never trust self-report):**
   - Read the diff yourself (`git diff`); confirm it touched only in-scope files.
   - Run the repo's gates yourself (lint, typecheck, build, tests). Record the counts in the runbook.
   - **Exercise any write path the default test run does not.** A tool with a dry-run/apply split, or a write path behind an `if apply:` / `if commit:` guard, can ship broken while gates + dry-run are all green: the dry-run may skip that branch entirely, and if the tests also mock the writer, nothing ever runs the real write path against the real payload. For any such path, add a test that runs the REAL writer against the REAL payload shape, and, where a live target exists and the write is reversible, run a single **canary apply (one row) with post-verify** before trusting the batch. A clean dry-run is not proof the apply path runs.
4. **Gates red -> bounded fix-run.** Send the build agent a scoped fix prompt; re-verify. Stop after 2 attempts on a task and report the failure (do not thrash).

## Living plan file, checkpoints, and resume

The plan file is the source of truth for progress, updated in real time, not retrospectively:

- **Before starting, check the plan's Prerequisites.** If any prerequisite is unmet, STOP and report - never build on an unsatisfied prerequisite.
- **Each task's OWN declared verification runs, not just the whole-diff gate.** A task is complete only when the specific `Verification` steps written in its plan entry pass (the exact commands / curls / checks it names) AND the whole-diff gates (Phase 2) are green. Generic gates green is necessary, not sufficient.
- **Commit per task, atomically.** Stage only that task's files; message `{task title} (plan task N)`. Then mark it complete in the plan file: `### Task N: Title ✅` with a `**Completed:** <date>` line, committed alongside the work.
- **At a plan checkpoint task**, run the checkpoint's integration-level verifications and record the result in the runbook before continuing. Autonomous green/yellow lanes do not pause for a human at a checkpoint; a red-lane task or an escalation still stops (see Lanes + Failure). (Per-task fix attempts are bounded at 2, this skill's standing cap.)
- **If the plan changes mid-run** (a task added, reordered, or scope shifts), update the plan file FIRST, then continue - never diverge from it silently.
- **At Terminus, run the plan's Definition of Done checks** before declaring the run complete - the plan's DoD is the final gate, over and above the per-task verifications.
- **Resume:** on restart, read the plan + runbook, find the last `✅` task, verify its output is still valid (code may have moved under it), then continue from the next incomplete task. This is what makes a killed run recoverable.

## Phase 2: Whole-diff local gates

After all phases, run the repo's full gate set (lint, typecheck, build, tests) over the full feature state. Must be all-green before review. Record counts in the runbook.

## Phase 3: Quad-review cycle (review loop)

1. Compute the **isolated feature diff** from the merge-base (`git merge-base origin/main HEAD`), not raw `origin/main`, so unrelated in-flight work does not pollute the review.
2. Run the review panel via the **`quad-review`** skill in `build` mode over the **isolated feature diff** (`<merge-base>...HEAD`). It runs four independent models in parallel and returns one synthesized, consensus-tagged findings table.
   **Scale to the diff:** a trivial diff (a lint/format autofix) gets a light single-model pass; a substantive diff gets the full panel. A reviewer reported unavailable (a wedge, or a leg out of quota) does not block the others; note it.
   **Split a large diff into focused per-subsystem passes.** A single monolithic review of a big diff has false coverage: focused per-area passes (and a repo host's own PR bot) routinely catch real findings a one-shot review misses. Above ~60KB, run `quad-review` per subsystem (e.g. resolver, webhooks, entitlements, migration/scripts, UI) with its own file set, then reconcile - do not trust one review of the whole thing.
   **A truncated leg is not a clean leg.** Some reviewer models silently truncate their input above a size threshold, so a "clean" verdict on a large diff may have seen only its head. Either split the diff so each pass fits, or drop the truncated leg from an over-cap pass and say so - never record a truncated pass as a clean pass.
   **Do not give reviewers filesystem `isolation: "worktree"` to protect the tree here** - a fresh worktree branches from `origin/<default-branch>`, not this feature branch, so it would review main, not the diff. The merge-base diff already computed is the correct isolation. Reserve `isolation: "worktree"` only for a probe that must branch off the feature HEAD itself, and require a checkpoint-commit + a post-hoc `git diff --stat` check when it is used that way.
3. **Record** the `quad-review` synthesized findings table in the runbook - it already deduped and consensus-tagged across the models, so do NOT build a second, divergent table. Sanity-check it for false positives from a truncated diff (a "missing tests/migration" finding when they exist).
4. **Act on the verdict:**
   - **No must-fix defects left** -> Phase 4. The exit is the absence of DEFECTS, not the reviewers running out of things to suggest: multiple models will always propose more, and advisory enhancements do not hold the gate open.
   - **Confirmed DEFECTS** (correctness, security, breakage, missing test) -> scoped fix-run (`--effort high`, `xhigh` for security-touching code) -> re-verify gates (Phase 2) -> re-review. **Loop, max 3 cycles.** Run the loop autonomously: fix, re-verify, re-review, repeat - do NOT pause between cycles to ask the user whether to keep going. `quad-review` runs in gate mode here and returns its table to you, not a menu to the user. If still not converging after 3, STOP and report the outstanding findings.
   - **ENHANCEMENTS** (a new feature, a bigger refactor, a speculative abstraction, hardening beyond the plan) -> **do NOT build them and do NOT loop on them.** Log each in the runbook Follow-ups. Only defects drive the cycle; a round that returns only enhancements is a clean exit.
   - **A genuine design/product decision, OR an enhancement that would add new surface area beyond the plan** (a feature, endpoint, flag, dependency, or abstraction) -> **STOP and escalate to the user.** Do not fold a decision or new scope into a "fix."

## Phase 4: Ship or stage (per the Phase 0 authorisation)

**Clean the tree first, both paths.** Ensure the diff is source-only: no build artifacts (verify/add `.gitignore` for `__pycache__/`, `*.pyc`, `dist/`, `node_modules/`, coverage files) and **no stray agent scratch files** (a root-level `test_task.py`, a `debug_*.py`, a scratch script the build left outside the test tree); `git rm --cached` any that slipped in. A stray artifact in the diff is a finding to fix before terminus (a committed `.pyc` is an easy leak when a lint gate like `py_compile` generates bytecode into an un-ignored tree). Then squash the wip commits into one clean commit on the feature branch (e.g. `git reset --soft <base> && git commit`), and immediately before the deploy-safely gates run, re-check `git log <merge-base>..HEAD --oneline` for a stray wip commit and re-squash if one reappears.

**If `deploy_authorised` is NO (the default) - stage push-ready:**

1. Do NOT push. Draft the PR description: what/why, suite counts, the quad-review result, and the rollback pointer.
2. Write a **PENDING** deploy-record stub in the project's deploy log/record (revision/sha left blank until the user deploys).
3. Go to Phase 5; the browser pass runs against the worktree / preview build, not production.

**If `deploy_authorised` is YES - deploy to production on green:**

Run the project's `deploy-safely` skill and EVERY gate it names (origin safety, main sync behind=0, local-main publication, wip-free range), then the project's own deploy recipe - the SAME production path `dev-quick-build` uses. For a container target (e.g. Cloud Run): build-then-deploy-by-digest (never deploy from source), pre-flip marker verify on a revision-tagged URL, **flip traffic to 100%** (the step that makes it live: a revision left at no-traffic is deployed **dark**, not deployed), then a Served-Image Integrity gate (compare the built digest to the `percent=100` traffic entry) and an ancestor gate (must **abort**, not echo). Smoke the **live prod URL**, not the revision-tag URL (200 + new markers, a health canary, clean revision log). Record the deploy in the project's deploy log (revision, sha, digest, markers, rollback pointer, suite + review results). Note: some projects deploy prod on merge via CI - there "deploy to production" = merge the branch to `main`. Then go to Phase 5; the browser pass runs against **production**.

## Phase 5: Verify (invoke dev-qa-verify)

Hand off to **`dev-qa-verify`** - the house verification-before-completion gate. It runs the interactive browser/persona pass (interact, do not just look - click every new control, check counts/orders against what the data implies, screenshot the evidence) against the right target - **production** when `deploy_authorised` (Phase 4 deployed it), the **worktree / preview build** otherwise - and triages any defect by severity:

- **Build bug** -> loops back through the dev-auto-build mechanics: a scoped fix-run (Phase 1, `--effort high`, `xhigh` for security-touching code; verify the diff yourself) -> whole-diff gates (Phase 2) -> quad-review cycle (Phase 3) -> re-ship (Phase 4) -> re-verify. **Bounded: max 2 cycles**; if it survives, STOP and report the outstanding break, what was tried, and the next step.
- **Plan-level** miss -> route to `dev-writing-plans` (revise the plan, re-enter the build); **wrong-concept** -> `dev-brainstorming`. Never fold a plan or product decision into a "fix".

`dev-qa-verify` owns the SSO/credentials rule (never type credentials), the Reversible smoke-data rule (below), and the OWED convention: if the target is signed out or no browser is connected (a scheduled / background run), it records the pass as OWED and does not block - there is nothing to loop on until a browser runs. The run reaches Terminus only when this gate is green or explicitly OWED.

## Terminus

**Output style.** Write the summary below in the reader's active output style. If none is set, default to: lead with the answer, short sentences, plain words, no idiom. Keep every required field (gates, review, browser result, branch, revision / sha / digest, rollback); cut only padding.

- **Not authorised:** emit the push-ready summary - what was built, gates + review + browser result, the branch name, what is OWED, and the exact command the user runs to push / PR. **No push, no merge, no deploy.**
- **Authorised:** emit the shipped summary - revision / sha / digest, the deploy-record pointer, the browser evidence, and the rollback pointer. The branch is deployed (the new revision serves **100% of live traffic** on the production URL, verified there - never left dark at 0%) and merged to main.

## Reversible smoke-data rule (verification)

Verification MAY create and exercise real write paths, including test/smoke data, without an approval pause, when ALL hold:
- **Reversible and self-contained:** create, then remove, your own test artifacts, and confirm the removal landed. Never delete or overwrite pre-existing real data.
- **Prefers staging / test-mode / test accounts.** On a production surface, only data invisible to real customers that sends no notification and triggers no downstream automation.
- **Emits nothing external:** no email/SMS/DM/chat to real people, no money movement (charge/refund/transfer/trade), no publish to a public surface. These stay red-lane and human-gated **regardless of reversibility**.
- **Audited:** log every created artifact and its cleanup in the runbook. A failed cleanup is a **blocking finding**, never silent residue.

## Cost and iteration bounds (stop conditions)

- Per-plan token ceiling (default ~200k): if exceeded, STOP and report progress + what remains.
- Build fix-runs: max 2 per task. Review cycles: max 3. dev-qa-verify browser loop (Phase 5): max 2. These bounds are what make the loops terminate.
- Track approximate spend in the runbook; a breach is a hard stop, not a warning.

## Failure and escalation

- A task that cannot pass its gates after the bounded attempts: STOP, report which task, expected vs actual, what was tried, suggested next step. Never skip a failing task.
- A red-lane requirement discovered mid-build: STOP, escalate. Do not attempt it autonomously.
- A design/product decision: STOP, escalate to the user with the options, do not decide unilaterally.

## Relationship to other skills

- `dev-quick-build`: the small-scope, human-present fast path that ALWAYS ships to prod on green. dev-auto-build is plan-driven and autonomous; it ships too, but only when deploy is authorised at kickoff (Phase 0), else it stops at push-ready. Both end by handing off to `dev-qa-verify`.
- **Plan execution is folded in here directly.** The task-by-task run, living-plan-file updates, checkpoints, and resume-from-last-task are part of `dev-auto-build`, the house-method, build-agent-powered, autonomous form (see the living-plan section above).
- `repo-health-sweep`: the first consumer; fans out across repos and calls `dev-auto-build` per failing repo.
- `deploy-safely` / `session-wrap`: what the user runs AFTER dev-auto-build hands off the push-ready worktree - squash the wip commits into one clean commit (e.g. `git reset --soft <base> && git commit`) if you haven't already, then `session-wrap` integrates and closes out.
- `dev-qa-verify`: the shared closing verification gate (Phase 5).
