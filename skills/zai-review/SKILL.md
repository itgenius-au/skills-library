---
name: zai-review
description: "Use z.ai's GLM models (GLM-5.2) as a second-opinion reviewer AND a general coding engine, via the z.ai HTTP API. A third independent model alongside codex-review and gemini-review — for code/decision/plan/build/codebase review, and for offloading coding tasks to GLM. Triggers on: zai review, z.ai review, glm review, ask glm, glm check, review with glm, glm audit, glm opinion, glm code, glm coding, use glm, zhipu review, third opinion."
argument-hint: "[mode: code|decision|plan|build|codebase|coding] [target: file path, branch, or description] [--model glm-5.2|glm-5-turbo|glm-4.6]"
---

# z.ai (GLM) Review + Coding — Second-Opinion Model & Coding Engine

Calls **z.ai's GLM models** (default `glm-5.2`) over the HTTP API to get independent analysis
from a third model alongside `codex-review` (GPT) and `gemini-review` (Gemini), and to offload
coding tasks to GLM. Use it for a second pair of eyes from a fundamentally different model, or to
have GLM draft an implementation that your primary agent then applies and verifies.

## How this differs from codex-review / gemini-review (read first)

z.ai ships **no headless CLI** (ZCODE is a GUI app), so this skill talks to the **HTTP API
directly** via `curl`. The consequence that changes how you use it:

**GLM only sees what you put in the prompt — it does NOT autonomously explore the repo.**
Codex and Gemini drive their own CLI and run `git diff`, read files, grep, etc. GLM (direct-HTTP)
cannot. So **the calling agent must assemble the context** — the diff, the relevant file contents,
the plan text — *into the prompt* before calling. If you don't show GLM the file, GLM can't review it.

The empirical-verification preamble still applies, but its "run the command yourself" clause is
addressed to *the calling agent*: supply the evidence, and where GLM says "I couldn't verify X
without access," fetch X and re-send. An optional **agentic recipe** (GLM self-driving via a
headless coding agent) is documented at the end for when you genuinely want GLM to explore on its own.

## The call: raw curl (and an optional local wrapper)

z.ai's API is OpenAI-compatible. The canonical call is a `curl` to the chat-completions endpoint:

```bash
# $ZAI_API_KEY = your z.ai key (see Prerequisites). $PROMPT = preamble + context (assembled below).
curl -sS https://api.z.ai/api/coding/paas/v4/chat/completions \
  -H "Authorization: Bearer $ZAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg m "glm-5.2" --arg p "$PROMPT" \
        '{model:$m, max_tokens:32000, messages:[{role:"user", content:$p}]}')" \
  | jq -r '.choices[0].message.content'
```

Because you call this repeatedly, **this skill ships that wrapper in its own directory**:
`glm-exec.sh` (plus its stdlib `glm_call.py` helper). It encapsulates the key load, the model pin,
the endpoint choice, a generous `max_tokens`, passing a large prompt via a temp file (shell arg
limits), and error classification (unfunded / auth / transient). Everything after this section uses
`glm-exec.sh …` as shorthand. **Call it by its path in this skill's base directory** (the
`Base directory for this skill:` path shown when the skill loads):

```bash
"$SKILL_DIR/glm-exec.sh" --model glm-5.2 --max-tokens 32000 -- "$PROMPT"
```

It resolves your key automatically: `ZAI_API_KEY` from the env if set, else from your own secret
manager. No local `.env`, no hard-coded key.

## Mandatory invocation rules (every call)

**Pin `--model glm-5.2`.** GLM-5.2 is z.ai's current flagship (best for coding/review). Verified
working 2026-06-29. Alternatives: `glm-5-turbo` (faster/cheaper, same family), `glm-4.6` (older,
much lighter reasoning — good for quick/cheap checks). Confirm the live lineup occasionally; z.ai
also lists `glm-4.7`, `glm-4.5-air`.

**Use a generous `max_tokens` (32000 for a real diff review).** GLM-5.2 is a *heavy reasoner* — it
can spend thousands of tokens "thinking" before emitting the final answer, and `max_tokens` caps
reasoning **plus** answer. Too low a cap returns empty/truncated `content` — and because the
reasoning is spent first, you lose the *findings*, not the preamble. **Measured 2026-07-12:
`max_tokens 8192` TRUNCATED on a ~2,200-line diff review and produced no usable findings; 32000
completed.** So 8192 is NOT a safe floor for a substantial review — treat it as the floor for a
*small* one (a single file, a short decision). Budget ~32000 for any multi-file diff, and tell GLM
explicitly to keep its reasoning brief and lead with the findings. For a one-line answer, 512 is plenty.

**Assemble the context into the prompt.** Run `git diff` / read the files / read the plan yourself
and inline them (fenced) in `$PROMPT`. GLM sees nothing else. Scope it: a focused diff + the
changed files beats dumping the whole repo (and costs less quota).

**Keep the key out of source.** Resolve `ZAI_API_KEY` from an env var, else from your secret manager.
Never reference a local `.env` or hard-code the key.

**Surface failures, don't guess.** Have the wrapper exit non-zero and print a clear marker on
failure (see Edge Cases). Treat an "insufficient balance" error as "needs a plan top-up," never as
a review verdict — and never substitute your own opinion silently for a failed GLM call.

## Core Principle: Verify Empirically, Don't Trust Docs

Prepend this empirical-verification + evidenced-verdict preamble to every review prompt:

```
You are reviewing real code. Treat documentation, code comments, and any prior agent's claims as
UNVERIFIED HYPOTHESES, not facts. Base every finding on evidence you can point to: a file:line
reference or the output of a command. If you cannot verify a claim from the material provided, say
so explicitly ("I'd need to see X to confirm") rather than guessing. When an area is clean, report
an evidenced per-focus-area verdict ("checked X, Y, Z — no issues because …"), not a bare "no findings".
```

Because GLM can't run commands itself here, "evidence" means reasoning grounded in the code you
supplied — and an explicit "I'd need to see X to confirm" when the supplied context is insufficient
(then you fetch X).

## When to Use

- **Code review** (`code`): review a diff, file, or branch with a third model.
- **Decision review** (`decision`): stress-test an architectural/business decision.
- **Plan review** (`plan`): critique an implementation plan before building.
- **Build review** (`build`): post-build audit of what was just implemented.
- **Codebase review** (`codebase`): targeted health check of an area you supply.
- **Coding** (`coding`): offload an implementation/refactor to GLM; the primary agent applies + verifies.

Best paired with the other two for multi-model coverage (see Multi-Model).

## Prerequisites

### Funding (the one real gotcha)

z.ai calls require an active **GLM Coding Plan** or pay-as-you-go balance. Without it every call
returns `HTTP 429 · code 1113 · "Insufficient balance or no resource package"`. Fix at
[z.ai/subscribe](https://z.ai/subscribe) (Coding Plan Lite is the cheap entry tier). The Coding
Plan bills through the `coding` endpoint (the default above).

### Key storage

Set `ZAI_API_KEY` in the env, or store your z.ai key in your own secret manager; the bundled
`glm-exec.sh` fetches it automatically. To rotate, push a new version to the same secret.

## Modes

> Every example assumes the preamble is prepended and the context is assembled into `$PROMPT`.
> In every example, **`glm-exec.sh` is shorthand for `"$SKILL_DIR/glm-exec.sh"`** - the wrapper
> bundled in THIS skill's base directory. It is NOT on your `$PATH`; always call it by that path
> (`SKILL_DIR` = the "Base directory for this skill" path shown when the skill loads). For a large
> diff, prefer `--prompt-file <file>` over `-- "$PROMPT"` to dodge argv size limits.
> Canonical call: `"$SKILL_DIR/glm-exec.sh" --model glm-5.2 --max-tokens 32000 -- "$PROMPT"`.

### 1. Code Review (`code`)

```bash
DIR="$PROJECT_DIR"
DIFF="$(cd "$DIR" && git diff)"                        # or: git diff main...HEAD
PROMPT="$PREAMBLE

Review the code changes below. Focus on:
- Correctness and edge cases
- Security vulnerabilities
- Performance issues
- Maintainability (only where it actively harms correctness)
Report issues with file:line references. Be direct. Give a per-focus-area evidenced verdict;
if you'd need to see a file not shown below to confirm something, say exactly which.

=== git diff ===
$DIFF
"
glm-exec.sh --model glm-5.2 --max-tokens 32000 -- "$PROMPT"
```

Variants: for a **specific file**, inline its full contents instead of the diff; for a **branch
diff**, use `git diff main...HEAD`. Always inline the actual file bodies GLM needs — it can't open
them itself.

### 2. Decision Review (`decision`)

```bash
PROMPT="$PREAMBLE

I'm considering this decision:

$DECISION_DESCRIPTION

Context (verify against any code I've inlined; flag claims you can't check):
$CONTEXT

Play devil's advocate — risks, failure modes, alternatives, blind spots. Be blunt. If after
thorough reasoning the decision holds up, say so plainly rather than manufacturing weak
counter-arguments."
glm-exec.sh --model glm-5.2 --max-tokens 32000 -- "$PROMPT"
```

### 3. Plan Review (`plan`)

```bash
PLAN="$(cat "$PLAN_FILE_PATH")"
PROMPT="$PREAMBLE

Critique the implementation plan below. Consider: soundness, missing/underspecified steps,
riskiest parts, sequencing/dependencies, over- or under-engineering. The plan describes INTENDED
work — I've inlined the relevant current code after it; flag any mismatch between the plan's
assumptions and the real code.

=== plan ===
$PLAN

=== current code the plan touches ===
$RELEVANT_CODE
"
glm-exec.sh --model glm-5.2 --max-tokens 32000 -- "$PROMPT"
```

### 4. Build Review (`build`)

```bash
DIR="$PROJECT_DIR"
LOG="$(cd "$DIR" && git log --oneline -20)"
DIFF="$(cd "$DIR" && git diff main...HEAD)"
PROMPT="$PREAMBLE

Audit what was just built (log + full branch diff below). Assess: correctness/completeness, bugs,
edge cases, security, structure/maintainability, missing tests or error handling. Prioritize
actionable findings. Clean result => per-area evidenced verdict, not a bare phrase.

=== git log ===
$LOG

=== git diff main...HEAD ===
$DIFF
"
glm-exec.sh --model glm-5.2 --max-tokens 32000 -- "$PROMPT"
```

### 5. Codebase Review (`codebase`)

GLM can't crawl the repo — *you* pick the area and inline it.

```bash
PROMPT="$PREAMBLE

Review the $AREA_DESCRIPTION code below. Provide: overall quality/organization assessment, top
concerns (bugs, security, tech debt) with file:line refs and evidence, and concrete
recommendations. Actionable findings only, not style nitpicks.

=== files ===
$INLINED_FILES
"
glm-exec.sh --model glm-5.2 --max-tokens 32000 -- "$PROMPT"
```

### 6. Coding (`coding`)

Offload an implementation/refactor to GLM. **GLM proposes; the primary agent applies and verifies**
(the direct-HTTP path does not let GLM edit files — that's the optional agentic recipe).

```bash
PROMPT="$PREAMBLE

Task: $CODING_TASK

Here are the relevant current files. Produce the implementation as a unified diff (or full file
bodies if cleaner), with a short rationale. Don't invent files/APIs you can't see below — if you
need to see something else, say which.

=== current files ===
$INLINED_FILES
"
glm-exec.sh --model glm-5.2 --max-tokens 32000 -- "$PROMPT"
```

Then: the primary agent reviews GLM's proposed diff, **applies it**, and **verifies** (runs the
tests / the app). Never apply GLM's output blind — treat it as a competent draft to check.

## Workflow

1. **Determine mode + target + project dir.** If unclear, ask. Default: `code` on uncommitted changes.
2. **Assemble context.** Run `git diff` / read files / read the plan and inline them into `$PROMPT`.
   Scope tightly — focused context is cheaper and sharper than a repo dump.
3. **Build the prompt.** `PREAMBLE` + mode instructions + the inlined context.
4. **Run the wrapper**, capturing output:
   ```bash
   GLM_OUT=$(glm-exec.sh --model glm-5.2 --max-tokens 32000 -- "$PROMPT")
   rc=$?   # non-zero + "unfunded" => tell the user to fund; non-zero + auth => key issue
   ```
5. **Handle "I need to see X."** If GLM flags context it lacks, fetch it, append, re-run. This
   round-trip is the point of the empirical preamble — guessed answers are worse than "show me X".
6. **Synthesize and present** (below).

## Synthesize and Present

1. Present GLM's findings, attributed "**GLM found:**".
2. Add your own assessment — agree / disagree / nuance per finding.
3. Highlight **disagreements** between your review and GLM's — the most valuable signal.
4. Prioritize by severity/impact.
5. Recommend concrete next steps.

```
## GLM Review Results  (model: glm-5.2)

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

For when you want GLM to explore the repo itself (run `git diff`, read files, even edit), z.ai is
Anthropic-compatible, so you can point a headless Anthropic-compatible coding agent at it:

```bash
ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic \
ANTHROPIC_AUTH_TOKEN="$ZAI_API_KEY" \
ANTHROPIC_MODEL=glm-5.2 \
  <your-coding-agent> -p "$PROMPT" --permission-mode plan   # plan = read-only, no edits
# For agentic coding, swap to an edit-capable permission mode and run it in a worktree.
```

> **Smoke-test before relying on it.** Nested-agent mechanics are easy to get wrong: confirm (a)
> the env actually routes to GLM (not your own model account), (b) the model slug, and (c) that any
> inherited auto-commit hooks / MCP load / permission prompts don't misfire. Run it in a throwaway
> worktree first; if clean, graduate it into the modes above. Until then the direct-HTTP path is
> the supported one.

## Configuration

### Model selection
- `glm-5.2` — **default**. Flagship; strongest coding/review; heavy reasoner (use high `max_tokens`).
- `glm-5-turbo` — same family, faster/cheaper; good for quick reviews.
- `glm-4.6` — older, much lighter reasoning; cheapest for simple checks.
- Verify the live lineup occasionally (z.ai also exposes `glm-4.7`, `glm-4.5-air`).

### Endpoint
- `coding` (**default**) → `https://api.z.ai/api/coding/paas/v4` — billed by the GLM Coding Plan.
- `general` → `https://api.z.ai/api/paas/v4` — for pay-as-you-go balance instead of a Coding Plan.

### Quota awareness
GLM-5.2's heavy reasoning burns completion tokens fast (Coding Plan quota is prompt-count + a
peak-hours multiplier). For high-volume passes, prefer `glm-5-turbo`/`glm-4.6` or scope context tighter.

## Multi-Model Review

Run GLM alongside Codex and Gemini for three independent models on the same code (pair with the
`codex-review` and `gemini-review` skills):

```bash
GLM_OUT=$(glm-exec.sh --model glm-5.2 --max-tokens 32000 -- "$PROMPT")
GEMINI_OUT=$(GEMINI_API_KEY="$KEY" gemini -p "$PROMPT" --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null)
CODEX_OUT=$(codex exec --full-auto -C "$DIR" "$PROMPT" 2>/dev/null)
# The primary agent synthesizes all three. Run them as parallel background calls.
```

Remember the asymmetry: Codex and Gemini explore the repo themselves; **GLM only sees `$PROMPT`**,
so give the GLM call the same context inlined. Three evidenced clean verdicts is a stronger ship
signal than any one alone.

## Edge Cases

- **Insufficient balance (code 1113)**: no Coding Plan / no balance. Fund at z.ai/subscribe — NOT a code finding.
- **Auth error (401/403)**: bad/rotated key. Re-push your z.ai key to your secret manager (or reset `ZAI_API_KEY`).
- **Truncated response**: hit `max_tokens` mid-answer — raise `max_tokens` and re-run.
- **Empty / unparseable content**: 200 but no usable content / unexpected shape — dump the raw body and inspect.
- **Transient failure (429-rate / 5xx / network)**: retry with backoff; if it persists, surface it — don't guess — and offer to fall back to Codex/Gemini.
- **Model slug rejected**: try `glm-5-turbo` / `glm-4.6`; re-check the live model list.
- **GLM reviews stale/missing context**: it can only see what you inlined — if a finding references something you didn't send, that's a context gap, not a real bug. Cross-check before presenting.
- **GLM hallucinates file:line**: cross-check every reference against the real files before surfacing.
- **Empty diff**: if `code` mode finds no changes, say so and offer a branch diff / specific file / codebase area.
- **Large context**: scope to the relevant files; don't dump the whole repo (cost + dilution).

## Example Invocations

```
/zai-review code                       # review uncommitted changes (inline the diff)
/zai-review code src/main.py           # review a specific file
/zai-review decision "Firestore -> Postgres?"
/zai-review plan docs/plans/my-plan.md
/zai-review build                      # audit branch vs main
/zai-review codebase "the auth module"
/zai-review coding "add retry/backoff to the upload client"   # GLM drafts, primary agent applies + verifies
```

**Pin `--model glm-5.2`, use a high `max_tokens` for reviews, and remember: GLM only sees what you put in the prompt.**
