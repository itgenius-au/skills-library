---
name: repo-health-sweep
description: "Green-lane loop that sweeps your code repos, runs each repo's OWN declared gates (test/lint/typecheck), and reports a health map. In --fix mode it hands each fixable failing repo to dev-auto-build to produce a verified push-ready fix branch. Nothing is pushed, merged, or deployed. Triggers on: repo health sweep, health sweep, sweep repos, check all repos, repo gates sweep, fleet health check, are my repos green."
---

# Repo Health Sweep: Green-Lane Fleet Loop

Run every code repo's own gates, produce one health map, and (optionally) auto-fix the fixable failures into push-ready branches. This is a consumer of `dev-auto-build` and a standing green-lane loop.

**Nothing leaves the machine.** Every fix lands on a feature branch in an isolated worktree. The sweep never pushes, merges, or deploys. The user reviews the report and the branches, then approves the batch.

## Modes

- `--report-only` (default, and the mandatory first live run): run each repo's gates and classify. No fixing. Produces the health map so you can see what is red before spending build/review budget.
- `--fix`: for each repo failing its gates, classify the failure; if it is fixable green/yellow-lane, generate a minimal fix-plan and invoke `dev-auto-build` on that repo. Red-lane failures are reported and skipped.

## Setup (once)

The sweep needs a folder that holds your repos. Either pass `--root <dir>` on each run, or copy `templates/repo-health-sweep.config.example.json` to `~/.claude/repo-health-sweep.config.json` and set `root` to that folder (an absolute path). With neither, the discovery script exits 2 and tells you what to set.

Each repo declares its gates on one line in its `.claude/CLAUDE.md`. See [`references/gate-lines.md`](references/gate-lines.md) for the format and the opt-out line.

## Flow

1. **Discover targets:** list the code repos that declare their own gates. A repo opts
   out by putting `Health sweep: skip - <reason>` at the start of a line in its
   `.claude/CLAUDE.md`. Run `bash "${CLAUDE_SKILL_DIR}/scripts/discover-targets.sh"`; add
   `--root <dir>` when the user names a root, otherwise it reads `root` from the config
   file above. Keep the `bash` prefix. Claude Code fills in this skill's folder when the
   skill loads; if you read this file from disk, the path still shows the raw
   `CLAUDE_SKILL_DIR` variable, so replace it with the folder that holds this SKILL.md.
2. **Per repo, in an isolated worktree, bounded concurrency 3:**
   - Run the repo's own gates (lint, typecheck, tests) with
     `bash "${CLAUDE_SKILL_DIR}/scripts/run-gates.sh" <REPO>`, where `<REPO>` is that
     repo's worktree path, pasted literally.
   - `overall:pass` -> record green.
   - `overall:skip` -> record skipped (no gates).
   - `overall:fail`:
     - **--report-only:** record red with the failing gate + diagnosis.
     - **--fix:** classify the failure. Red-lane (needs authz/migration/secrets/deploy) -> record + skip. Otherwise generate a minimal fix-plan (the failing gate + captured diagnosis) and invoke `dev-auto-build <fix-plan> --repo "$REPO" --lane green`.
3. **Aggregate:** consolidate into one report (green / fixed / couldn't-fix / skipped-red-lane / no-gates per repo) plus the set of push-ready branches. Write it to `docs/plans/YYYY-MM-DD-repo-health-sweep-report.md` and (when scheduled) post an exception-only digest to your team chat.

## Invariants

Inherits every `dev-auto-build` invariant: never push/merge/deploy; never edit secrets/authz/migrations autonomously; never trust an agent's self-report (Claude re-runs gates); reversible smoke-data rule for any verification.

- **Concurrency:** default 3 repos at once (bounds cost and time). Configurable.
- **Cost cap:** default ~2M tokens for a full `--fix` sweep. On breach, STOP and report what was done and what remains. `--report-only` is cheap (no Codex/review calls) and is not capped.
- **Isolation:** each repo's work is in its own worktree. If you need to exercise a fix path on an all-green fleet for testing, plant the failure in a scratch worktree, never the main checkout.

## Scheduling (later)

Designed to be schedulable: a weekly `--report-only` (or a scoped `--fix`) routine with exception-only output is the intended scheduled use. Do not wire a scheduler until you opt in; when you do, keep the output exception-based.

## Known limitation: cold checkouts

A gate run from a cold checkout fails on missing dependencies, not code (`uv run pytest` needs `uv sync`; `npm test`/`npm run lint` need `npm ci`). A cold sample can show every repo `fail` from a cold state, with an accurate per-gate breakdown (e.g. one repo's test+lint pass, typecheck fail). So a `--report-only` red means "not green from cold" and should not be read as "the code is broken" until deps are installed. Install each repo's dependencies first, or classify `env-fail` (deps/toolchain) vs `code-fail`, so a red is trustworthy before `--fix` spends build budget on it.

## Relationship to other skills

- `dev-auto-build`: the engine this loop calls per failing repo.
- bundled helpers: `scripts/discover-targets.sh` lists repos (from `--root` or the config file), and `scripts/run-gates.sh <REPO>` runs one repo's declared gates and prints one JSON line. Self-test: `bash scripts/tests/run-tests.sh`.
- gate declaration and opt-out format: [`references/gate-lines.md`](references/gate-lines.md).
- your other audit skills: candidates to become scheduled maintainer routines the same way.
