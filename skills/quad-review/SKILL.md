---
name: quad-review
description: "Run a rigorous quad review - four models (OpenAI Codex + Google Gemini + z.ai GLM + a deep-reasoning Claude pass) over the same subject in one parallel pass, then synthesize one deduplicated, severity-ranked, consensus-tagged findings list. Three are INDEPENDENT external models; the fourth (Fable) is a Claude-family model run isolated and read-only. The primary agent orchestrates only; it is NOT one of the reviewers (no self-grading). Use for a high-stakes review of code, a decision, a plan, or a document, and as the review gate inside dev-quick-build / dev-auto-build style workflows. Triggers on: quad review, quad-review, quad check, quad-check this, four-model review, 4-model review, house review, panel review, Codex Gemini GLM Fable, review with all four."
argument-hint: "[mode: code|decision|plan|doc|build] [target: file path, branch, dir, or description]"
---

# Quad Review - Codex + Gemini + GLM + Fable, one pass, synthesized

Runs **four models** over the same subject and returns **one** consolidated findings list. The four
reviewers are:

- **Codex** (OpenAI, external, via the `codex-review` skill)
- **Gemini** (Google, external, via the `gemini-review` skill)
- **GLM** (z.ai, external, via the `zai-review` skill)
- **Fable** (a deep-reasoning Claude pass, via the `fable-review` skill) - run isolated and read-only
  through headless `claude -p`, so it behaves like a fourth model even though it shares a vendor with
  the orchestrator.

**The primary agent is the orchestrator, not a reviewer.** It assembles the subject, fans the four
models out in parallel, then synthesizes - it does NOT add its own review as a fifth opinion. Keeping
the orchestrator out of the reviewer set is deliberate: a model should not grade its own or its
sibling's output.

> **Independence is not uniform across the four.** Codex, Gemini, and GLM are outside models with no
> stake in the work. Fable is Claude-family: a genuinely separate, isolated process, so it is an
> independent opinion, but the same vendor/family as a Claude orchestrator. Weight a Fable-only finding
> accordingly (see the consensus tags): three independent external models remain the backbone of the
> panel, and Fable is a strong fourth deep-reasoning vote, not a replacement for an outside model.

> **This is the multi-model review gate that dev-quick-build / dev-auto-build style workflows should call for**
> their review phase, rather than hand-rolling the fan-out themselves. If your project has no
> `dev-quick-build` / `dev-auto-build` equivalent, invoke this skill directly whenever a change, plan,
> or decision needs a high-confidence panel before you act on it.

## How it differs from `ai-debate` (pick the right one)

| | `quad-review` (this) | `ai-debate` |
|---|---|---|
| Reviewers | Codex + Gemini + GLM + **Fable** (4) | **Primary agent** + Gemini + Codex |
| Rounds | **One** (review -> synthesize) | **Three** (review -> challenge -> synthesize) |
| Primary agent | Orchestrator only | A reviewer + moderator |
| Speed / cost | Faster, ~4 parallel calls | Deeper, up to ~4 calls + debate |
| Use when | Fast high-confidence panel over a subject | The finding is disputed and needs models to argue it out |

Reach for `ai-debate` when a `quad-review` surfaces a genuine disagreement worth litigating. Reach
for a single `codex-review` / `gemini-review` / `zai-review` / `fable-review` for a quick one-model
sanity check.

## When to use

- **Pre-merge / pre-ship code review** of a feature diff or branch.
- **A decision** with real downside (architecture, trust model, money, legal/tax).
- **A plan** before building against it.
- **A document** you are about to act on (contract, filing, tax position, runbook).
- The **review gate** inside a dev-quick-build style flow (plan review) or a dev-auto-build style flow
  (diff review).

**When NOT to use**: a small/obvious change, a style pass, or anything where one model is plenty - use
a single `*-review` skill. Speed-critical work where one opinion suffices.

## Prerequisites (each model's own skill owns the details)

- `codex-review` - Codex CLI signed into the reviewer's own ChatGPT account (`codex login`).
- `gemini-review` - Gemini CLI + a `GEMINI_API_KEY` in your env or secret manager.
- `zai-review` - a z.ai key (`ZAI_API_KEY`) in your env or secret manager + a funded GLM Coding Plan.
- `fable-review` - the machine's own Claude Code login (no key/secret). Fable runs via headless
  `claude -p`.

Keys resolve from your own env or secret manager (each sibling skill documents its own). **Never**
point at someone else's project or key. Model pins live in the four sibling skills - do NOT restate
versions here (they rot); match whatever those skills pin.

## The verification preamble (prepended to every model's prompt)

```
You are one leg of a quad review. Treat documentation, code comments, plan files, and any prior
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
Parse the request. If unclear, default to `code` on uncommitted changes and say so. For `code`/`build`,
identify the repo dir and the diff range (`build` = `git merge-base origin/main HEAD`...HEAD, so
unrelated in-flight work does not pollute the review).

### Step 2 - Assemble the review packet (once)
Build ONE shared packet the four legs will each review, so all models see the same thing:
- **code / build**: the repo dir + the diff range. (Codex/Gemini/Fable re-derive the diff; the GLM leg
  will inline it.) Do not paste a huge diff into this file's shell args - let each self-exploring leg
  gather it.
- **plan / decision / doc**: read the file(s) / capture the decision text, and inline the actual
  content. These are usually small enough to embed.

Build the shared reviewer prompt = the **verification preamble** + a mode line + the structured-output
ask:

```
<verification preamble>

<mode line - e.g. for code: "Review the changes in this repo (diff range: <RANGE>). Focus on
correctness, edge cases, security, and anything that breaks under real inputs.">

<caller focus, if any: if the invoking skill or user supplied specific questions, paste them here
VERBATIM as "Specifically answer: ...". Omit this block if none.>

For each issue, report:
- Finding: <one line>
- Type: defect | enhancement
- Severity: critical | high | medium | low
- Evidence: file:line, a command's output, or the exact supplied text
- Confidence: 1-10
- Action: <what to do>

**Type is scope discipline, not politeness.** A `defect` is a correctness, security, breakage,
or missing-test problem in the subject AS SCOPED - it must be fixed before ship. An `enhancement`
is a new feature, a larger refactor, a speculative abstraction, or hardening BEYOND the stated
ask/plan - it is ADVISORY ONLY: the caller logs it as a follow-up and does NOT build it without
the owner's go-ahead. When unsure, tag `enhancement`. Do not inflate scope: prefer the simplest
correct fix, and never propose new surface area (a feature, endpoint, flag, dependency, or
abstraction) as something to just build - report it as an enhancement the owner decides on.

Be thorough but prioritise; at most 10 findings, ranked by severity. A clean result is a valid
outcome - report it as an evidenced per-area verdict, not a bare "no findings".
```

### Step 3 - Fan out four subagents in parallel
Dispatch **four general-purpose subagents in the same turn** (one message, four Agent calls, each
`run_in_background: true`) - label them `codex` / `gemini` / `glm` / `fable`. These are ROLE labels, not
subagent-type names; all four are general-purpose agents. Background dispatch is what makes them
parallel and non-blocking: a slow or wedged leg does NOT hold up the others or the turn - you are
notified as each returns.

Each subagent's only job is to **run its model via the matching review skill and return that model's
findings verbatim**. It must NOT add its own analysis, and it must NOT run the sibling skill's "add
your own assessment / My Take" step - that would leak a fifth (Claude-orchestrator) opinion into the
panel.

**A leg must BLOCK on its CLI and return real findings, never background-and-return.** The single
biggest wall-clock waste in this loop is a leg subagent that launches its review CLI as a background
task and then yields to the orchestrator before any output exists, forcing manual re-nudges. A
subagent that returns before its CLI produced findings is a FAILED leg, not a clean one: the
orchestrator re-runs it synchronously (or marks it `unavailable`), and NEVER records an empty
early-return as "no findings". Tell each leg, in its prompt, to run its CLI to completion and return
the findings text (or a definite failure), not to background it.

**Detect a background-and-return by its tell** - an empty or near-instant reply, no `MODEL:` line, or
language like "started"/"running in the background" instead of findings. Recover by nudging that SAME
leg in place (send a message to the codex/gemini/glm/fable agent: "you returned before your CLI
finished - block on it now and return the findings"), not by accepting the early return or launching a
redundant duplicate leg. Only mark it `unavailable` if the nudge itself times out.

**Every leg reports the exact model it ran.** At the top of its returned report the subagent states
the precise model ID its CLI used this run - the pin (or default) the sibling skill applied, read back
from the run, e.g. `MODEL: gpt-5-codex` or `MODEL: claude-fable`. Do NOT hardcode versions in this
skill (they rot, see the model-pins note above); the synthesis names whatever each leg reports. If a
leg cannot read its model back, it reports `MODEL: unknown`.

**Mode mapping when dispatching** (the sibling skills implement `code`/`decision`/`plan`/`build`/`codebase`,
there is NO `doc` mode): `doc` -> the sibling's `decision` path with the document inlined; `plan` ->
`plan`; `code`/`build` -> `code`/`build` **at the exact diff range from Step 1**. Pass that range
explicitly in each leg's prompt - do NOT let a leg fall back to the sibling's default `main...HEAD`,
or unrelated in-flight work pollutes the "isolated" review.

- Subagent **codex** -> "Invoke `codex-review` on `<subject>` at `<explicit mode + range>`. You are
  one leg of a quad review (Codex+Gemini+GLM+Fable). Run Codex and return ONLY CODEX's findings in the
  structured format below; do not add your own analysis or run the skill's My-Take step. Run your CLI
  to completion and BLOCK on it. Do NOT launch it in the background and return before it has produced
  output - a background-and-return is a FAILED leg. Return the findings text now, or state a definite
  failure; never yield with nothing. <shared prompt>"
- Subagent **gemini** -> same, invoking `gemini-review`.
- Subagent **fable** -> same, invoking `fable-review`. Fable explores the repo itself (read-only plan
  mode), so it behaves like Codex/Gemini - pass it the repo dir + diff range, not an inlined diff.
- Subagent **glm** -> same, invoking `zai-review`. GLM cannot explore the repo, so THIS subagent runs
  `git diff <range>` / reads the files/plan/doc ITSELF and inlines them into GLM's prompt.

Give the CLIs room: a thorough pass on each model can run 5-7 minutes. Collect each report as it lands.
If a leg has not returned after **~12 minutes**, mark it `unavailable` and synthesize with the rest -
never stall the panel on one wedged leg (see Graceful degradation).

**Do not fork-bomb a small host.** Each leg spawns a heavy CLI; four launched at once on a modest
machine can exhaust the process table and kill a leg outright. On a resource-limited host, cap
concurrency - run the legs two at a time rather than all four - and prefer this restraint whenever the
diff is small enough that the panel overhead dwarfs the change (see Scale to the subject: a trivial
change does not get the full four-CLI panel at all).

### Step 4 - Normalise and cross-check
For each returned finding: tag its source model, and **cross-check every `file:line` reference from the
models against the real files** before trusting it (models occasionally hallucinate paths).
Drop or flag references that do not exist.

### Step 5 - Synthesize (the orchestrator's only judgement call)
Merge the four lists into one. **Deduplicate**: the same issue raised by more than one model becomes a
single row, attributed to all who flagged it, with a **consensus tag** (out of the number that ran):
- **4/4** all four flagged it - highest confidence, fix it.
- **3/4** three flagged it - strong signal.
- **2/4** two flagged it - real; verify.
- **1/4** one flagged it - real but unconfirmed; verify before acting. Extra caution when the sole
  flagger is the **GLM leg** (it saw only the inlined code) or the **Fable leg** (Claude-family, so a
  Fable-only finding that echoes the orchestrator's instinct is weaker independent signal than one from
  an outside model).

When a model was `unavailable`, the consensus denominator is the number that actually RAN, and the
header names the missing model - e.g. `3/3 (Codex, Gemini, Fable; GLM unavailable)`. Never print `3/4`
for a degraded panel as if a fourth model checked it and stayed silent.

Rank by severity, then by consensus. **Name the exact model each leg ran** in the header - fill each
`<model>` slot from the `MODEL:` line that leg reported (Step 3), not from memory. A leg that did not
run shows its status only (e.g. `Codex (unavailable)`); a leg that could not read its model back shows
`unknown`. Present:

**Keep defects and enhancements separate in the output.** Carry each finding's `Type` through to
the table, and split the actionable lists: **Must-fix defects** hold the gate; **Advisory
enhancements** do not - they are logged, not built, and the caller does not fold them into a "fix"
without the owner's go-ahead. A panel that returns only enhancements is a CLEAN gate result.

```
## Quad Review - <mode>: <subject>
Models: Codex (<model>, <status>) · Gemini (<model>, <status>) · GLM (<model>, <status>) · Fable (<model>, <status>)

### Findings
| # | Type | Severity | Consensus | Finding | Location | Action |
|---|------|----------|-----------|---------|----------|--------|
| 1 | defect      | Critical | 4/4       | ...     | file:line| ...    |
| 2 | defect      | High     | 2/4 (C,F) | ...     | file:line| ...    |
| 3 | enhancement | Medium   | 1/4 (GLM) | ...     | file:line| log as follow-up; owner decides |

### Must-fix defects (before ship/act)
1. ...

### Advisory enhancements (NOT for this build - log as follow-ups)
1. ...

### Agreed clean
[Areas all available models checked and passed, with the evidence - not a bare "looks fine".]

### Disagreements worth a closer look
[Where models contradict each other. Offer /ai-debate to litigate.]
```

### Step 6 - Follow up

**Standalone / interactive use only.** Offer: fix the must-fix items; run `/ai-debate` on a specific
disagreement; or a deeper single-model dig on one area.

**When a build or plan workflow invoked you as a review GATE inside a loop**: do NOT print this menu
and do NOT ask the user which option to take. Return the synthesized findings table to the CALLER and
stop there. The caller's own bounded loop folds the confirmed findings back in and re-runs you, until
its exit condition (consensus clean) or its bound (cycle cap / irreconcilable dispute). Handing the
user a menu mid-loop is what turns an autonomous "review until clean" into a stop-and-ask - do not do
it. Two things, and only these two, return control to the user from inside the gate: a genuine
product / design / trust decision, and an ENHANCEMENT whose adoption would add new surface area beyond
the ask/plan (a feature, endpoint, flag, dependency, or abstraction). Both are surfaced as decisions,
never as a "pick a follow-up" prompt, and never folded silently into a "fix". Advisory enhancements
that do NOT expand scope are just logged as follow-ups; they do not stop the loop and are not built.

## Graceful degradation (never silently drop a model)

| Situation | Behaviour |
|---|---|
| One model unavailable (auth, quota, wedge, timeout) | Proceed with the rest; mark it `unavailable` in the header and say which. A 3/4 panel is still a quad review with one leg down - do not hide it. |
| GLM unfunded (billing error) | Report "GLM: unfunded - fund your z.ai account"; continue with the rest. Never treat the billing error as a finding. |
| Fable not logged in | Report "Fable: not logged in - sign in to Claude Code on this machine"; continue with the rest. Not a finding. |
| Codex emits nothing / a streaming leg wedges | Treat as a wedged handshake, not "clean" - relaunch that leg attached once, else mark unavailable. **Does NOT apply to Fable**: `claude -p` text mode emits nothing until completion by design, so judge the Fable leg by its wrapper's exit code or timeout signal, never by silence. |
| All four unavailable | Do NOT fake a review. Report that no model ran and why; suggest fixing the failing prerequisite. |
| Empty diff (code mode) | Say so; offer a branch diff, a specific file, or a different mode. |

## Scale to the subject
Match the panel to the diff - this is a rule, not a suggestion, because running four heavy CLIs on a
one-line change is the overhead the loop is blamed for, not the safety. A **trivial change** (a lint
autofix, a one-line copy/comment/config tweak, a diff under ~30 changed lines with no logic change)
gets ONE model - a single `*-review` - not the four-CLI panel. Reserve the **full panel** for
substantive logic changes, wide-reaching or cross-cutting diffs, and every money-path / authz /
migration change. Three independent external models plus Fable is the standard for a real review, not
a ceiling to always max out - and a copy tweak is not a real review subject.

## Example invocations

```
/quad-review code                                  # uncommitted changes
/quad-review code src/app/billing.ts               # a specific file
/quad-review build                                 # this branch vs main (feature diff)
/quad-review plan docs/plans/2026-09-02-thing.md   # a plan before building
/quad-review decision "move the CDP from Firestore to Postgres"
/quad-review doc ~/Downloads/share-transfer-484.md # a document before acting on it
/triple-review code                                # older alias, still works if your setup wires it up
```

**Four models, one synthesized verdict, consensus-tagged: three independent external models plus a
deep-reasoning Fable leg. The orchestrator never grades its own homework.**
