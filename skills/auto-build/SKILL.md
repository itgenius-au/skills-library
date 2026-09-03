---
name: auto-build
description: "Autonomously execute a plan/runbook end to end to a PUSH-READY worktree using a rigorous build method: Codex builds per phase, Claude verifies independently, triple review (Codex+Gemini+GLM) cycles findings back to Codex until clean, stopping at the human gate (never pushes, merges, or deploys). Use when the user hands over a plan and wants it built autonomously without babysitting. Triggers on: auto build, autobuild, run the plan, execute this plan autonomously, build this plan, build to push-ready, autonomous build."
---

# Auto-Build: Autonomous Plan-Driven Build Engine

Take a plan/runbook and drive it to a **push-ready worktree**, unattended, using a rigorous build method (Codex runbook build + triple review). quick-build is the small, human-present, ship-to-prod fast path; auto-build is the plan-driven, autonomous, stop-at-the-gate engine.

> **This skill owns the autonomous mechanics.** The non-negotiable gates it enforces - TDD, full local gates, triple/multi-model review, worktree isolation, and build-then-deploy-by-digest + integrity + ancestor gate at deploy time - come from a rigorous build method; keep them in sync with your project's own build/deploy playbook if you have one.

**The terminus is a push-ready worktree, not a deploy.** auto-build STOPS when the branch is committed, gates are green, triple review is clean (or a design decision is escalated), and a PR is drafted. It never pushes to a remote, merges to main, or deploys. the user owns that gate.

## Lanes (what auto-build may do autonomously)

Classify the plan before running, using the lane model below.

- **Green** (reversible, low-risk: dep bumps, lint/format, test backfill, doc fixes, self-contained features): run to push-ready autonomously.
- **Yellow** (feature builds, refactors): run to push-ready autonomously; the push-ready PR is the gate.
- **Red** (authz, schema migration, secrets, deploy, external comms, money movement, publishing): **STOP and escalate.** Never done autonomously, even if a task claims to be "reversible" (a refund is reversible but is a transfer; a sent notification cannot be recalled). If any plan task is red-lane and the invocation did not explicitly authorize it, stop in Phase 0 and report.

## Invariants (hold throughout)

- **Never** push to a remote, merge to main, or deploy. All work on a feature branch in an isolated worktree.
- **Never** edit secrets/authz/migrations autonomously unless the plan + invocation explicitly authorize it (then use `xhigh` and flag for the user).
- **Never trust an agent's self-report.** After every Codex run, Claude reads the diff, confirms scope, and re-runs the gates itself.
- **Every loop is bounded** with a checkable stop condition and a cost cap that aborts.
- **Cost / model dispatch:** Sonnet for orchestration and gate-running; Codex `-m gpt-5.5` at **`high`** for builds (`xhigh` only for security/authz/migration/architectural tasks, and for all reviews). Per-run and total token ceilings (defaults: ~200k per plan; abort on breach).

## Phase 0: Intake and guardrail classification

1. Read the plan file completely. Confirm today's date from the environment (never infer it).
2. Classify each task green / yellow / red-lane. **Any unauthorized red-lane task -> STOP, report, do not proceed.**
3. Ensure an isolated worktree (`EnterWorktree`, or verify you are already in one that matches the target repo). Verify `git rev-parse --show-toplevel` is the worktree path before any edit.
4. Create the runbook doc `docs/plans/YYYY-MM-DD-<slug>-auto-build.md` with a `**Date:**` header and sections: Ask, Decisions, Build log, Review, Deploy. Update it at every phase transition (a one-line append is enough), not retrospectively.

## Phase 1: Per-phase Codex build (build loop)

For each phase/task in the plan, in dependency order (disjoint-file phases may run in parallel; overlapping phases stay sequential):

1. **Scope the Codex run.** Write a focused prompt: "Implement Task N, touch nothing else. TDD: write failing tests first, confirm they fail for the right reason, then implement to green." Include the empirical grounding note (verify against the live code, do not trust doc claims).
2. **Invoke Codex** headlessly (build tier, not review — the `codex-review` skill in this library wraps the same Codex CLI):
   ```bash
   # Run Codex CLI against "$REPO" at build-tier effort, in a sandboxed/inspect mode:
   codex exec --dir "$REPO" --effort high -- "$PROMPT"
   # use a network-enabled mode if the tests need network; effort xhigh ONLY for security/authz/migration/architectural tasks
   ```
   Handle a wedge: if Codex hangs (a timeout exit or a wedge marker), relaunch attached, do not passively wait.
3. **Verify independently (never trust self-report):**
   - Read the diff yourself (`git diff`); confirm it touched only in-scope files.
   - Run the repo's local gates yourself (lint, typecheck, tests, build). Record the counts in the runbook.
4. **Gates red -> bounded fix-run.** Send Codex a scoped fix prompt; re-verify. Stop after 2 attempts on a task and report the failure (do not thrash).

## Phase 2: Whole-diff local gates

After all phases, run the repo's full local gate suite (lint, typecheck, tests, build) over the full feature state. Must be all-green before review. Record counts in the runbook.

## Phase 3: Triple-review cycle (review loop)

1. Compute the **isolated feature diff** from the merge-base (`git merge-base origin/main HEAD`), not raw `origin/main`, so unrelated in-flight work does not pollute the review.
2. Run the three reviewers at `xhigh` — invoke the `codex-review`, `gemini-review`, and `zai-review` (GLM) skills yourself over `<merge-base>...HEAD` and reconcile their findings:
   **Scale to the diff:** a trivial diff (a lint/format autofix) gets a light single-model pass; a substantive diff gets the full panel. A reviewer reported unavailable (a model unfunded, a wedge) does not block the other two; note it.
3. **Synthesize** a finding x model x verdict table into the runbook. Watch for false positives from a truncated diff (a "missing tests/migration" finding when they exist).
4. **Act on the verdict:**
   - **All clear** -> Phase 4.
   - **Confirmed findings** -> scoped Codex fix-run (`--effort high`, `xhigh` for security-touching code) -> re-verify gates (Phase 2) -> re-review. **Loop, max 3 cycles.** If still not converging after 3, STOP and report the outstanding findings.
   - **Genuine design or product decision flagged** (e.g. a trust-model choice) -> **STOP and escalate to the user.** Do not fold a product decision into a "fix."

## Phase 4: Push-ready terminus

1. **Clean the tree, then squash.** Ensure the diff is source-only: no build artifacts (verify/add `.gitignore` for `__pycache__/`, `*.pyc`, `dist/`, `node_modules/`, coverage files) and `git rm --cached` any that slipped in. A stray artifact in the diff is a finding to fix before terminus (a dogfood run once caught a committed `.pyc` this way, because the lint gate `py_compile` generated bytecode into an un-ignored tree). Then squash the wip commits into one clean commit on the feature branch (e.g. `git reset --soft <base> && git commit`). Do not push.
2. Draft the PR description: what/why, suite counts, the triple-review result, and the rollback pointer.
3. Write a **PENDING** deploy-record stub in the project's deploy record (revision/sha left blank until the user deploys).
4. **Browser / persona verification** (automatic, when a browser session is available): if the change has a UI surface and a signed-in session is available in Claude-in-Chrome, verify by interacting (click every new control, check counts/orders), subject to the Reversible smoke-data rule below. If the target is signed out (SSO needs the user; the extension must not type credentials) or no browser is connected (a scheduled/background run), record the pass as **OWED** and continue without blocking.
5. **STOP.** Emit the summary: what was built, gates + review result, the branch name, what is OWED, and the exact command the user runs to push/PR. **No push, no merge, no deploy.**

## Reversible smoke-data rule (verification)

Verification MAY create and exercise real write paths, including test/smoke data, without an approval pause, when ALL hold:
- **Reversible and self-contained:** create, then remove, your own test artifacts, and confirm the removal landed. Never delete or overwrite pre-existing real data.
- **Prefers staging / test-mode / test accounts.** On a production surface, only data invisible to real customers that sends no notification and triggers no downstream automation.
- **Emits nothing external:** no email/SMS/DM/chat to real people, no money movement (charge/refund/transfer/trade), no publish to a public surface. These stay red-lane and human-gated **regardless of reversibility**.
- **Audited:** log every created artifact and its cleanup in the runbook. A failed cleanup is a **blocking finding**, never silent residue.

## Cost and iteration bounds (stop conditions)

- Per-plan token ceiling (default ~200k): if exceeded, STOP and report progress + what remains.
- Build fix-runs: max 2 per task. Review cycles: max 3. These bounds are what make the loops terminate.
- Track approximate spend in the runbook; a breach is a hard stop, not a warning.

## Failure and escalation

- A task that cannot pass its gates after the bounded attempts: STOP, report which task, expected vs actual, what was tried, suggested next step. Never skip a failing task.
- A red-lane requirement discovered mid-build: STOP, escalate. Do not attempt it autonomously.
- A design/product decision: STOP, escalate to the user with the options, do not decide unilaterally.

## Relationship to other skills

- `quick-build`: the small-scope, human-present, ship-to-prod fast path. Different terminus (deploys) and driver (human).
- `executing-plans`: generic Claude-executes-a-plan. auto-build is the rigorous-method, Codex-powered, autonomous variant that stops at push-ready.
- `repo-health-sweep`: the first consumer; fans out across repos and calls auto-build per failing repo.
- `deploy-safely` / squash-and-push / `finish-branch`: what the user runs AFTER auto-build hands off the push-ready worktree.
