---
name: ai-debate
description: "Orchestrate multi-round debates between Claude, Gemini, and Codex for higher-quality reviews. Three rounds: independent review, targeted challenge on disputes, and synthesis with self-challenge. Triggers on: ai debate, debate this, three-model review, consensus review, multi-model debate, 3-way review."
argument-hint: "[mode: code|decision|plan|build|codebase] [target: file path, branch, or description]"
---

# AI Debate - Multi-Model Debate & Consensus Review

Orchestrates a structured 3-round debate between your primary agent (in-process), Gemini, and Codex
to produce higher-quality reviews than any single model. Models review independently, challenge each
other's disputed findings, and converge on consensus - with minority opinions preserved.

**Use this instead of one-shot `/gemini-review` or `/codex-review` when the stakes are high enough
to justify ~3 minutes and 4 CLI calls.**

> **Model pins live in your sibling review skills, not here.** This skill drives Gemini and Codex
> the **same way as `gemini-review` / `codex-review`** — reuse their model flags and their guards.
> Do NOT restate model versions in this file (they rot). Point at those skills for the current pins.
> Prepend the shared verification preamble (below) to every model prompt — the debate is only as
> good as its evidence discipline.

## When to Use

- **High-stakes code review**: Changes to auth, payments, data pipelines, or anything where a missed bug is costly
- **Architectural decisions**: "Should we migrate to X?" - get three independent perspectives before committing
- **Plan validation**: Critique an implementation plan from three angles before building
- **Pre-merge build audit**: Final check before merging a large feature branch
- **Codebase deep-dive**: Comprehensive health check with three models exploring independently

**When NOT to use** (use one-shot `/gemini-review` or `/codex-review` instead):
- Quick sanity checks on small changes
- Style or formatting reviews
- Anything where speed matters more than thoroughness

## Prerequisites

Same as the sibling review skills:
- **Gemini CLI**: `npm install -g @google/gemini-cli`
- **Codex CLI**: `npm install -g @openai/codex`
- **Gemini API key**: `GEMINI_API_KEY` in your env or your own secret manager
- **Codex auth**: OAuth cached at `~/.codex/auth.json` (run `codex login` if expired)

## The verification preamble

Prepend this to every model prompt (the same empirical + evidenced-verdict discipline the one-shot
skills use):

```
You are reviewing real code. Treat documentation, code comments, and any prior agent's claims as
UNVERIFIED HYPOTHESES, not facts. Base every finding on evidence you can point to: a file:line
reference or the output of a command you ran. If you cannot verify a claim, say so explicitly rather
than guessing. When an area is clean, report an evidenced per-area verdict, not a bare "no findings".
```

## Modes

### 1. Code (`code`)

**Context to gather**: `git diff` (uncommitted), `git diff main...HEAD` (branch), or file contents
**Default**: Uncommitted changes if no target specified

### 2. Decision (`decision`)

**Context to gather**: User's decision description + any relevant context they provide
**Required**: User must describe the decision (inline argument or in conversation)

### 3. Plan (`plan`)

**Context to gather**: Plan file contents (read the file path provided)
**Required**: File path to the plan document

### 4. Build (`build`)

**Context to gather**: `git log --oneline -20` + `git diff main...HEAD`
**Default**: Current branch vs main

### 5. Codebase (`codebase`)

**Context to gather**: Models explore the codebase themselves (CLI advantage - they can read files)
**Default**: Current working directory. If a subdirectory/project is given, `cd` into it first.

## Workflow

### Step 1: Determine Mode and Target

Parse the user's request to identify:
- **Mode**: code, decision, plan, build, or codebase
- **Target**: file path, branch name, plan file, or inline description
- **Project directory**: Which project or repo

If unclear, ask the user. Default to `code` mode reviewing uncommitted changes.

### Step 2: Gather Context

How context reaches each model depends on the mode:

**Code / Build / Codebase modes**: Do NOT pre-gather diffs and embed them in prompts (diffs can be huge and exceed shell argument limits). Instead, instruct the external models to run `git diff`, `git log`, or explore the codebase themselves - they have filesystem access via CLI. Only the primary agent (in-process) reads the context directly.

**Decision / Plan modes**: The context is user-provided text or a plan file. Read the file contents and embed them in the prompt since they're typically small.

```bash
# Decision/Plan mode only - embed in prompt
CONTEXT="$USER_PROVIDED_DESCRIPTION"  # or read the plan file contents
```

### Step 3: Set the API Key

```bash
export GEMINI_API_KEY=...   # from your own secret manager or shell
```

### Step 4: Round 1 - Independent Review

**The primary agent reviews first (in-process).** Perform your own review of the target, producing findings in the structured format below. Do this BEFORE seeing Gemini or Codex output. Think carefully and be thorough - these are your Round 1 findings that will be debated.

**Structured output format** (use for your own review and instruct external models to use):

```
Finding: <description>
Severity: critical | high | medium | low
Evidence: <file:line reference or specific reasoning>
Confidence: 1-10
Proposed Action: <what to do about it>
```

**Then fire Gemini and Codex in parallel.** Issue both Bash tool calls in the same response with `run_in_background: true`. **Use different timeouts: Gemini `timeout: 180000`, Codex `timeout: 600000`** — a deep Codex review at `xhigh` runs ~5–7 min, so a uniform `120000` (2 min) would kill Codex mid-review. Codex is the long pole: collect results as each lands, and **don't block synthesis on a model that wedged or timed out** — degrade gracefully (see Error Handling). If Codex emits no output at all, that's a wedged handshake, not slow work — kill and relaunch it attached.

For **code/build/codebase modes**, instruct models to gather context themselves (they have filesystem access). Build the shared prompt once, prepending the verification preamble:

```bash
PROMPT="$PREAMBLE

[MODE-SPECIFIC PREAMBLE - for code mode: 'Review the uncommitted changes in this repo (run git diff).']

For each issue or insight you find, provide:
- Finding: what you found
- Severity: critical, high, medium, or low
- Evidence: file:line reference or specific reasoning
- Confidence: 1-10 (how sure are you?)
- Proposed Action: what should be done

Be thorough but prioritize. Focus on issues that matter, not style nitpicks.
Report a maximum of 10 findings, ranked by severity. A clean result is fine — report it
as an evidenced per-area verdict, not a bare 'no findings'."
```

```bash
# Gemini (Bash call 1, run_in_background: true, timeout: 180000) — same flags as gemini-review.
cd "$PROJECT_DIR" && GEMINI_API_KEY="$KEY" gemini -p "$PROMPT" \
  --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null   # match your gemini-review pin
```

```bash
# Codex (Bash call 2, run_in_background: true, timeout: 600000) — same flags as codex-review.
codex exec -s read-only -C "$PROJECT_DIR" "$PROMPT" 2>/dev/null         # match your codex-review pin
```

**Note:** Round 1 sessions are preserved. Round 2 uses session resumption (`codex exec resume --last` and `gemini --resume latest`) so models retain their Round 1 context and can build on prior analysis.

For **decision/plan modes**, embed the user-provided context directly in the prompt (it's typically small enough).

**Mode-specific preambles:**

| Mode | Preamble |
|------|----------|
| code | "Review the uncommitted changes in this repo (run git diff). Focus on correctness, edge cases, security vulnerabilities, performance issues, and maintainability." |
| decision | "I'm considering the following decision. Play devil's advocate. What are the risks? What could go wrong? What alternatives should I consider? What am I not thinking about?" |
| plan | "Critique this implementation plan. Is the approach sound? What's missing? What are the riskiest parts? Is the sequencing right? Is it over-engineered or under-engineered?" |
| build | "Audit the recent changes on this branch (run git log --oneline -20 and git diff main...HEAD). Does the implementation look correct and complete? Any bugs, edge cases, or security issues? Missing tests or error handling?" |
| codebase | "Explore this codebase. Provide an overall assessment of code quality, top 5 areas of concern, and specific recommendations with file:line references." |

### Step 5: Normalize Round 1 Outputs

After collecting all 3 outputs, normalize them into a unified list:

1. Parse each model's free-text output and extract findings into the shared schema
2. Tag each finding with its source (primary agent, Gemini, or Codex)
3. **Cross-check all file:line references from Gemini and Codex against the actual codebase** before proceeding - external models sometimes hallucinate paths. Read the referenced files to verify. Drop or flag any references that don't exist.

### Step 6: Identify Disputes

Compare all 3 Round 1 outputs and categorize each finding:

**Consensus** (skip Round 2): All models flagged the same issue, or findings are complementary (different aspects of the same problem).

**Disputed** (send to Round 2):
1. Finding from one model that another model contradicts
2. Finding with confidence < 7 from any model
3. Critical or high severity finding from only one model (others missed it)

**Early termination**: If there are zero disputes and no lone high-severity findings, skip Round 2 entirely. Present the consensus directly and go to Step 8. Note: "All models agreed - no debate needed."

### Step 7: Round 2 - Challenge Disputed Findings

**Fast path — verify directly instead of debating when you can.** If a disputed finding is independently **code-verifiable** (you can settle it by reading the referenced file or running one command yourself), do that and **skip the Round 2 model round-trip for it** — a model round-trip to re-litigate something you can check in 30s is wasted latency and cost. Send to Round 2 only the disputes that genuinely need another model's *judgment*: design trade-offs, risk calls, anything with no ground truth in the code. If every dispute is code-verifiable, resolve them all directly and go straight to synthesis (Step 8), noting "Round 2 skipped — disputes resolved by direct verification." In the output, mark which disputes were settled by verification vs. by debate.

Send the remaining (judgment-needing) disputes to Gemini and Codex for challenge. The primary agent acts as **moderator only** in this round - does NOT add its own rebuttal.

```bash
# Build the challenge prompt with ONLY disputed findings (not full R1 outputs - too large)
CHALLENGE_PROMPT="Three AI models independently reviewed [target]. Below are the disputed findings only.

## Disputed Items

$DISPUTE_LIST_WITH_EACH_MODELS_POSITION

For each disputed item:
1. State whether you agree or disagree with each model's position
2. Provide additional evidence to support your view (run git diff, read files if needed)
3. If you've changed your mind from Round 1, say so and explain why

Focus ONLY on these disputed items."
```

**Tip:** For sharper critique, frame Round 2 as reviewing another model's output: "You're reviewing findings from two other AI models. Identify weak assumptions, missed edge cases, and better alternatives." This yields more critical, less deferential responses.

Fire both in parallel using session resumption so models retain Round 1 context. Use `run_in_background: true`, with `timeout: 600000` for Codex and `timeout: 180000` for Gemini (same long-pole asymmetry as Round 1):

```bash
# Gemini R2 (Bash call 1, run_in_background: true, timeout: 180000)
cd "$PROJECT_DIR" && GEMINI_API_KEY="$KEY" gemini --resume latest -p "$CHALLENGE_PROMPT" \
  --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

```bash
# Codex R2 (Bash call 2, run_in_background: true, timeout: 600000)
# Resume the Round 1 session; keep < /dev/null so it can't hang on stdin.
codex exec resume --last -c 'model_reasoning_effort="xhigh"' "$CHALLENGE_PROMPT" < /dev/null 2>/dev/null
```

**Fallback:** If session resumption fails (session expired, CLI version mismatch), fall back to a fresh call with full context embedded in the prompt.

Collect results when both complete.

### Step 8: Round 3 - Synthesis

Read all Round 1 and Round 2 outputs. Before writing the final output, perform a self-challenge:

**Self-challenge checklist:**
- For each of your Round 1 findings, did Gemini or Codex provide stronger evidence that contradicts it?
- Did the Round 2 debate reveal flaws in your original reasoning?
- Would you change any severity ratings or confidence scores based on the debate?
- Be honest. Weight evidence quality over source. If another model was right and you were wrong, say so.

**Then produce the final output:**

```
## AI Debate Results

**Mode**: [code/decision/plan/build/codebase]
**Target**: [what was reviewed]
**Models**: Primary agent (in-process) + Gemini + Codex
**Model pins**: [as resolved at run time — Gemini/Codex per your sibling review skills]
**Rounds**: [2 or 3]

### Consensus (all models agree)
| # | Severity | Finding | Location | Action |
|---|----------|---------|----------|--------|

### Resolved Disputes
| # | Finding | Round 1 Positions | Round 2 Resolution | Action |
|---|---------|-------------------|---------------------|--------|

### Unresolved (minority opinion preserved)
| # | Finding | For | Against | Recommendation |
|---|---------|-----|---------|---------------|

### Self-Challenge
[Where the primary agent changed its own Round 1 position based on debate evidence.
If no changes, state: "No position changes - Round 1 findings held up under scrutiny."]

### Recommended Actions (ranked by impact)
1. ...
2. ...
```

### Step 9: Follow-up

After presenting results, offer:
- "Want me to fix any of these issues?"
- "Want me to run a deeper debate on any specific finding?"
- "Want me to get a one-shot review from Gemini or Codex on a specific area?"

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Gemini CLI fails or times out | Degrade to 2-model debate (primary + Codex). Note: "Gemini was unavailable for this debate." |
| Codex CLI fails or times out | Degrade to 2-model debate (primary + Gemini). Note: "Codex was unavailable for this debate." |
| Both CLIs fail | Fall back to a single-model review. Note: "External models were unavailable. This is a single-model review, not a debate." |
| Round 1 produces zero disputes | Skip Round 2. Present consensus directly. Note: "All models agreed - no debate needed." |
| Empty diff (code mode) | Tell the user and offer alternatives (branch diff, specific file, codebase review) |
| API key missing | Fetch from your secret manager. If that fails, report the error and suggest manual key setup |
| Codex auth expired | Report the error and instruct: "Run `codex login` to re-authenticate" |

**Timeouts**: Codex ~600s, Gemini ~180s (Codex at `xhigh` runs ~5–7 min; a uniform 120s would kill it mid-review). Use the `timeout` parameter on the background bash calls. If Codex emits no output at all, treat it as a wedged handshake ("relaunch attached"), not "found nothing".

## Edge Cases

- **Gemini hallucinates file paths**: Cross-check ALL file:line references from external models against the actual codebase before including in results
- **Models produce unstructured output**: If a model ignores the structured format, extract findings manually from the free-text output
- **Large diffs**: For diffs over 500 lines, consider scoping to specific files rather than the full diff
- **Subproject context**: When debating a subproject, `cd` into its directory before running CLI commands so models have the right filesystem context
- **Codebase mode Round 2**: Re-include `-C "$PROJECT_DIR"` for Codex and `cd` for Gemini in Round 2 so models can re-examine disputed files

## Configuration

### Model Selection

Model pins are **owned by your `codex-review` and `gemini-review` skills**, not restated here —
restating is exactly how a multi-model skill drifts to a stale version. Match whatever those skills
currently pin. The primary agent runs in-process on its own session model.

### Performance

| Metric | Value |
|--------|-------|
| CLI calls | 4 max (2 per round x 2 models); often 2 when the Round 2 fast path applies |
| Wall-clock time | ~5–8 min (Codex at `xhigh` is the long pole, ~5–7 min; Gemini ~2 min). Skipping Round 2 ≈ one Codex review of wall-clock. |
| Cost multiplier | ~4x a single one-shot review (less when Round 2 is skipped) |

## Example Invocations

```
/ai-debate code                              # Debate uncommitted changes
/ai-debate code src/main.py                  # Debate a specific file
/ai-debate decision "Migrate to Postgres"    # Debate an architectural decision
/ai-debate plan docs/migration-plan.md       # Debate a plan before building
/ai-debate build                             # Debate recent build vs main
/ai-debate codebase my-project               # Debate a project's health
```
