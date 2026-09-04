---
name: auto-build
description: "Autonomously execute a plan/runbook end to end using a rigorous build method: Codex builds per phase, Claude verifies independently, triple review (Codex+Gemini+GLM) cycles findings back to Codex until clean, then a final browser pass whose defects loop back through build + review. Stops at a PUSH-READY worktree by default (never pushes/merges/deploys); deploys to production on green only when that is authorised at kickoff. Use when the user hands over a plan and wants it built autonomously without babysitting. Triggers on: auto build, autobuild, run the plan, execute this plan autonomously, build this plan, build to push-ready, autonomous build."
---

# Auto-Build: Autonomous Plan-Driven Build Engine

Take a plan/runbook and drive it, unattended, using a rigorous build method (Codex runbook build + triple review). quick-build is the small, human-present fast path that always ships to prod; auto-build is the plan-driven, autonomous engine that stops at push-ready by default and deploys to prod only when authorised at kickoff.

> **The non-negotiable gates are the same on every path** and this skill enforces them: TDD, full local gates, multi-model (triple) review, worktree isolation, and build-then-deploy-by-digest + Served-Image Integrity + ancestor gate for any deploy. This skill owns the autonomous mechanics; wire it to your project's own build/deploy playbook where one exists.

**The terminus depends on the kickoff deploy-authorisation choice (Phase 0).**

- **Not authorised (the default):** auto-build STOPS at a **push-ready worktree** - branch committed, gates green, triple review clean (or a design decision escalated), browser pass done, PR drafted. It never pushes, merges, or deploys; the user owns that gate. This is the historical behaviour.
- **Authorised:** auto-build runs the same build + review, then **deploys to production on green** through the `deploy-safely` gates (like `quick-build`), verifies live in the browser, and merges to main. Authorisation is decided ONCE at kickoff (Phase 0) and is never inferred mid-run.

Either way the browser pass is the **final gate**, and a browser-caught defect loops back to the Codex build and triple review before the run can end (Phase 6).

## Lanes (what auto-build may do autonomously)

Classify the plan before running.

- **Green** (reversible, low-risk: dep bumps, lint/format, test backfill, doc fixes, self-contained features): run to push-ready autonomously.
- **Yellow** (feature builds, refactors): run to push-ready autonomously; the push-ready PR is the gate.
- **Red** (authz, schema migration, secrets, external comms, money movement, publishing): **STOP and escalate.** Never done autonomously, even if a task claims to be "reversible" (a refund is reversible but is a transfer; a sent notification cannot be recalled). If any plan task is red-lane and the invocation did not explicitly authorize it, stop in Phase 0 and report.
- **Deploying the built feature to production** is NOT auto-red here: it is gated by the Phase 0 deploy-authorisation choice. Authorised at kickoff -> the end-of-run deploy proceeds on green. Not authorised -> push-ready terminus, no deploy. Every OTHER red-lane task above stays red regardless of that choice.

## Invariants (hold throughout)

- **Deploy only if authorised at kickoff.** With authorisation, push / merge / deploy happen ONLY at the end, through `deploy-safely` gates, after the browser pass. Without it (the default), never push, merge, or deploy - all work stays on a feature branch in an isolated worktree.
- **Never** edit secrets/authz/migrations autonomously unless the plan + invocation explicitly authorize it (then use `xhigh` and flag for the user).
- **Never trust an agent's self-report.** After every Codex run, Claude reads the diff, confirms scope, and re-runs the gates itself.
- **Every loop is bounded** with a checkable stop condition and a cost cap that aborts.
- **Cost / model dispatch:** Sonnet for orchestration and gate-running; Codex `-m gpt-5.5` at **`high`** for builds (`xhigh` only for security/authz/migration/architectural tasks, and for all reviews). Per-run and total token ceilings (defaults: ~200k per plan; abort on breach).

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

## Phase 1: Per-phase Codex build (build loop)

For each phase/task in the plan, in dependency order (disjoint-file phases may run in parallel; overlapping phases stay sequential):

1. **Scope the Codex run.** Write a focused prompt: "Implement Task N, touch nothing else. TDD: write failing tests first, confirm they fail for the right reason, then implement to green." Include the empirical grounding note (verify against the live code, do not trust doc claims).
2. **Invoke your build agent** (e.g. the Codex CLI in a headless/exec mode), build tier not review:
   ```bash
   codex exec --dir "$REPO" -- "$PROMPT"
   # high reasoning effort for normal tasks; raise it ONLY for security/authz/migration/architectural tasks
   ```
   Handle a wedge: a timeout / stuck-agent signal means relaunch attached, do not passively wait.
3. **Verify independently (never trust self-report):**
   - Read the diff yourself (`git diff`); confirm it touched only in-scope files.
   - Run the repo's gates yourself (lint, typecheck, build, tests). Record the counts in the runbook.
   - **Exercise any write path the default test run does not.** A tool with a dry-run/apply split, or a write path behind an `if apply:` / `if commit:` guard, can ship broken while gates + dry-run are all green: a build's `--apply` path can raise `KeyError` on its first live row because the dry-run skips that branch AND the tests mock the writer, so nothing ever runs the real write path against the real payload. For any such path, add a test that runs the REAL writer against the REAL payload shape, and - where a live target exists and the write is reversible - run a single **canary apply (one row) with post-verify** before trusting the batch. A clean dry-run is not proof the apply path runs.
4. **Gates red -> bounded fix-run.** Send Codex a scoped fix prompt; re-verify. Stop after 2 attempts on a task and report the failure (do not thrash).

## Phase 2: Whole-diff local gates

After all phases, run the repo's full gate set (lint, typecheck, build, tests) over the full feature state. Must be all-green before review. Record counts in the runbook.

## Phase 3: Triple-review cycle (review loop)

1. Compute the **isolated feature diff** from the merge-base (`git merge-base origin/main HEAD`), not raw `origin/main`, so unrelated in-flight work does not pollute the review.
2. Run the review panel via the **`triple-review`** skill in `build` mode over the **isolated feature diff** (`<merge-base>...HEAD`). It runs Codex + Gemini + GLM in parallel and returns one synthesized, consensus-tagged findings table.
   **Scale to the diff:** a trivial diff (a lint/format autofix) gets a light single-model pass; a substantive diff gets the full panel. A reviewer reported unavailable (GLM unfunded, a wedge) does not block the other two; note it.
   **Split a large diff into focused per-subsystem passes.** A single monolithic review of a big diff has false coverage: a single 372KB one-shot review can miss real findings that focused per-area passes (and a GitHub PR bot) then catch. Above ~60KB, run `triple-review` per subsystem (e.g. resolver, webhooks, entitlements, migration/scripts, SPA) with its own file set, then reconcile - do not trust one review of the whole thing.
   **A truncated GLM is not a clean GLM.** GLM silently truncates its input above ~60KB, so a "clean" GLM verdict on a large diff may have seen only its head. Either split the diff so each pass fits, or drop the GLM leg from an over-cap pass and say so - never record a truncated GLM as a pass.
3. **Record** the `triple-review` synthesized findings table in the runbook - it already deduped and consensus-tagged across the three models, so do NOT build a second, divergent table. Sanity-check it for false positives from a truncated diff (a "missing tests/migration" finding when they exist).
4. **Act on the verdict:**
   - **All clear** -> Phase 4.
   - **Confirmed findings** -> scoped Codex fix-run (`--effort high`, `xhigh` for security-touching code) -> re-verify gates (Phase 2) -> re-review. **Loop, max 3 cycles.** If still not converging after 3, STOP and report the outstanding findings.
   - **Genuine design or product decision flagged** (e.g. a trust-model choice) -> **STOP and escalate to the user.** Do not fold a product decision into a "fix."

## Phase 4: Ship or stage (per the Phase 0 authorisation)

**Clean the tree first, both paths.** Ensure the diff is source-only: no build artifacts (verify/add `.gitignore` for `__pycache__/`, `*.pyc`, `dist/`, `node_modules/`, coverage files) and **no stray agent scratch files** (a root-level `test_task.py`, a `debug_*.py`, a scratch script the build left outside the test tree - builds routinely leave a stray `test_task.py` a reviewer then catches); `git rm --cached` any that slipped in. A stray artifact in the diff is a finding to fix before terminus (a committed `.pyc` is easy to leak this way when a lint gate like `py_compile` generates bytecode into an un-ignored tree). Then squash the wip commits into one clean commit on the feature branch (e.g. `git reset --soft <base> && git commit`).

**If `deploy_authorised` is NO (the default) - stage push-ready:**

1. Do NOT push. Draft the PR description: what/why, suite counts, the triple-review result, and the rollback pointer.
2. Write a **PENDING** deploy-record stub in the project's deploy log/record (revision/sha left blank until the user deploys).
3. Go to Phase 5; the browser pass runs against the worktree / preview build, not production.

**If `deploy_authorised` is YES - deploy to production on green:**

Run the project's `deploy-safely` skill and EVERY gate it names (origin safety, main sync behind=0, local-main publication, wip-free range), then the project's deploy recipe - the SAME production path `quick-build` uses. For a container target (e.g. Cloud Run): build-then-deploy-by-digest (never deploy from source), pre-flip marker verify on the revision-tag URL, flip traffic, then the Served-Image Integrity gate (compare the built digest to the `percent=100` traffic entry) and the ancestor gate (must **abort**, not echo). Smoke the prod URL (200 + new markers, `/health` canary, clean revision log). Record the deploy in the project's deploy log (revision, sha, digest, markers, rollback pointer, suite + review results). Note: some projects deploy prod on merge via CI - there "deploy to production" = merge the branch to `main`. Then go to Phase 5; the browser pass runs against **production**.

## Phase 5: Browser / persona verification (final gate)

CLI smokes pass while rendered pages are broken - the browser pass is what catches that. Run it automatically as part of the pipeline.

- If the change has a UI surface and a signed-in session is available in Claude-in-Chrome, verify by **interacting**, not just looking: click every new control, check counts / orders against what the data implies, screenshot the evidence. Subject to the Reversible smoke-data rule below.
- Target: **production** when `deploy_authorised` (Phase 4 deployed it); the **worktree / preview build** otherwise.
- If the target is signed out (SSO needs the user; the extension must not type credentials) or no browser is connected (a scheduled / background run), record the pass as **OWED** and continue without blocking. An OWED pass does not gate the loop below - there is nothing to loop on until a browser actually runs.

## Phase 6: Browser feedback loop (bounded)

A browser-caught defect is a real finding, never a "known issue" you ship or hand off past. If Phase 5 surfaces a rendered break, a wrong count / order, or a broken control, **loop back** - do not just report:

1. **Back to the Codex build (Phase 1 mechanics):** scoped fix-run for the defect (`--effort high`, `xhigh` for security-touching code). Verify the diff yourself.
2. **Re-run the whole-diff local gates (Phase 2).**
3. **Re-run the triple-review cycle (Phase 3)** over the new isolated feature diff.
4. **Re-ship (Phase 4):** if `deploy_authorised`, redeploy through `deploy-safely`; otherwise refresh the push-ready state.
5. **Re-verify in the browser (Phase 5).**

**Bounded: max 2 browser-loop cycles.** If the defect survives 2 cycles, STOP and report the outstanding break, what was tried, and the suggested next step.

## Terminus

- **Not authorised:** emit the push-ready summary - what was built, gates + review + browser result, the branch name, what is OWED, and the exact command the user runs to push / PR. **No push, no merge, no deploy.**
- **Authorised:** emit the shipped summary - revision / sha / digest, the deploy-record pointer, the browser evidence, and the rollback pointer. The branch is deployed and merged to main.

## Reversible smoke-data rule (verification)

Verification MAY create and exercise real write paths, including test/smoke data, without an approval pause, when ALL hold:
- **Reversible and self-contained:** create, then remove, your own test artifacts, and confirm the removal landed. Never delete or overwrite pre-existing real data.
- **Prefers staging / test-mode / test accounts.** On a production surface, only data invisible to real customers that sends no notification and triggers no downstream automation.
- **Emits nothing external:** no email/SMS/DM/chat to real people, no money movement (charge/refund/transfer/trade), no publish to a public surface. These stay red-lane and human-gated **regardless of reversibility**.
- **Audited:** log every created artifact and its cleanup in the runbook. A failed cleanup is a **blocking finding**, never silent residue.

## Cost and iteration bounds (stop conditions)

- Per-plan token ceiling (default ~200k): if exceeded, STOP and report progress + what remains.
- Build fix-runs: max 2 per task. Review cycles: max 3. Browser-loop cycles (Phase 6): max 2. These bounds are what make the loops terminate.
- Track approximate spend in the runbook; a breach is a hard stop, not a warning.

## Failure and escalation

- A task that cannot pass its gates after the bounded attempts: STOP, report which task, expected vs actual, what was tried, suggested next step. Never skip a failing task.
- A red-lane requirement discovered mid-build: STOP, escalate. Do not attempt it autonomously.
- A design/product decision: STOP, escalate to the user with the options, do not decide unilaterally.

## Relationship to other skills

- `quick-build`: the small-scope, human-present fast path that ALWAYS ships to prod on green. auto-build is plan-driven and autonomous; it ships too, but only when deploy is authorised at kickoff (Phase 0), else it stops at push-ready. Both end with the browser gate + bounded loop.
- `executing-plans`: generic Claude-executes-a-plan. auto-build is the rigorous-method, Codex-powered, autonomous variant that stops at push-ready.
- `repo-health-sweep`: the first consumer; fans out across repos and calls auto-build per failing repo.
- `deploy-safely` / `finish-branch` (and squashing your wip commits into one clean commit, e.g. `git reset --soft <base> && git commit`): what the user runs AFTER auto-build hands off the push-ready worktree.
