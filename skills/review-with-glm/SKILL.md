---
name: review-with-glm
description: "Use z.ai's GLM models (its current flagship by default) as a second-opinion reviewer AND a general coding engine, via the z.ai HTTP API. A third independent model alongside review-with-codex and review-with-gemini - for code/decision/plan/build/codebase review, and for offloading coding tasks to GLM. Triggers on: zai review, z.ai review, glm review, ask glm, glm check, review with glm, glm audit, glm opinion, glm code, glm coding, use glm, zhipu review, third opinion."
argument-hint: "[mode: code|decision|plan|build|codebase|coding] [target: file path, branch, or description] [--model <id>]"
---

# Review with GLM (z.ai) - Second-Opinion Model & Coding Engine

Calls **z.ai's GLM models** (the default model is pinned in `glm-exec.sh`) over the HTTP API to get independent analysis from a third model alongside `review-with-codex` (GPT) and `review-with-gemini` (Gemini), and to offload coding tasks to GLM. Use it for a second pair of eyes from a fundamentally different model, or to have GLM draft an implementation that your primary agent then applies and verifies.

## How this differs from review-with-codex / review-with-gemini (read first)

z.ai ships **no headless CLI** (ZCODE is a GUI app), so this skill talks to the **HTTP API directly**. The consequence that changes how you use it:

**GLM only sees what you put in the prompt - it does NOT autonomously explore the repo.** Codex and Gemini drive their own CLI and read files, grep, and so on. GLM (direct-HTTP) cannot. So **the calling agent must assemble the context** - the diff, the relevant file contents, the plan text - *into the prompt* before calling. If you don't show GLM the file, GLM can't review it.

The empirical-verification preamble still applies, but its "run the command yourself" clause is addressed to *the calling agent*: supply the evidence, and where GLM says "I couldn't verify X without access," fetch X and re-send. An optional **agentic recipe** (GLM self-driving via a headless coding agent) is documented near the end for when you genuinely want GLM to explore on its own.

## The call: raw curl (and the bundled wrapper)

z.ai's API is OpenAI-compatible. The canonical call is a `curl` to the chat-completions endpoint (shown to explain what the wrapper does; use `glm-exec.sh` below instead):

```bash
# $ZAI_API_KEY = your z.ai key (see Prerequisites). $PROMPT = preamble + context (assembled below).
curl -sS https://api.z.ai/api/coding/paas/v4/chat/completions \
  -H "Authorization: Bearer $ZAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg m "<model id>" --arg p "$PROMPT" \
        '{model:$m, max_tokens:64000, messages:[{role:"user", content:$p}]}')" \
  | jq -r '.choices[0].message.content'
```

Because you call this repeatedly, **this skill ships that wrapper in its own directory**: `glm-exec.sh` (plus its stdlib `glm_call.py` helper, Python 3 only). It encapsulates the model pin (its `MODEL` variable, the only place a model name is set in this skill), the endpoint choice, a generous `max_tokens`, passing a large prompt via a temp file (shell arg limits), and error classification (unfunded / auth / transient). Everything after this section uses `glm-exec.sh` as shorthand for the literal path shown in "Invocation form" below.

It reads your key from the `ZAI_API_KEY` environment variable (export it from your shell or your own secret manager before the call). No key is stored in the skill, and the wrapper only ever sends it to `https://api.z.ai/`.

## Invocation form (works in restrictive agent harnesses)

Some agent harnesses refuse a Bash command that contains a `$(...)`/backtick substitution, a variable assigned from command output (`DIFF=$(git diff)`), `export VAR=...`, a variable used as the command name, a heredoc, a `for`/`while` loop, or `bash -c "..."`. Claude Code does this in a git-worktree session. A literal absolute script path with literal arguments and a plain `>` redirect always passes, so use this canonical form for every `glm-exec.sh` call:

1. Write the prompt with your editor/Write tool to a file in a scratch directory. GLM can't read the repo (see "How this differs" above), so this is also where you inline the diff/files/plan text, either directly or by first capturing them with a plain `git diff <RANGE> > <SCRATCH>/glm-diff.txt` and including that text.
2. Run `glm-exec.sh` as ONE plain command. Every path is a **literal absolute path** you paste in, never a shell variable:
   `<SKILL_DIR>/glm-exec.sh --max-tokens 64000 --prompt-file <SCRATCH>/glm-prompt.txt > <SCRATCH>/glm-out.txt 2>&1`
3. Read `<SCRATCH>/glm-out.txt`.

Placeholders (used throughout this skill):
- `<SKILL_DIR>` = this skill's base directory path, pasted literally. Not `$SKILL_DIR`.
- `<SCRATCH>` = a scratch directory for prompts and outputs, pasted literally.
- `<PROJECT_DIR>` = the absolute path of the repo under review.
- `<RANGE>` = the diff range (e.g. `main...HEAD`).

`--prompt-file` and `-- "PROMPT"` are alternatives (both given: exit 2); a missing or empty prompt file exits 2. Prefer `--prompt-file` for anything large (a real diff review).

For a large review, `review-swarm` ships `scripts/glm_packet.py`, which builds the GLM prompt from a body file plus inlined files and refuses an empty inlined file, a packet over the size limit, or a body that promises content that is not there.

## Mandatory invocation rules (every call)

**Use the pinned default model.** The wrapper's default is z.ai's current flagship (best for coding/review), so do not pass `--model` for a normal review. For a quick or cheap check, pass `--model <id>` with a faster or lighter member of the family; confirm the live lineup on z.ai's model list occasionally.

**Use a generous `max_tokens` (64000 for a real diff or plan review; the wrapper default).** The default GLM model is a *heavy reasoner* - it can spend thousands of tokens "thinking" before emitting the final answer, and `max_tokens` caps reasoning **plus** answer. Too low a cap returns empty/truncated `content` - and because the reasoning is spent first, you lose the *findings*, not the preamble. In testing, `max_tokens 8192` truncated on a ~2,200-line diff review and produced no usable findings, and 32000 truncated on a 1,355-line diff and on a 44 KB plan packet while 64000 and 96000 completed. So 8192 is the floor for a *small* review only (a single file, a short decision). Budget 64000 for any multi-file diff or a plan, and tell GLM explicitly to keep its reasoning brief and lead with the findings. For a one-line answer, 512 is plenty.

- For a diff over about 1,000 lines, start at `--max-tokens 96000`.
- On `::GLM-TRUNCATED::`, re-run the SAME prompt once at 96000. Never accept a truncated review as "no findings".
- A reply that is raw reasoning (a think-aloud with draft finding lists and self-questions) instead of a report is also a truncation: read the findings it had concluded, verify each, and mark the review partial.

**Assemble the context into the prompt.** Run `git diff` / read the files / read the plan yourself and inline them (fenced) in the prompt. GLM sees nothing else. Scope it: a focused diff + the changed files beats dumping the whole repo (and costs less quota). Keep the whole packet under about 60 KB: larger prompts risk silent truncation, so split the review into passes.

**Check the prompt before sending.** Search the assembled prompt for phrases that promise content ("included below", "excerpt attached", "see the diff below", "full text follows") and confirm that the promised text is really there, and not empty or truncated. A reviewer that cannot read the repo does not flag a missing excerpt: it writes findings "consistent with the prompt's descriptions" with plausible but invented file:line citations. Treat any finding from a run whose prompt failed this check as unverified.

**Keep the key out of source.** Resolve `ZAI_API_KEY` from an env var or your secret manager. Never hard-code the key.

**Surface failures, don't guess.** The wrapper exits non-zero and prints a clear marker on failure (see Edge Cases). Treat an "insufficient balance" error as "needs a plan top-up," never as a review verdict - and never substitute your own opinion silently for a failed GLM call.

## Core Principle: Verify Empirically, Don't Trust Docs

Prepend this empirical-verification + evidenced-verdict preamble to every review prompt:

```
You are reviewing real code. Treat documentation, code comments, and any prior agent's claims as
UNVERIFIED HYPOTHESES, not facts. Base every finding on evidence you can point to: a file:line
reference or the output of a command. If you cannot verify a claim from the material provided, say
so explicitly ("I'd need to see X to confirm") rather than guessing. When an area is clean, report
an evidenced per-focus-area verdict ("checked X, Y, Z - no issues because ..."), not a bare "no findings".
```

Because GLM can't run commands itself here, "evidence" means reasoning grounded in the code you supplied - and an explicit "I'd need to see X to confirm" when the supplied context is insufficient (then you fetch X).

## When to Use

- **Code review** (`code`): review a diff, file, or branch with a third model.
- **Decision review** (`decision`): stress-test an architectural/business decision.
- **Plan review** (`plan`): critique an implementation plan before building.
- **Build review** (`build`): post-build audit of what was just implemented.
- **Codebase review** (`codebase`): targeted health check of an area you supply.
- **Coding** (`coding`): offload an implementation/refactor to GLM; the primary agent applies + verifies.

Best paired with the other legs for multi-model coverage (see Multi-Model), or run all four via `review-swarm`.

## Prerequisites

### Funding (the one real gotcha)

z.ai calls require an active **GLM Coding Plan** or pay-as-you-go balance. Without it every call returns `HTTP 429 - code 1113 - "Insufficient balance or no resource package"`. Fix at [z.ai/subscribe](https://z.ai/subscribe) (Coding Plan Lite is the cheap entry tier). The Coding Plan bills through the `coding` endpoint (the default above).

### Key storage

Export your z.ai key as `ZAI_API_KEY` (from your shell profile or your own secret manager) before calling the wrapper. To rotate, replace the value in your secret manager. Never use someone else's key - mint your own.

## Modes

> Every example below assumes you write the preamble + assembled context to a prompt file (`<SCRATCH>/glm-prompt.txt`) and invoke with the canonical form from "Invocation form" above: `<SKILL_DIR>/glm-exec.sh --max-tokens 64000 --prompt-file <SCRATCH>/glm-prompt.txt > <SCRATCH>/glm-out.txt 2>&1`, then read `<SCRATCH>/glm-out.txt`. `glm-exec.sh` is not on your `$PATH`.

### 1. Code Review (`code`)

Capture the diff (`git diff > <SCRATCH>/glm-diff.txt`), read it, then write the prompt file:

```
$PREAMBLE

Review the code changes below. Focus on:
- Correctness and edge cases
- Security vulnerabilities
- Performance issues
- Maintainability (only where it actively harms correctness)
Report issues with file:line references. Be direct. Give a per-focus-area evidenced verdict;
if you'd need to see a file not shown below to confirm something, say exactly which.

=== git diff ===
<contents of <SCRATCH>/glm-diff.txt>
```

Variants: for a **specific file**, inline its full contents instead of the diff; for a **branch diff**, capture with `git diff main...HEAD > <SCRATCH>/glm-diff.txt`. Always inline the actual file bodies GLM needs, since it can't open them itself.

### 2. Decision Review (`decision`)

Prompt file:

```
$PREAMBLE

I'm considering this decision:

$DECISION_DESCRIPTION

Context (verify against any code I've inlined; flag claims you can't check):
$CONTEXT

Play devil's advocate - risks, failure modes, alternatives, blind spots. Be blunt. If after
thorough reasoning the decision holds up, say so plainly rather than manufacturing weak
counter-arguments.
```

### 3. Plan Review (`plan`)

Read `<PLAN_FILE_PATH>`, then write the prompt file:

```
$PREAMBLE

Critique the implementation plan below. Consider: soundness, missing/underspecified steps,
riskiest parts, sequencing/dependencies, over- or under-engineering. The plan describes INTENDED
work - I've inlined the relevant current code after it; flag any mismatch between the plan's
assumptions and the real code.

=== plan ===
<contents of <PLAN_FILE_PATH>>

=== current code the plan touches ===
<inlined relevant files>
```

### 4. Build Review (`build`)

Capture the log + diff (`git log --oneline -20 > <SCRATCH>/glm-diff.txt`, then `git diff main...HEAD >> <SCRATCH>/glm-diff.txt`), read it, and write the prompt file:

```
$PREAMBLE

Audit what was just built (log + full branch diff below). Assess: correctness/completeness, bugs,
edge cases, security, structure/maintainability, missing tests or error handling. Prioritize
actionable findings. Clean result => per-area evidenced verdict, not a bare phrase.

=== git log + git diff main...HEAD ===
<contents of <SCRATCH>/glm-diff.txt>
```

### 5. Codebase Review (`codebase`)

GLM can't crawl the repo - *you* pick the area and inline it. Prompt file:

```
$PREAMBLE

Review the $AREA_DESCRIPTION code below. Provide: overall quality/organization assessment, top
concerns (bugs, security, tech debt) with file:line refs and evidence, and concrete
recommendations. Actionable findings only, not style nitpicks.

=== files ===
<inlined file contents>
```

### 6. Coding (`coding`)

Offload an implementation/refactor to GLM. **GLM proposes; the primary agent applies and verifies** (the direct-HTTP path does not let GLM edit files - that's the optional agentic recipe). Prompt file:

```
$PREAMBLE

Task: $CODING_TASK

Here are the relevant current files. Produce the implementation as a unified diff (or full file
bodies if cleaner), with a short rationale. Don't invent files/APIs you can't see below - if you
need to see something else, say which.

=== current files ===
<inlined file contents>
```

Then: the primary agent reviews GLM's proposed diff, **applies it**, and **verifies** (runs the tests / the app). Never apply GLM's output blind - treat it as a competent draft to check.

## Workflow

1. **Determine mode + target + project dir.** If unclear, ask. Default: `code` on uncommitted changes.
2. **Assemble context.** Run `git diff` / read files / read the plan, capturing any command output into a scratch file with a plain redirect, then inline it into the prompt file. Scope tightly - focused context is cheaper and sharper than a repo dump.
3. **Build the prompt.** Write `PREAMBLE` + mode instructions + the inlined context to `<SCRATCH>/glm-prompt.txt`, then run the pre-send check above.
4. **Run the wrapper**, redirecting output to a file, then read it. A non-zero exit with "unfunded" in the output means tell the user to fund; a non-zero exit with an auth error means a key issue.
5. **Handle "I need to see X."** If GLM flags context it lacks, fetch it, append, re-run. This round-trip is the point of the empirical preamble - guessed answers are worse than "show me X".
6. **Synthesize and present** (below).

## Synthesize and Present

**Always lead with the exact model that ran, verbatim** - a `MODEL: <id>` line read back from the actual invocation (the model id the wrapper sent to z.ai: `MODEL: <id>`). Mandatory on every run, standalone or as a `review-swarm` leg (the orchestrator reads this line back). State what actually ran; do not assume the pin.

The `MODEL:` line comes from the wrapper invocation, NEVER from GLM's own self-description. GLM can misname itself: a leg pinned to one model can write a different model's name in its answer. Report the invocation's model, and add the self-report only as a note (`MODEL: <pinned id> (self-reported <name it gave>)`).

**Check every "stale text" finding against the real file before you count it.** Given an inlined diff, GLM can read a removed (`-`) line as current text and report it as still present. Grep the current file for the quoted text; drop the finding when it has 0 hits.

1. Present GLM's findings, attributed "**GLM found:**" (under the `MODEL:` line above).
2. Add your own assessment - agree / disagree / nuance per finding.
3. Highlight **disagreements** between your review and GLM's - the most valuable signal.
4. Prioritize by severity/impact.
5. Recommend concrete next steps.

(When this skill runs as a `review-swarm` leg, skip steps 2-5 and return GLM's findings only.)

```
MODEL: <exact GLM model id this run>

## GLM Review Results

### Findings
| # | Severity | Finding | Location | My Take |
|---|---|---|---|---|
| 1 | High | ... | file:line | Agree / Disagree / Nuance |

### Key Disagreements
[Where the primary review and GLM differ]

### Recommended Actions
1. ...
```

Then offer: fix the issues, ask GLM to dig deeper on one, or run another focus.

## Optional: agentic GLM (self-driving)

For when you want GLM to explore the repo itself (read files, run commands, even edit), z.ai is Anthropic-compatible, so you can point a headless Anthropic-compatible coding agent at it:

```bash
ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic \
ANTHROPIC_AUTH_TOKEN="$ZAI_API_KEY" \
ANTHROPIC_MODEL=<model id> \
  <your-coding-agent> -p "$PROMPT" --permission-mode plan   # plan mode is an instruction only; it does not remove the shell
# For agentic coding, swap to an edit-capable permission mode and run it in a worktree.
```

> **Smoke-test before relying on it.** Nested-agent mechanics are easy to get wrong: confirm (a) the env actually routes to GLM (not your own model account), (b) the model slug, and (c) that any inherited auto-commit hooks / MCP load / permission prompts don't misfire. Run it in a throwaway worktree first. Until then the direct-HTTP path is the supported one.

## Configuration

### Model selection
The default model is the `MODEL` variable near the top of `glm-exec.sh`, the only place this skill names a version (versions rot; `glm_call.py` keeps a same-valued fallback for direct use). It is z.ai's flagship: strongest coding and review, and a heavy reasoner (use a high `max_tokens`). For a quick review, a faster and cheaper member of the same family exists; older models reason much more lightly and suit simple checks. Verify the live lineup on z.ai's model list occasionally, and pass `--model <id>` to override per call.

### Endpoint
- `coding` (**default**) -> `https://api.z.ai/api/coding/paas/v4` - billed by the GLM Coding Plan.
- `general` -> `https://api.z.ai/api/paas/v4` - for pay-as-you-go balance instead of a Coding Plan.

### Timeout and retries
`--timeout` is per request (default 600 s) and a transient failure is retried once by default (`--retries 1`, 20 s apart), so one call can take about twice the timeout. Pass `--retries 0` when you need a hard time bound.

### Quota awareness
The default model's heavy reasoning burns completion tokens fast (Coding Plan quota is prompt-count plus a peak-hours multiplier). For high-volume passes, prefer a lighter model or scope context tighter.

## Multi-Model Review

Run GLM alongside Codex, Gemini, and Claude on the same code (pair with the `review-with-codex`, `review-with-gemini`, and `review-with-claude` skills), or just use the `review-swarm` skill, which fans all four out and synthesizes for you:

```bash
# GLM pass
<SKILL_DIR>/glm-exec.sh --max-tokens 64000 --prompt-file <SCRATCH>/glm-prompt.txt > <SCRATCH>/glm-out.txt 2>&1

# Gemini and Codex passes: their own skills' wrappers, siblings of this skill's folder
<SKILL_DIR>/../review-with-gemini/gemini-exec.sh --dir <PROJECT_DIR> --stdin-file <SCRATCH>/diff.txt --prompt-file <SCRATCH>/gemini-prompt.txt > <SCRATCH>/gemini-out.txt 2>&1
<SKILL_DIR>/../review-with-codex/codex-exec.sh --mode review --dir <PROJECT_DIR> --prompt-file <SCRATCH>/codex-prompt.txt > <SCRATCH>/codex-out.txt 2>&1
# The primary agent reads the out files and synthesizes. Run them as parallel background calls.
```

Remember the asymmetry: Codex and Gemini explore the repo themselves; **GLM only sees the prompt file**, so give the GLM call the same context inlined. Multiple evidenced clean verdicts are a stronger ship signal than any one alone.

## Edge Cases

- **Insufficient balance (code 1113)**: no Coding Plan / no balance. Fund at z.ai/subscribe - NOT a code finding.
- **Auth error (401/403)**: bad/rotated key. Re-export a current `ZAI_API_KEY`.
- **Truncated response (`::GLM-TRUNCATED::`)**: hit `max_tokens` mid-answer - raise `--max-tokens` (96000) and re-run the same prompt once.
- **Empty / unparseable content**: 200 but no usable content / unexpected shape - dump the raw body and inspect.
- **Transient failure (429-rate / 5xx / network)**: retry with backoff; if it persists, surface it - don't guess - and offer to fall back to Codex/Gemini.
- **Model slug rejected**: try another id from z.ai's live model list.
- **GLM reviews stale/missing context**: it can only see what you inlined - if a finding references something you didn't send, that's a context gap, not a real bug. Cross-check before presenting.
- **GLM claims it ran something**: it has no shell. A report that says "I ran X" with output, commit SHAs or file listings is fabricated evidence: check the cited items yourself, and if they do not exist, exclude that review from any consensus count.
- **GLM hallucinates file:line**: cross-check every reference against the real files before surfacing.
- **Empty diff**: if `code` mode finds no changes, say so and offer a branch diff / specific file / codebase area.
- **Large context**: scope to the relevant files; don't dump the whole repo (cost + dilution).

## Example Invocations

```
/review-with-glm code                       # review uncommitted changes (inline the diff)
/review-with-glm code src/main.py           # review a specific file
/review-with-glm decision "Firestore -> Postgres?"
/review-with-glm plan docs/plans/2026-...md
/review-with-glm build                      # audit branch vs main
/review-with-glm codebase "the auth module"
/review-with-glm coding "add retry/backoff to the upload client"   # GLM drafts, primary agent applies + verifies
```

**Use the pinned default model, use a high `max_tokens` for reviews, and remember: GLM only sees what you put in the prompt.**
