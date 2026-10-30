---
name: dev-writing-plans
description: "Turn a spec into a granular, dependency-ordered implementation plan with a file-structure map, right-sized tasks, verification criteria, risk/rollback flags, and checkpoints - then harden it with a review-swarm-until-consensus loop before any build. Use when the user says 'write plan', 'write a plan', 'document a plan', 'create a plan', 'make a plan', 'draft a plan', 'implementation plan', 'build plan', 'break this down', 'plan this', 'plan this out', 'task breakdown', 'how should we build this', 'plan the work', or after completing a dev-brainstorming session."
argument-hint: "[spec file path or feature description]"
---

# dev-writing-plans: Spec -> Implementation Plan

Takes a spec (from `dev-brainstorming` or provided directly) and produces a granular, ordered implementation plan that `dev-quick-build` or `dev-auto-build` can run - hardened by a review-swarm-until-consensus loop so the plan is sound before a line of code is written.

> **Credit.** The task-template shape, the "Task Right-Sizing" rubric, and the file-structure-before-decomposition step in this skill are structurally derived from Jesse Vincent's [superpowers](https://github.com/obra/superpowers) `superpowers:writing-plans` skill (MIT licensed). See [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) for the full notice.

## When to Use

- After `dev-brainstorming` produces a spec.
- The user has a clear idea of what to build and needs a step-by-step plan.
- Before any non-trivial implementation (3+ files, new service, cross-project work).

## Inputs

One of:
1. **Spec file** - a spec from `dev-brainstorming` (e.g. `docs/plans/YYYY-MM-DD-<topic>-spec.md`).
2. **Inline description** - the user describes what to build.
3. **Existing code** - the user points to code to refactor/extend.
4. **Locked design artefact** - for a UI/visual feature, an interactive Claude Artifact mockup the user iterated on and locked during `dev-brainstorming`. Treat its URL as the design record: open it alongside any prose spec, and carry the URL into the plan and into any task whose Approach implements it.

If no spec exists and the work is architectural, offer to run `dev-brainstorming` first.

## Workflow

### Step 1: Understand the full picture

1. **Read the spec** completely, if one exists.
2. **Survey the codebase** - existing patterns and conventions, files to modify vs create, test patterns in use, the CI/CD + deploy process, related code that might be affected.
3. **Check dependencies** - prerequisites, other PRs in flight, blocked tickets in your issue tracker.
4. **Identify the critical path** - the minimum sequence that gets something working end to end.

### Step 2: File structure (define BEFORE decomposing)

Lay out the concrete file/module structure the plan will build, mapped to the spec's architecture. This turns an abstract design into named files and catches structural problems before they become task churn.

- **List every file** the plan touches, marked create / modify, with a one-line purpose each.
- **Reuse check on every "create".** For each file/module marked *create*, add a `Reuses: <existing component + path>` (valid only if you actually grepped the codebase and it fits) or `New: <one line on why nothing existing fits>`. A reuse claim from memory is not evidence - grep it. This is where a duplicate helper/component gets caught, before it is built.
- **Place new modules** deliberately: which directory, following the project's existing layout and naming. Do not invent a new structure where the project has a pattern.
- **Name the boundaries** - which unit owns which responsibility, and the interfaces between them. If a file would grow too large or take on two jobs, split it here, in the plan, not mid-build.
- **New cloud resources: exact name and location.** List each new cloud resource the plan creates with its exact name and its region or location, checked against your project's naming conventions (co-locate with what it talks to, measured live). Names of many cloud resources cannot be changed later. `dev-auto-build` signs these off from the plan before its build loop, so a missing location here becomes a question there.
- **Note shared/edited surfaces** - config, schema, routing, types - so their tasks can be ordered first and flagged for risk.
- **Find every producer and consumer of a changed artefact.** When the plan changes something that is fetched, staged, cached, reported or put in a prompt (a file, a token, a path, a payload key), grep the repo for every place that writes or reads it - installers, cron wrappers, second code paths (a resume or wake prompt beside the spawn prompt), list and report tools, test fixtures - and put each one in the file list. Do not stop at the first module that obviously changes. A short read-only survey at planning time usually finds the second prompt, installer or cache key that the obvious change would have missed.

Record this as a "File Structure" section in the plan.

### Step 3: Decompose into right-sized tasks

Break the work into tasks, ordered by dependency, grouped by layer not feature (foundations - data model, API - before features on top). Make verification (tests, smoke checks, integration) explicit tasks, not afterthoughts.

**Plan the simplest thing that meets the spec.** The spec is the scope ceiling, not a launchpad: pick the fewest tasks and files that deliver it, and YAGNI anything the spec did not ask for - no speculative abstractions, no "we might also want" features, no hardening for a case the spec excludes. A plan is easier to overbuild than code, because adding a task costs a line here and a build session later. If a genuinely useful idea is out of scope, it goes in the plan's Non-goals section, not its Task List.

**Task right-sizing** - the rubric every task must pass:

- **One testable result.** After the task, you can verify it works. If you cannot state its verification in one line, it is not one task.
- **One focused session** (~30 minutes of AI work). Bigger = split it.
- **A coherent file set** - the files from Step 2 that change together for one reason.
- **Too big** ("build the API", "add auth") is a project, not a task - decompose it.
- **Too small** (a one-line config change) does not get its own task - fold it into the neighbour it serves.

For each task:

```markdown
### Task {N}: {Title}
**Goal**: {what this achieves - one sentence}
**Files**: {create/modify, from the Step 2 structure}
**Depends on**: {task numbers, or "None"}
**Approach**:
- {step-by-step; specific patterns to follow; reference existing code}
**Verification**:
- {how to confirm it's done: exact test commands, curl calls, or checks}
**Estimated effort**: {S/M/L}
```

### Step 4: Risks and checkpoints

1. **Checkpoint tasks** after every 3-5 tasks or at a milestone - an explicit task that pauses and verifies everything still works together.
2. **Risk flags** (`**Risk**:` field) on any task that touches shared infrastructure, changes a schema or an API contract, or affects other projects - what could go wrong and how to mitigate it.
3. **Rollback notes** for destructive or hard-to-reverse tasks.
4. **Payoff and code budget** when the spec exists to cut cost (money, tokens or spend): the expected saving, the measure that proves it (what runs, on what, and the pass mark), and a code budget counted as the lines the branch adds to code and test files (`git diff --numstat origin/<default>...HEAD`, docs not counted). Put the measure before any further build round. Add a checkpoint after each measure and at each phase end, written as `**STOP on a miss**: over budget or below the pass mark = escalate; do not start the next task until the user gives a go and a new budget`. `dev-auto-build` treats that miss as an escalation. A cost-saving build whose code costs more than it saves is a net loss; see `dev-quick-build`'s scope gate.

### Step 5: Write the plan document

Create `docs/plans/YYYY-MM-DD-<descriptive-name>-plan.md`. **Confirm today's date from the environment first** (the `currentDate` context line, or `date +%F`); never infer it or copy a date from an example; use ISO `YYYY-MM-DD`. (This date discipline does not travel to subagents - restate it in any delegating prompt.) For child projects, use the same path relative to the child root. Create `docs/plans/` if needed.

```markdown
# {Project/Feature Name} - Implementation Plan

**Date**: {ISO YYYY-MM-DD, confirmed from the environment}
**Spec**: {link to the spec file if one exists}
**Design reference**: {locked design artefact URL, if one exists - reference it, don't re-describe it, in any task that implements it}
**Target project**: {directory/repo}
**Estimated total effort**: {S/M/L/XL}
**Tasks**: {count}  |  **Checkpoints**: {count}

## Prerequisites
- {what must be true before starting}

## File Structure
- {create/modify file list from Step 2, with one-line purposes}

## Non-goals / Out of scope
- {what this plan explicitly does NOT do - carried from the spec's Out of Scope, plus anything reviewers or scouting raised that is deliberately deferred. This is the fence the build holds to: an item here is a Follow-up, never a task that quietly reappears.}

## Task List
### Task 1: {Title}
...
### Checkpoint A: {verify milestone}
...

## Execution Notes
- {git strategy: branch name, commit cadence}
- {deploy strategy: how and when}
- {coordination: who/what to notify}

## Definition of Done
- {all task verifications pass; integration tests pass; deployed if applicable; manual checks}
```

### Step 6: Review-swarm-until-consensus loop (the gate)

A plan is not ready to build until the review panel (three external models plus a deep-reasoning fourth) finds no must-fix defect left in it. Do NOT hand off on a single pass. The gate is defect-free, not "everyone ran out of ideas" (see step 4).

1. **Invoke the `review-swarm` skill in `plan` mode** on the plan file. It fans four independent models out in parallel and returns ONE synthesized, consensus-tagged findings table - no hand-rolled fan-out. Ask it: is the decomposition sound and correctly ordered; is any task mis-sized; is the file structure right; is any risk or dependency missing; is anything unbuildable as written; does each 'create' entry's Reuse check hold up against the real repo (grep it - an unverified or false reuse/new claim is a must-fix); and what in the plan goes beyond the spec or would block the user's normal path (`simplify`). Pass the spec's goal and Non-goals as THE ASK and NON-GOALS.
2. **Fold MUST-FIX defects back INTO the plan** (the `review-swarm` must-fix rule: critical/high, or medium flagged by 2+ legs; everything else is advisory and goes in one line under Non-goals or Follow-ups), and apply `simplify` items that remove something outside the spec - a mis-sized or mis-ordered task, a missing risk/dependency, something unbuildable as written. Update tasks, file structure, ordering, risks. Do not argue findings in chat; fix the plan. A reviewer ENHANCEMENT (an extra feature, a speculative abstraction, "we could also") does NOT become a task - it goes in the plan's Non-goals section. Four models will always suggest more scope; the plan does not grow to absorb it.
3. **Re-run `review-swarm`** on the updated plan.
4. **Loop until no must-fix DEFECT remains** - the decomposition is sound, ordered, right-sized, and buildable as written. The exit is the absence of defects, NOT the reviewers running out of suggestions: "reviewers agree it is good" ratchets a plan bigger every cycle, because a fresh model always finds one more thing to add. Advisory enhancements do not hold the gate open. **Run this loop autonomously: fold the defects, re-run, repeat - the re-run IS the loop. Do NOT pause between cycles to ask the user whether to keep going.** `review-swarm` runs in gate mode here: it returns its table to you and does not hand the user a follow-up menu. The only thing that breaks the loop early is the bound in step 5, a genuine product / design decision, or an enhancement that would add new surface area beyond the spec (surface that as a scope decision).
5. **Bound it:** if the plan is not converging after ~3 cycles, or two reviewers disagree irreconcilably on a real design point, STOP and surface it to the user (offer `review-debate` to litigate the specific dispute) rather than looping forever. **A single finding rejected twice escalates ahead of the cycle bound:** if the SAME finding (review-swarm already dedups and consensus-tags them) is rejected a second consecutive time - re-disputed after a fix, or disputed again with no fix - stop re-litigating it now, escalate it by name to the user, and record the ruling as a dated line in the Review History that later cycles and the build treat as settled. A reviewer reported unavailable (a model unfunded, a wedge) does not block the others; consensus is over the legs that ran, and say which.
6. Record the review history (models run, what changed each cycle) in the plan.

### Step 7: Executive summary, then hand straight off (no sign-off gate)

The user does not read the full plan, and does not sign it off. When Step 6 reports the plan clean, post a SHORT executive summary - 3-6 bullets, nothing more:

- **What gets built** - one line.
- **Tasks + effort** (count + S/M/L/XL) and the **critical path**.
- **Asked vs planned** - one line: the spec's ask against the plan's task count and any new flag, mode, guard, script or dependency. Record the first draft's task count in the Review History. **If review cycles added tasks or new surface area beyond the first draft, STOP here and ask the user before hand-off** - this is the one approval a plan needs, and it must name the size ("go = build <N> tasks: ..."). Why: a small ask can become a very large plan through several review rounds, approved by a single "go".
- **Any risk or rollback flag** worth naming.
- **Deploy target** - prod on green, or push-ready (whatever was authorised at kickoff).
- **Any decision the user still genuinely owns** - only a real product / design / trust call, never "may I proceed?".

**Output style.** Write the summary with the `exec-summary` skill if you have it, using the five bullets above as its sections; otherwise write them in the reader's active output style, defaulting to short sentences and plain words. The hand-off below stays as it is: do not add an approval question, except the scope-growth stop in the "Asked vs planned" bullet.

Then hand straight off to the build pathway - do NOT wait for approval. A review-swarm-clean plan flows on its own: **`dev-auto-build`** for a plan-driven / multi-phase build (the autonomous engine - pass the kickoff deploy authorisation straight through to it), **`dev-quick-build`** for a small single-session feature. The summary is a fly-by so the user can interject if something is wrong; silence is not a gate. Only two things stop the hand-off: review grew the plan beyond its first draft (the "Asked vs planned" bullet), or a genuine decision surfaced in the last bullet - never a request for permission to build.

## Rules

- Plans follow the project's existing conventions - read its CLAUDE.md (or equivalent) and existing patterns first.
- Every task has a verification step. "Trust me it works" is not verification.
- Don't over-decompose simple work; don't under-decompose complex work (see the right-sizing rubric).
- The spec is the scope ceiling. Plan the simplest set of tasks that meets it; put anything beyond it in Non-goals, not the Task List. The review loop (Step 6) fixes defects, it does not grow the plan.
- The plan is a living document - `dev-auto-build` updates it as tasks complete.
- Include the git workflow: branch name, commit strategy, when to push.
- If the plan exceeds 20 tasks, split into phases with separate plans.
- Reference file paths relative to the target project root, not a parent orchestrator repo.
- The review-swarm loop (Step 6) is a gate, not a formality - the plan does not leave this skill until no must-fix defect remains (not until every reviewer agrees).
- **Refuse by default only where it is earned.** In the thing you build (not the deploy and CI gates, which still abort), a refusal, a typed confirmation token, or a "stop until a named person confirms" step belongs only on an action that is irreversible and destructive, or that moves money with no human in the loop. Everywhere else: warn, log, and continue. A human-in-the-loop skill trusts the human - the user's "go" approves the action, including a money action or a customer send; do not add a second confirmation word. An UNKNOWN answer is a warning to show, not a reason to refuse. Fail-closed defaults built into ops tools block normal work and have to be loosened later.
