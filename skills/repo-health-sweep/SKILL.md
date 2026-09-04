---
name: repo-health-sweep
description: "Green-lane loop that sweeps your code repos, runs each repo's OWN declared gates (test/lint/typecheck), and reports a health map. In --fix mode it hands each fixable failing repo to auto-build to produce a verified push-ready fix branch. Nothing is pushed, merged, or deployed. Triggers on: repo health sweep, health sweep, sweep repos, check all repos, repo gates sweep, fleet health check, are my repos green."
---

# Repo Health Sweep: Green-Lane Fleet Loop

Run every code repo's own gates, produce one health map, and (optionally) auto-fix the fixable failures into push-ready branches. This is a consumer of `auto-build` and a standing green-lane loop.

**Nothing leaves the machine.** Every fix lands on a feature branch in an isolated worktree. The sweep never pushes, merges, or deploys. the user reviews the report and the branches, then approves the batch.

## Modes

- `--report-only` (default, and the mandatory first live run): run each repo's gates and classify. No fixing. Produces the health map so you can see what is red before spending build/review budget.
- `--fix`: for each repo failing its gates, classify the failure; if it is fixable green/yellow-lane, generate a minimal fix-plan and invoke `auto-build` on that repo. Red-lane failures are reported and skipped.

## Flow

1. **Discover targets:** list the code repos that declare their own gates, excluding
   paused / skeleton / no-gate repos (e.g. paused projects, skeleton repos, an empty
   CLAUDE.md). A small discovery script that emits them as JSON keeps this repeatable.
2. **Per repo, in an isolated worktree, bounded concurrency 3:**
   - Run the repo's own gates (lint, typecheck, tests, build).
   - `overall:pass` -> record green.
   - `overall:skip` -> record skipped (no gates).
   - `overall:fail`:
     - **--report-only:** record red with the failing gate + diagnosis.
     - **--fix:** classify the failure. Red-lane (needs authz/migration/secrets/deploy) -> record + skip. Otherwise generate a minimal fix-plan (the failing gate + captured diagnosis) and invoke `auto-build <fix-plan> --repo "$REPO" --lane green`.
3. **Aggregate:** consolidate into one report (green / fixed / couldn't-fix / skipped-red-lane / no-gates per repo) plus the set of push-ready branches. Write it to `docs/plans/YYYY-MM-DD-repo-health-sweep-report.md` and (when scheduled) post an exception-only digest to your team chat.

## Invariants

Inherits every `auto-build` invariant: never push/merge/deploy; never edit secrets/authz/migrations autonomously; never trust an agent's self-report (Claude re-runs gates); reversible smoke-data rule for any verification.

- **Concurrency:** default 3 repos at once (bounds cost and time). Configurable.
- **Cost cap:** default ~2M tokens for a full `--fix` sweep. On breach, STOP and report what was done and what remains. `--report-only` is cheap (no Codex/review calls) and is not capped.
- **Isolation:** each repo's work is in its own worktree. If you need to exercise a fix path on an all-green fleet for testing, plant the failure in a scratch worktree, never the main checkout.

## Scheduling (later, v3)

Designed to be schedulable: a weekly `--report-only` (or a scoped `--fix`) routine with exception-only output is the intended scheduled use. Do not wire a cron until you opt in; when you do, use the `schedule` skill and keep the output exception-based.

## Known limitation (v1) — cold checkouts

A gate run from a cold checkout fails on missing dependencies, not code (`uv run pytest` needs `uv sync`; `npm test`/`npm run lint` need `npm ci`). A cold sample can show every repo `fail` from a cold state, with an accurate per-gate breakdown (e.g. one repo's test+lint pass, typecheck fail). So a v1 `--report-only` red means "not green from cold" and should not be read as "the code is broken" until deps are installed. **v2:** run the repo's dependency install first, or classify `env-fail` (deps/toolchain) vs `code-fail`, so a red is trustworthy before `--fix` spends build budget on it.

## Relationship to other skills

- `auto-build`: the engine this loop calls per failing repo.
- a discovery step and a gate-runner: small helpers you provide for listing repos and running each repo's gates.
- your other audit skills: candidates to become scheduled maintainer routines the same way.
