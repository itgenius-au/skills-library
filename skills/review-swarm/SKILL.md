---
name: review-swarm
description: "Run a rigorous review swarm - four models (OpenAI Codex + Google Gemini + z.ai GLM + a deep-reasoning Claude Fable pass) over the same subject in one parallel pass, then synthesize one deduplicated, severity-ranked, consensus-tagged findings list. Three are INDEPENDENT external models; the fourth (Fable) is a Claude-family model run as an isolated read-only process. The primary agent orchestrates only; it is NOT one of the reviewers (no self-grading). Use for a high-stakes review of code, a decision, a plan, or a document, and as the review gate inside dev-quick-build / dev-auto-build. Add quick for a faster panel (about 10 minutes). Triggers on: review swarm, review-swarm, swarm review, review with swarm, quad review, quad-review, quad check, quad-check this, four-model review, 4-model review, house review, panel review, Codex Gemini GLM Fable, review with all four, quick swarm, quick review swarm, fast swarm, quick quad review."
argument-hint: "[quick] [mode: code|decision|plan|doc|build] [target: file path, branch, dir, or description]"
---

# Review Swarm - Codex + Gemini + GLM + Fable, one pass, synthesized

Runs **four models** over the same subject and returns **one** consolidated findings list. The four reviewers are:

- **Codex** (OpenAI, external, via the `review-with-codex` skill)
- **Gemini** (Google, external, via the `review-with-gemini` skill)
- **GLM** (z.ai, external, via the `review-with-glm` skill)
- **Fable** (a deep-reasoning Claude pass, via the `review-with-claude` skill) - a Claude-family leg, run as an isolated read-only `claude -p` process with no shell.

**The primary agent is the orchestrator, not a reviewer.** It assembles the subject, fans the four models out in parallel, then synthesizes - it does NOT add its own review as a fifth opinion. Keeping the orchestrator out of the reviewer set is deliberate: a model should not grade its own or its sibling's output.

> **Independence is not uniform across the four.** Codex, Gemini, and GLM are outside models with no stake in the work. Fable is Anthropic-family - a genuinely separate model run in an isolated process, so it is an independent opinion, but the same vendor/family as a Claude orchestrator. Weight a Fable-only finding accordingly (see the consensus tags): three independent external models remain the backbone of the panel, and Fable is a strong fourth deep-reasoning vote, not a replacement for an outside model.

> **This is the multi-model review gate** that `dev-quick-build` and `dev-auto-build` call for their review phase, rather than hand-rolling the fan-out. If your project has no such build workflow, invoke this skill directly whenever a change, plan, or decision needs a high-confidence panel before you act on it.

## Reference files (read the file when its row applies)

This file holds the modes, the shared reviewer prompt, the rules every leg obeys, the post-panel check, the must-fix rule and quick mode. The two dispatch paths, the redaction rules and the edge cases live in `references/` beside it. Open a file when its row applies, and open it BEFORE the step it names: a row is an instruction, not a link to skim. Text past the first screens of this file is not kept after a compaction: after one, re-read Step 5 (the must-fix rule), the post-panel check and Quick mode in this file before you adopt findings.

| When | Read now |
|---|---|
| Step 3, the pre-dispatch check says UNBOUND, so you dispatch subagent legs | `references/subagent-legs.md`, before you dispatch the first leg |
| Step 3, the pre-dispatch check says BOUND, a subagent leg locked on its snapshot, or a leg's subagent dispatch failed outright | `references/orchestrator-run-legs.md`, before you launch the first leg |
| Step 3, any reachable branch history holds a live credential, or the subject touches customer data, bank details or a personal document | `references/redaction-and-privacy.md`, before you build any snapshot or packet |
| Step 3, before you write any leg prompt (the host-hook line every leg gets, Gemini's `::GEMINI-MODEL::` marker); before a quick-mode decision or doc review (the Codex `TIME LIMIT` line, `--timeout 1800` for a long document); or a leg returned early or empty, timed out, printed a partial GLM report, failed to authenticate, or the host is small | `references/leg-troubleshooting.md` |
| Step 4 or 5: a GLM report claims command output, a finding rests on vendor documentation, a test-leak finding appears, or you write the report | `references/synthesis.md` |
| Quick mode with a large packet, a Codex leg on a large repo, or a session that cannot run background calls | `references/quick-mode-details.md`, before you launch the legs |
| You are unsure whether to run the swarm at all or whether `review-debate` fits better, it is the first use on this machine, a key-based leg fails to authenticate, you need the model-pins note, or you want example invocations | `references/setup-and-examples.md` |

## The verification preamble (prepended to every model's prompt)

```
You are one leg of a review swarm. Treat documentation, code comments, plan files, and any prior
agent's claims as UNVERIFIED HYPOTHESES, not facts. Base every finding on evidence you can point to:
a file:line reference, the output of a command you ran, or the exact text of the material supplied.
If you cannot verify a claim, say so explicitly rather than guessing. When an area is clean, report an
evidenced per-area verdict ("checked X, Y, Z - no issue because ..."), not a bare "no findings". Do NOT
defer to the other reviewers; report what YOU find.
```

## Modes

| Mode | Subject | How context reaches the models |
|---|---|---|
| `code` | Uncommitted diff, a file, or a branch | Codex, Gemini & Fable read the repo themselves; the GLM leg inlines the diff (GLM can't explore). Default: uncommitted changes. |
| `build` | Branch vs main (`merge-base...HEAD`) | Same as code, over the isolated feature diff. |
| `plan` | A plan/spec file | Read the file; supply its text to all four, plus the current code it touches. |
| `decision` | A claim/choice to stress-test | Supply the decision text + any relevant context to all four. |
| `doc` | Any document (contract, filing, tax position) | Inline the full document text to all four. |

## Workflow

### Step 1 - Determine mode, subject, and project dir
Parse the request. If unclear, default to `code` on uncommitted changes and say so. If the first argument is `quick`, or the request asks for a quick or fast swarm, apply "Quick mode" (under "Scale to the subject") on top of the mode. A "quick" inside a path or the subject text does not count. For `code`/`build`, identify the repo dir and the diff range (`build` = `git merge-base origin/main HEAD`...HEAD, so unrelated in-flight work does not pollute the review).

### Step 2 - Assemble the review packet (once)
Build ONE shared packet the four legs will each review, so all models see the same thing:
- **code / build**: the repo dir + the diff range. Codex re-derives the diff itself. Fable gets it from its wrapper via `--diff-range <RANGE>` (it has no shell). Gemini cannot run git (its policy is read-only), so the orchestrator runs a plain `git diff <RANGE> > <SCRATCH>/gemini-diff.txt` in the repo/snapshot (placeholders are defined in "Invocation form" below) and passes it to Gemini with `--stdin-file`. GLM gets the diff inlined in its prompt file. Do not paste a huge diff into shell args - let each self-exploring leg gather it.
- **plan / decision / doc**: read the file(s) / capture the decision text, and inline the actual content. These are usually small enough to embed.
- **Fable effort (decide once, pass to the Fable leg)**: `xhigh` when the subject touches authorization, a migration, money/billing, or security, or when the user asks for maximum depth (the `review-with-claude` effort gate; when unsure, `xhigh`), else the wrapper's `high` default. For code/build, decide from `git diff --name-only <range>` plus the stated ask. Fable at `xhigh` is usually the slowest leg, so do not trip the gate without a reason. In quick mode, Fable always runs at `high` (see "Quick mode").
- **Codex effort: `xhigh`** (the `codex-exec.sh` default) for a full panel and quick mode. The one exception is a one-pass review of a small change by a build skill (for example `dev-quick-build`), which may run Codex alone at `high`.
- **The ask and non-goals (required).** Capture the owner's ask VERBATIM (a plan's "Ask", a spec's goal, or the user's request) and the Non-goals list if one exists. Every leg gets them. A reviewer that cannot see the ask cannot tell "a guard the ask left out on purpose" from "a missing guard", and it will ask for both - plans grow 2-4x over a few review rounds that way. If no written ask exists, write the subject's purpose in one line and mark it inferred.

Build the shared reviewer prompt = the **verification preamble** + a mode line + the structured-output ask:

```
<verification preamble>

THE ASK: <the owner's ask, verbatim>
NON-GOALS: <the non-goals, verbatim, or "none stated">
Judge everything against THE ASK. The subject only has to do what THE ASK says, safely.

<mode line - e.g. for code: "Review the changes in this repo (diff range: <RANGE>). Focus on what
breaks under realistic inputs for THE ASK: correctness, edge cases, security.">

<caller focus, if any: if the invoking skill or user supplied specific questions, paste them here
VERBATIM as "Specifically answer: ...". Omit this block if none.>

For each issue, report:
- Finding: <one line>
- Type: defect | enhancement | simplify
- Severity: critical | high | medium | low
- Failure case: <the realistic input or event that triggers it, and what goes wrong for the user>
- Evidence: file:line, a command's output, or the exact supplied text
- Confidence: 1-10
- Action: <what to do>

**Type is scope discipline, not politeness.** A `defect` is a correctness, security, breakage,
or missing-test problem in the subject AS SCOPED BY THE ASK, with a realistic failure case. An
`enhancement` is a new feature, a larger refactor, a speculative abstraction, or hardening BEYOND
THE ASK - it is ADVISORY ONLY: the caller logs it as a follow-up and does NOT build it without the
owner's go-ahead. A problem that needs an unrealistic input, or matters only outside THE ASK or
inside a NON-GOAL, is an `enhancement`, not a defect. When unsure, tag `enhancement`. Do not inflate
scope: prefer the simplest correct fix, and never propose new surface area (a feature, endpoint,
flag, dependency, or abstraction) as something to just build. In Action, prefer the cheapest fix
that removes the failure case.

**Also report what to REMOVE (`simplify`).** Name any guard, refusal, confirmation step, option,
mode, layer, or config in the subject that THE ASK does not need, or that blocks the normal path for
the intended user. Do not ask for a refuse-by-default guard, a typed confirmation, or a "stop until
a named person confirms" step unless the action is irreversible and destructive, or moves money with
no human in the loop. Where a human approves the action, the human is the guard; an UNKNOWN answer
is a warning to show, not a reason to refuse. (Deploy and CI gates are different: they still abort.)

**Also hunt these two "clean on a skim" failure shapes, and report each as a defect** (the
anti-padding instruction governs cosmetic noise, NOT this scrutiny):
- **Unreachable / orphaned code** - a route, handler, hook, or export that no real call path
  reaches (a registered endpoint no client or webhook calls; a defined-but-never-enqueued hook).
- **Fake-green tests** - a test that passes without exercising the production path: it mocks or
  re-implements the code under test instead of calling it, or asserts nothing that would fail if
  the behaviour broke.

**Bug-class sibling sweep.** When you confirm a defect, look for its siblings - the create path
against the update path, an in-memory value against its persisted/cached copy, one route against an
alternate route to the same data - and report each instance as its own finding. One instance means
assume siblings exist.

Prioritise; at most 10 findings, ranked by severity. Most good reviews of a small subject have
fewer than five: do not fill the list. A clean result is a valid
outcome - report it as an evidenced per-area verdict, not a bare "no findings".
```

### Invocation form (read before dispatching any leg)

Some agent harnesses refuse a Bash command that contains a `$(...)`/backtick substitution, a variable assigned from command output, `export VAR=...`, a variable used as the command name, a heredoc, a `for`/`while` loop, or `bash -c "..."`. Claude Code does this in a git-worktree session, and the refusal cannot be turned off. A literal absolute path with literal arguments and a plain `>` redirect passes.

**The canonical form for every wrapper call in this skill:**
1. Write the prompt with your editor/Write tool to a file in a scratch directory. Do not build the prompt in the shell.
2. Run the wrapper as ONE plain command, every path a literal absolute path (never a shell variable), for example:
   `<REVIEW_SKILLS>/review-with-codex/codex-exec.sh --mode review --dir <PROJECT_DIR> --prompt-file <SCRATCH>/codex-prompt.txt > <SCRATCH>/codex-out.txt 2>&1`
3. Read `<SCRATCH>/codex-out.txt`. A Codex output can pass 256 KB (it logs every command it ran), and some file readers refuse a file that size. Then `grep -n '^MODEL:'` to find the final report and read from that line with `sed -n '<line>,$p'`.

Placeholders used throughout this skill: `<REVIEW_SKILLS>` = the parent of this skill's "Base directory for this skill" path (the folder holding the sibling `review-with-*` skills), pasted literally (never a shell variable). Each wrapper lives in its own sibling skill: `<REVIEW_SKILLS>/review-with-codex/codex-exec.sh`, `<REVIEW_SKILLS>/review-with-gemini/gemini-exec.sh`, `<REVIEW_SKILLS>/review-with-glm/glm-exec.sh`, `<REVIEW_SKILLS>/review-with-claude/fable-exec.sh`. `<SCRATCH>` = your scratch directory, pasted literally; `<PROJECT_DIR>` / `<snapshot>` = the absolute path of the repo or review snapshot under review; `<RANGE>` = the diff range.

Give each leg's prompt file and output file different base names, never names that differ only by case. macOS file names are case-insensitive, so `d1-gemini.txt` and `D1-gemini.txt` are the same file: the `>` redirect to the output empties the prompt before the wrapper reads it, and the leg fails with "no PROMPT given" or "--prompt-file is empty". Use suffixes such as `-prompt.txt` and `-out.txt`.

`--prompt-file` and `-- PROMPT` are alternatives (both given: exit 2); a missing or empty prompt file exits 2; a prompt over ~131000 bytes exits 2 (keep large input in files the model reads, or `--stdin-file` for Gemini, which is read-only and cannot run git itself).

When the skills path contains a space, a harness may refuse a quoted wrapper path as "a command whose name is computed at runtime". Call each wrapper through bash instead, so the command name is the literal `bash`:
`bash "<REVIEW_SKILLS>/review-with-codex/codex-exec.sh" --mode review --dir <PROJECT_DIR> --prompt-file <SCRATCH>/codex-prompt.txt > <SCRATCH>/codex-out.txt 2>&1`

### Step 3 - Fan out four legs in parallel

**Pre-dispatch check: is the orchestrator itself bound to a worktree?** Check this BEFORE you dispatch any leg:

```bash
git rev-parse --git-dir
git rev-parse --git-common-dir
```

Run them as two separate plain commands (a combined `[ "$(...)" != "$(...)" ]` test is itself refused in a bound session). Different outputs mean BOUND; the same output means UNBOUND. Also treat the session as BOUND when the harness says it "is isolated in the worktree" (it entered one via its worktree-entering tool, such as Claude Code's `EnterWorktree`). When BOUND, **do NOT dispatch subagent legs.** A subagent inherits the pinned cwd, so it either locks (see "If a leg cannot bind to its snapshot" below) or silently reads the build worktree instead of its snapshot. Go straight to the orchestrator-run path: one background Bash call per leg, each at its own snapshot by absolute path. Key this on the detected binding state, not on the surface name. When UNBOUND, dispatch subagents.

**Two paths, chosen by the check above.** UNBOUND: dispatch subagent legs, and read `references/subagent-legs.md` now, before you dispatch the first leg. BOUND: run the legs from the orchestrator, and read `references/orchestrator-run-legs.md` now, before you launch the first leg. Both paths share every rule below: the model report, the freeze, the leg-prompt rules, the snapshots, the post-panel check and the redaction rules. Before you write any leg prompt, read `references/leg-troubleshooting.md` now: it holds the host-hook line that goes into every leg prompt and Gemini's `::GEMINI-MODEL::` marker, which you record instead of the leg's own `MODEL:` line.

**Every leg reports the exact model it ran.** At the top of its returned report the subagent states the precise model ID its CLI used this run - the pin (or default) the sibling skill applied, read back from the run, e.g. `MODEL: <exact model id>` (the Fable leg adds its effort, for example `MODEL: <exact model id> (effort: high)`, so the synthesis shows whether the gate tripped). Do NOT hardcode versions in this skill (they rot, see the model-pins note in `references/setup-and-examples.md`); the synthesis names whatever each leg reports. If a leg cannot read its model back, it reports `MODEL: unknown`. The GLM leg cannot read its model back, and its self-reported id is unreliable (it can name itself as a different model than the wrapper pinned). Record the wrapper's pin for GLM, not the model's own claim.

**Pre-send check for every inlined prompt (GLM especially).** Before sending, search the assembled prompt for phrases that promise content ("included below", "excerpt attached", "see the diff below", "full text follows") and confirm that the promised text is actually there, and not empty or truncated. A reviewer that cannot read the repo does not flag a missing excerpt. It writes findings "consistent with the prompt's descriptions" instead, with plausible but invented file:line citations. If content is missing, fix the prompt and re-send. Treat any finding from a leg whose prompt failed this check as unverified. `scripts/glm_packet.py` (see `references/orchestrator-run-legs.md`) automates this check.

**Freeze the subject while any leg runs.** Do not edit the files under review until every leg has returned. Fold early findings in only after the last leg lands. Also tell each leg, in its prompt: if the tree changes in a way the leg did not cause, REPORT it and never revert it (no `git checkout --`, `git reset`, or `git stash`). A leg cannot tell the orchestrator's edits from its CLI's side effects. Inside a review swarm, the sibling skills' "`git status` and discard unsolicited edits" cleanup (for example `review-with-gemini`) is the orchestrator's job, done once after the last leg lands, not a leg's. A leg in a write-capable sandbox mode can mistake the orchestrator's mid-panel edits for its own CLI's side effects and revert them, and the fixes then have to be re-applied before merge.

**Leg scratch files go outside the repo.** Tell each leg, in its prompt: any file it creates (a staged prompt, a runner script, captured output) goes to a unique path OUTSIDE the tree under review (`mktemp /tmp/<leg>-XXXXXX`, or a private dir under `~` on a shared host), never the repo or worktree. A project's auto-commit hook commits whatever it finds in the tree: a leg that stages its prompt or a runner script in a worktree (to get past a harness guard, say) has them swept into a `wip` commit on the feature branch mid-review. After the last leg lands, `git status` must show only the orchestrator's own changes. A leg or probe agent that runs tests in its own copy also needs its OWN virtualenv, never a symlink to the build worktree's `.venv`: `uv run` (or an editable install) in a copy can rewrite the shared editable-install `.pth` to the copy's `src`.

**Legs probe only through the project's test harness.** Tell each leg, in its prompt: to exercise behaviour, run the project's own test runner so its test fixtures load (for a Python repo, `pytest`, which loads the repo's `conftest.py`). Never import the application or its config module directly in a scratch script. An app's real config loader can read production secrets at import time, and some also write key files to disk. A read-only review must never touch production secrets.

**Legs never run a project's own scripts, outside the test harness.** Tell each leg, in its prompt: never run, exec or import a project script, generator, build or deploy file, or a reference file the review names; read it instead, and write nothing anywhere except its own temp files. The snapshot protects the repo, not files OUTSIDE it: a plan-review leg that runs a generator script "to compare outputs" can have that script rewrite its input file somewhere else on the machine. A review must never be the reason work has to be recovered. The Fable wrapper enforces this with a hard limit: the leg has no shell (`--tools Read,Grep,Glob`). The other legs still get the prompt rule.

**Give the legs a snapshot, never the build worktree.** A prose "READ-ONLY" does not stop an agent that has a shell. Agents told to stay read-only have been seen to write anyway: checking out another branch in the build worktree (HEAD detached, branch-only files gone from disk, the next commit landing on the detached HEAD), implementing the change and committing, pushing or opening a PR, or trying to reach a production system. A subagent starts in YOUR working directory, so a repo path in its prompt does not move it. So:

1. Checkpoint-commit the subject first (a plan or doc too). Create one detached snapshot of that commit PER LEG, as worktrees of the same repo: `git worktree add --detach <repo>/.claude/worktrees/review-<slug>-<leg> <checkpoint-sha>`. One per leg, so a misbehaving leg cannot change what the other legs are reading. In a worktree-bound session, run it plainly from your own worktree: `git -C <the repo's main checkout> worktree add ...` may be refused as a redirect to the shared checkout. `<REVIEW_SKILLS>/review-swarm/scripts/snapshots.sh` does this and records the baseline (see `references/orchestrator-run-legs.md`).
2. Tell each leg that its FIRST action is to enter its snapshot with the harness's worktree-entering tool (Claude Code: `EnterWorktree(path=<its snapshot>)`). That rebinds that agent alone to the snapshot, so a bare `git checkout`, `reset` or `commit` lands there, not on your branch. If the leg has no such tool, it runs every command by absolute snapshot path (`git -C <snapshot> ...`). Pass the snapshot as the repo dir to the CLI wrappers. It shares the object store, so the diff range resolves there. Remove it after the panel (`git worktree remove --force <snapshot>`). Do NOT use an agent tool's "isolated worktree" option for this: a fresh one branches from `origin/<default-branch>`, so the legs would review main, not your diff. Before launch, record a baseline for the post-panel check: the panel start time and `git ls-remote --heads origin > <scratch>/refs-before.txt`.
3. When an agent only reads (no CLI to run), dispatch a subagent type whose tool list has no Bash, Edit or Write. A tool it does not have is a real limit; a sentence in its prompt is not.
4. Tell each leg, in its prompt: never commit, push, open or edit a PR, merge, or touch a production system (database, deploy, secret, live API write). If it thinks a fix is needed, it REPORTS the fix.
5-7. **Redaction rules.** (5) A live key in any branch's history reaches the legs' providers. (6) Personal and customer data stays out of non-Anthropic legs: names, emails and bank details stay out of the whole packet, and Codex and Gemini get a redacted export, not a git snapshot, when a name is in the subject's own diff or files. (7) `doc` mode on a personal or financial document needs a redacted copy. When any reachable branch history holds a live credential, or the subject touches customer data, bank details or a personal document, read `references/redaction-and-privacy.md` now, before you build any snapshot or packet.

**If a leg cannot bind to its snapshot.** When the pre-dispatch check says BOUND, an UNBOUND session's leg locks anyway, or a leg's subagent dispatch fails outright, run the legs from the orchestrator, one background Bash call per leg, each at its own snapshot. Read `references/orchestrator-run-legs.md` now, before you launch any leg: it holds the per-leg commands, the helper scripts (`snapshots.sh`, `glm_packet.py`, `postpanel.sh`), the empty-output and heap rules, and the degraded-host dispatch fallback (a leg's subagent dispatch fails outright).

**Post-panel check (mandatory, after the last leg lands, before Step 4 and before you remove the snapshots).** In the build worktree:

```bash
git branch --show-current                        # still your branch (empty = detached HEAD)
git reflog -5                                    # no checkout, reset or commit you did not make
git status --short                               # only your own changes
git -C <each snapshot> reflog -5                 # a commit or checkout here is a write attempt
git ls-remote --heads origin | diff <scratch>/refs-before.txt -   # new or moved remote branches
gh pr list --author @me --state all --limit 5    # no PR you did not open (this repo)
gh search prs --author @me --created ">=<panel-start>"   # no PR you did not open (any repo)
```
In a worktree-bound session, run this check as `references/orchestrator-run-legs.md` says (`postpanel.sh`, or one command per line, with each snapshot's reflog read as a file).

Another session can move a remote branch during the panel too; attribute each ref change before you call it clean.

Treat any unexpected commit, push, branch or PR as **out-of-process work**: stop, record it, and review it like any other change before you decide to keep it. Never merge it on an agent's word.

**Remove the snapshots before you run the repo's own gates.** The snapshots sit inside the repo under review (`.claude/worktrees/review-<slug>-<leg>`). A gate that scans the whole tree, such as a scrub check or a validator test, then also scans the snapshots and fails on their fixture files. After the post-panel check is clean, run `git worktree remove --force <snapshot>` for each one, then run the gates (`snapshots.sh` recreates them at the next checkpoint for the next cycle).

### Step 4 - Normalise and cross-check
For each returned finding: tag its source model, and **cross-check every `file:line` reference from the models against the real files** before trusting it (models occasionally hallucinate paths). Drop or flag references that do not exist.

Three checks belong here when they apply: a leg that cannot run commands reports command output, a finding rests on vendor or API documentation, or a finding says tests leak state. Read `references/synthesis.md` now, before you adopt or reject such a finding.

### Step 5 - Synthesize (the orchestrator's only judgement call)
Merge the four lists into one. **Deduplicate**: the same issue raised by more than one model becomes a single row, attributed to all who flagged it, with a **consensus tag** (out of the number that ran):
- **4/4** all four flagged it - highest confidence, fix it.
- **3/4** three flagged it - strong signal.
- **2/4** two flagged it - real; verify.
- **1/4** one flagged it - real but unconfirmed; verify before acting. Extra caution when the sole flagger is the **GLM leg** (it saw only the inlined code) or the **Fable leg** (Claude-family, so a Fable-only finding that echoes the orchestrator's instinct is weaker independent signal than one from an outside model).

When a model was `unavailable`, the consensus denominator is the number that actually RAN, and the header names the missing model - e.g. `3/3 (Codex, Gemini, Fable; GLM unavailable)`. Never print `3/4` for a degraded panel as if a fourth model checked it and stayed silent.

Rank by severity, then by consensus. **Name the exact model each leg ran** in the header - fill each `<model>` slot from the `MODEL:` line that leg reported (Step 3), not from memory. A leg that did not run shows its status only (e.g. `Codex (unavailable)`); a leg that could not read its model back shows `unknown`. Present:

**The must-fix rule.** A defect holds the gate ONLY when it has a realistic failure case AND it is **critical or high**, or it is **medium and 2 or more legs flagged it**. On a single-model review, only critical or high can hold the gate. Every other defect - low, or a medium from one leg only - is **advisory**: list it in one line, do not build it, and do not loop on it. A finding outside THE ASK or inside a NON-GOAL is an enhancement whatever its tag. Why: without this rule the orchestrator fixes almost every finding, including low single-model ones, and builds come out over-restricted and 2-4x the size of the ask.

**Keep the three types separate in the output.** Carry each finding's `Type` through to the table, and split the actionable lists: **Must-fix defects** hold the gate; **Advisory** items (enhancements and below-the-bar defects) do not - they are logged, not built, and the caller does not fold them into a "fix" without the owner's go-ahead. **Simplify** items are applied by the caller when the removed thing is outside THE ASK and the ask's own tests still pass; a simplify item that would remove a guard the ask names goes to the owner as a decision. A panel that returns no must-fix defect is a CLEAN gate result.

**Report format.** Read `references/synthesis.md` now, before you present: it holds the exact report template (header, findings table, must-fix, simplify, advisory, agreed clean, disagreements).

### Step 6 - Follow up

**A regression test added in a fix round must fail on the pre-fix code.** Whoever runs the fix round (the caller inside a gate loop, or you in standalone use) checks this before calling a finding fixed: run the new test against a complete pre-fix tree (`git worktree add --detach <scratch> <pre-fix sha>`, with the new test copied in), or swap the old function in, in memory. A single copied file on `PYTHONPATH` can still import the fixed code from the checkout or an editable install, so for Python confirm the imported module's `__file__` is the pre-fix copy. Expect red, and the failure must reproduce the original defect (the wrong result, or the crash the defect caused), not an import error or a missing name that only the new test introduced: that proves nothing. A test that also passes on the old code proves nothing either.

**Standalone / interactive use only.** Offer: fix the must-fix items; run `/review-debate` on a specific disagreement; or a deeper single-model dig on one area.

**When a build or plan workflow invoked you as a review GATE inside a loop** (`dev-writing-plans`, `dev-auto-build`, `dev-quick-build`): do NOT print this menu and do NOT ask the user which option to take. Return the synthesized findings table to the CALLER and stop there. The caller's own bounded loop folds the confirmed findings back in and re-runs you, until its exit condition (consensus clean) or its bound (cycle cap / irreconcilable dispute). Handing the user a menu mid-loop is what turns an autonomous "review until clean" into a stop-and-ask - do not do it. Two things, and only these two, return control to the user from inside the gate: a genuine product / design / trust decision, and an ENHANCEMENT whose adoption would add new surface area beyond the ask/plan (a feature, endpoint, flag, dependency, or abstraction). Both are surfaced as decisions, never as a "pick a follow-up" prompt, and never folded silently into a "fix". Advisory enhancements that do NOT expand scope are just logged as follow-ups; they do not stop the loop and are not built.

## Graceful degradation (never silently drop a model)

| Situation | Behaviour |
|---|---|
| One model unavailable (auth, quota, wedge, timeout) | Proceed with the rest; mark it `unavailable` in the header and say which. A 3/4 panel is still a review swarm with one leg down - do not hide it. |
| GLM unfunded (`1113`) | Report "GLM: unfunded - fund your z.ai account"; continue with the rest. Never treat the billing error as a finding. |
| Fable not logged in (`::FABLE-NOAUTH::`) | Report "Fable: not logged in - sign in to Claude Code on this machine"; continue with the rest. Not a finding. |
| Codex emits nothing / a streaming leg wedges | Treat as a wedged handshake, not "clean" - relaunch that leg attached once, else mark unavailable. **Does NOT apply to Fable**: `claude -p` text mode emits nothing until completion by design, so judge the Fable leg by its wrapper's rc / `::FABLE-TIMEOUT::`, never by silence. |
| A leg's SUBAGENT dispatch fails (e.g. Claude usage limit, HTTP 429) while the orchestrator still runs | Not a down leg yet: run that leg's wrapper directly from the orchestrator (`references/orchestrator-run-legs.md`, "Degraded-host dispatch fallback"). Mark it `unavailable` only if the direct run also fails. |
| All four unavailable | Do NOT fake a review. Report that no model ran and why; suggest fixing the failing prerequisite. |
| Empty diff (code mode) | Say so; offer a branch diff, a specific file, or a different mode. |
| Waiting for legs on a shared machine | Wait on the background task ids and output files YOU launched, with a timeout. Never wait by process name (`pgrep`): it can match another session's review processes and never finish. |

## Scale to the subject
Match the panel to the diff - this is a rule, not a suggestion, because running four heavy CLIs on a one-line change is the overhead the loop is blamed for, not the safety. A **trivial change** (a lint autofix, a one-line copy/comment/config tweak, a diff under ~30 changed lines with no logic change) gets ONE model - a single `review-with-*` skill - not the four-CLI panel. Reserve the **full panel** for substantive logic changes, wide-reaching or cross-cutting diffs, and every money-path / authz / migration change. Three independent external models plus Fable is the standard for a real review, not a ceiling to always max out - and a copy tweak is not a real review subject. Outside a build skill's one-pass review of a small change (Step 2), scale down by the number of legs and the size of the subject, not by lowering the Codex leg's effort below `xhigh`.

### Quick mode (`/review-swarm quick <mode> <target>`)
A fast panel, called by the user or by `dev-quick-build`: the same four models, sized to come back in about 10 minutes. A single leg usually takes about 6 to 10 minutes, but a full panel often takes 20 minutes or more. The extra time comes from Fable at `xhigh`, relaunches, and the slow tail, not from Codex effort. Quick mode removes those:
- **Same four legs, same shared prompt, one round.** Launch all four together (Step 3). There is no re-review round: after fixes, the user asks for a new run (a caller follows its own rule).
- **Codex stays at `xhigh`** (Step 2). **Fable runs at `high`**: skip the Step 2 effort gate.
- **Every wrapper call gets `--timeout 570`, and GLM also gets `--retries 0`.** 570 s is 30 s under the Bash tool's 10-minute cap, so the wrapper stops the CLI itself. GLM's timeout is per request and it retries a timeout once by default, so without `--retries 0` it can run about 19 minutes. Put the flags in each leg's prompt (subagent legs) or in each command (orchestrator-run legs).
- **One attempt per leg.** Synthesize when all four have returned; each returns within about 10 minutes of its wrapper start. A leg that timed out or failed is `unavailable`. Quick mode overrides every other wait or retry rule in this skill: the force-background wait, the re-run-once rules (empty output, heap OOM, Fable with no `MODEL:` line), and the Graceful degradation relaunch. A nudge that only makes a leg wait for its own running CLI is fine; never start a leg's CLI a second time. Head the output `## Review Swarm (quick) - <mode>: <subject>`.

Quick mode with a large inlined packet, a Codex leg on a large repo, a session that cannot run background calls, or a decision or doc review (the Codex `TIME LIMIT` line): read `references/quick-mode-details.md` and `references/leg-troubleshooting.md` now, before you launch the legs.

- **Not for risky subjects.** When the subject touches authz, a migration, secrets, money or billing, security, or a write or delete of production or customer data, or you are unsure, say so and run the full panel.
- **Other rules still apply.** A trivial change still gets one model (above), which is faster still. On a host too small for four legs at once, say that quick mode cannot hold 10 minutes, then run the legs two at a time.
- **Callers.** The user, and `dev-quick-build` for its plan review (below). `dev-auto-build` keeps the full panel.

### Quick-build review (called from `dev-quick-build`)
A quick build is one small feature, so its review is sized for speed:
- **Quick mode (above), one round, for every quick build.** Give it the same shared prompt as a full panel (THE ASK, NON-GOALS, the finding fields, the must-fix rule, `simplify`) plus the caller's questions. Quick mode's "Not for risky subjects" rule does not apply here: a quick build that touches authz, a migration, secrets, or a production or customer data write (money movement included) gets the same four-model panel.
- **If every leg fails,** proceed without a model review and say so in the plan document; the build's own later code review still runs.
- **No re-review round** unless a fix changed the approach; then re-run the same review once.

**Four models, one synthesized verdict, consensus-tagged: three independent external models plus a deep-reasoning Fable leg. The orchestrator never grades its own homework.**
