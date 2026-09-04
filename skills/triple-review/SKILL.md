---
name: triple-review
description: "Run a rigorous triple review - three INDEPENDENT external models (OpenAI Codex + Google Gemini + z.ai GLM) over the same subject in one parallel pass, then synthesize one deduplicated, severity-ranked, consensus-tagged findings list. The primary agent orchestrates only; it is NOT one of the three reviewers (no self-grading). Use for a high-stakes review of code, a decision, a plan, or a document, and as the review gate inside quick-build / auto-build. Triggers on: triple review, triple-review, triple check, triple-check this, three-model review, 3-model review, Codex Gemini GLM, review with all three, panel review."
argument-hint: "[mode: code|decision|plan|doc|build] [target: file path, branch, dir, or description]"
---

# Triple Review - Codex + Gemini + GLM, one pass, synthesized

Runs **three independent external models** over the same subject and returns **one** consolidated
findings list. The three reviewers are:

- **Codex** (OpenAI, via the `codex-review` skill)
- **Gemini** (Google, via the `gemini-review` skill)
- **GLM** (z.ai, via the `zai-review` skill)

**The primary agent is the orchestrator, not a reviewer.** It assembles the subject, fans the three
models out in parallel, then synthesizes - it does NOT add its own review as a fourth opinion. Keeping
the orchestrator out of the reviewer set is deliberate: three outside models with no stake in the work
give a cleaner signal than a model grading its own or its sibling's output.

> **This is the multi-model review gate `quick-build` and `auto-build` call for** - they invoke
> this skill for their review phase rather than hand-rolling the fan-out.

## How it differs from `ai-debate` (pick the right one)

| | `triple-review` (this) | `ai-debate` |
|---|---|---|
| Reviewers | Codex + Gemini + **GLM** (3 external) | **Primary agent** + Gemini + Codex |
| Rounds | **One** (review -> synthesize) | **Three** (review -> challenge -> synthesize) |
| Primary agent | Orchestrator only | A reviewer + moderator |
| Speed / cost | Faster, ~3 calls | Deeper, up to ~4 calls + debate |
| Use when | Fast high-confidence panel over a subject | The finding is disputed and needs models to argue it out |

Reach for `ai-debate` when a `triple-review` surfaces a genuine disagreement worth litigating. Reach
for a single `codex-review` / `gemini-review` / `zai-review` for a quick one-model sanity check.

## When to use

- **Pre-merge / pre-ship code review** of a feature diff or branch.
- **A decision** with real downside (architecture, trust model, money, legal/tax).
- **A plan** before building against it.
- **A document** you are about to act on (contract, filing, tax position, runbook).
- The **review gate** inside `quick-build` (plan review) and `auto-build` (diff review).

**When NOT to use**: a small/obvious change, a style pass, or anything where one model is plenty - use
a single `*-review` skill. Speed-critical work where one opinion suffices.

## Prerequisites (each model's own skill owns the details)

- `codex-review` - Codex CLI signed into the reviewer's own ChatGPT account (`codex login`).
- `gemini-review` - Gemini CLI + a `GEMINI_API_KEY` in your env or secret manager.
- `zai-review` - a z.ai key (`ZAI_API_KEY`) in your env or secret manager + a funded GLM Coding Plan.

Keys resolve from your own env or secret manager (each sibling skill documents its own). Model pins
live in the three sibling skills - do NOT restate versions here (they rot); match whatever those skills pin.

## The verification preamble (prepended to every model's prompt)

```
You are one leg of a triple review. Treat documentation, code comments, plan files, and any prior
agent's claims as UNVERIFIED HYPOTHESES, not facts. Base every finding on evidence you can point to:
a file:line reference, the output of a command you ran, or the exact text of the material supplied.
If you cannot verify a claim, say so explicitly rather than guessing. When an area is clean, report an
evidenced per-area verdict ("checked X, Y, Z - no issue because ..."), not a bare "no findings". Do NOT
defer to the other reviewers; report what YOU find.
```

## Modes

| Mode | Subject | How context reaches the models |
|---|---|---|
| `code` | Uncommitted diff, a file, or a branch | Codex & Gemini read the repo themselves; the GLM leg inlines the diff (GLM can't explore). Default: uncommitted changes. |
| `build` | Branch vs main (`merge-base...HEAD`) | Same as code, over the isolated feature diff. |
| `plan` | A plan/spec file | Read the file; supply its text to all three, plus the current code it touches. |
| `decision` | A claim/choice to stress-test | Supply the decision text + any relevant context to all three. |
| `doc` | Any document (contract, filing, tax position) | Inline the full document text to all three (the models review the text itself). |

## Workflow

### Step 1 - Determine mode, subject, and project dir
Parse the request. If unclear, default to `code` on uncommitted changes and say so. For `code`/`build`,
identify the repo dir and the diff range (`build` = `git merge-base origin/main HEAD`...HEAD, so
unrelated in-flight work does not pollute the review).

### Step 2 - Assemble the review packet (once)
Build ONE shared packet the three legs will each review, so all models see the same thing:
- **code / build**: the repo dir + the diff range. (Codex/Gemini re-derive the diff; the GLM leg will
  inline it.) Do not paste a huge diff into this file's shell args - let each leg gather it.
- **plan / decision / doc**: read the file(s) / capture the decision text, and inline the actual
  content. These are usually small enough to embed.

Build the shared reviewer prompt = the **verification preamble** + a mode line + the structured-output
ask:

```
<verification preamble>

<mode line - e.g. for code: "Review the changes in this repo (diff range: <RANGE>). Focus on
correctness, edge cases, security, and anything that breaks under real inputs.">

<caller focus, if any: if the invoking skill or user supplied specific questions (e.g. quick-build's
four questions), paste them here VERBATIM as "Specifically answer: ...". Omit this block if none.>

For each issue, report:
- Finding: <one line>
- Severity: critical | high | medium | low
- Evidence: file:line, a command's output, or the exact supplied text
- Confidence: 1-10
- Action: <what to do>

Be thorough but prioritise; at most 10 findings, ranked by severity. A clean result is a valid
outcome - report it as an evidenced per-area verdict, not a bare "no findings".
```

### Step 3 - Fan out three subagents in parallel
Dispatch **three general-purpose subagents in the same turn** (one message, three Agent calls, each
`run_in_background: true`) - label them `codex` / `gemini` / `glm`. These are ROLE labels, not
subagent-type names; all three are general-purpose agents. Background dispatch is what makes them
parallel and non-blocking: a slow or wedged leg does NOT hold up the others or the turn - you are
notified as each returns.

Each subagent's only job is to **run its model via the matching review skill and return that model's
findings verbatim**. It must NOT add its own analysis, and it must NOT run the sibling skill's "add
your own assessment / My Take" step - that would leak a fourth (Claude) opinion into the panel.

**Mode mapping when dispatching** (the sibling skills implement `code`/`decision`/`plan`/`build`/`codebase`,
there is NO `doc` mode): `doc` -> the sibling's `decision` path with the document inlined; `plan` ->
`plan`; `code`/`build` -> `code`/`build` **at the exact diff range from Step 1**. Pass that range
explicitly in each leg's prompt - do NOT let a leg fall back to the sibling's default `main...HEAD`,
or unrelated in-flight work pollutes the "isolated" review.

- Subagent **codex** -> "Invoke `codex-review` on `<subject>` at `<explicit mode + range>`. You are
  one leg of a triple review (Codex+Gemini+GLM). Run Codex and return ONLY CODEX's findings in the
  structured format below; do not add your own analysis or run the skill's My-Take step. <shared prompt>"
- Subagent **gemini** -> same, invoking `gemini-review`.
- Subagent **glm** -> same, invoking `zai-review`. GLM cannot explore the repo, so THIS subagent runs
  `git diff <range>` / reads the files/plan/doc ITSELF and inlines them into GLM's prompt.

Give the external CLIs room: Codex at `xhigh` runs ~5-7 min. Collect each report as it lands. If a leg
has not returned after **~8 minutes**, mark it `unavailable` and synthesize with the rest - never
stall the panel on one wedged leg (see Graceful degradation).

### Step 4 - Normalise and cross-check
For each returned finding: tag its source model, and **cross-check every `file:line` reference from the
models against the real files** before trusting it (external models occasionally hallucinate paths).
Drop or flag references that do not exist.

### Step 5 - Synthesize (the orchestrator's only judgement call)
Merge the three lists into one. **Deduplicate**: the same issue raised by more than one model becomes a
single row, attributed to all who flagged it, with a **consensus tag**:
- **3/3** all three flagged it - highest confidence, fix it.
- **2/3** two flagged it - strong signal.
- **1/3** one flagged it - real but unconfirmed; verify before acting, especially if it is the GLM leg
  on code it could only see inlined.

When a model was `unavailable`, the consensus denominator is the number that actually RAN, and the
header names the missing model - e.g. `2/2 (Codex, Gemini; GLM unavailable)`. Never print `2/3` for a
degraded panel as if a third model checked it and stayed silent.

Rank by severity, then by consensus. Present:

```
## Triple Review - <mode>: <subject>
Models: Codex (<status>) · Gemini (<status>) · GLM (<status>)

### Findings
| # | Severity | Consensus | Finding | Location | Action |
|---|----------|-----------|---------|----------|--------|
| 1 | Critical | 3/3       | ...     | file:line| ...    |
| 2 | High     | 2/3 (C,G) | ...     | file:line| ...    |
| 3 | Medium   | 1/3 (GLM) | ...     | file:line| verify then ... |

### Must-fix (before ship/act)
1. ...

### Agreed clean
[Areas all available models checked and passed, with the evidence - not a bare "looks fine".]

### Disagreements worth a closer look
[Where models contradict each other. Offer /ai-debate to litigate.]
```

### Step 6 - Follow up
Offer: fix the must-fix items; run `/ai-debate` on a specific disagreement; or a deeper single-model
dig on one area.

## Graceful degradation (never silently drop a model)

| Situation | Behaviour |
|---|---|
| One model unavailable (auth, quota, wedge, timeout) | Proceed with the other two; mark it `unavailable` in the header and say which. A 2/3 panel is still a triple review with one leg down - do not hide it. |
| GLM unfunded (`1113`) | Report "GLM: unfunded - fund at z.ai/subscribe"; continue with Codex+Gemini. Never treat the billing error as a finding. |
| Codex emits nothing | Treat as a wedged handshake, not "clean" - relaunch that leg attached once, else mark unavailable. |
| All three unavailable | Do NOT fake a review. Report that no external model ran and why; suggest fixing the failing prerequisite. |
| Empty diff (code mode) | Say so; offer a branch diff, a specific file, or a different mode. |

## Scale to the subject
A trivial change (a lint autofix, a one-line copy tweak) gets a light pass - or a single `*-review`.
A substantive or high-blast-radius change gets the full panel at each model's higher effort. Three
independent models is the floor for a real review, not the ceiling.

## Example invocations

```
/triple-review code                                  # uncommitted changes
/triple-review code src/app/billing.ts               # a specific file
/triple-review build                                 # this branch vs main (feature diff)
/triple-review plan docs/plans/my-plan.md          # a plan before building
/triple-review decision "move the CDP from Firestore to Postgres"
/triple-review doc ~/Downloads/share-transfer-484.md # a document before acting on it
```

**Three independent external models, one synthesized verdict, consensus-tagged. The orchestrator
never grades its own homework.**
