---
name: triple-review
description: "Review one focused diff with THREE independent frontier models at once - Codex (GPT), Gemini, and z.ai (GLM) - then reconcile their findings into a single report. A one-shot multi-model gate: faster and cheaper than ai-debate (which adds challenge rounds), stronger than any single review. Degrades gracefully when a model is unavailable. Triggers on: triple review, three-model review, 3-model review, review with all models, multi-model review, all-model review."
argument-hint: "[dir] [diff-range, e.g. main...HEAD]"
---

# Triple Review - One-Shot Three-Model Code Review

Run Codex, Gemini, and GLM over the SAME focused diff in parallel, then reconcile
their findings into one report. Three independently-trained models flag different
issues; where they agree you can trust it, where they disagree a human should
look.

This is the **one-shot** multi-model gate. It runs each model once and
synthesizes - no back-and-forth. For high-stakes changes where you want the
models to challenge each other's disputed findings across rounds, use `ai-debate`
instead (more thorough, ~4x the cost). For a single second opinion, use one of
`codex-review` / `gemini-review` / `zai-review` on its own.

## When to use

- A pre-merge gate on a focused feature or fix diff.
- Any change where a missed bug is costly but a full debate is overkill.
- You want three models' coverage in roughly the wall-clock of the slowest one.

Scope it to a FOCUSED diff (a feature or fix), not a whole-branch dump: the
reviews are sharper and GLM (which reads only what you inline) stays within its
token budget.

## Prerequisites

Same tools as the single-model review skills - install only what you have:

- **Codex**: `npm install -g @openai/codex`, signed in with `codex login`.
- **Gemini**: `npm install -g @google/gemini-cli`, plus `GEMINI_API_KEY` (from
  [Google AI Studio](https://aistudio.google.com/apikey)) in your env or secret
  manager.
- **GLM (z.ai)**: a `ZAI_API_KEY` (GLM Coding Plan or pay-as-you-go) in your env
  or secret manager. See [z.ai/subscribe](https://z.ai/subscribe).

Missing one model is fine - the skill degrades to a two- or one-model review and
says so.

## Shared verification preamble

Prepend this to every model's prompt so findings are evidence-based, not guessed:

```
You are reviewing real code. Treat documentation, code comments, and any prior
agent's claims as UNVERIFIED HYPOTHESES, not facts. Base every finding on
evidence you can point to: a file:line reference or the output of a command. If
you cannot verify a claim, say so explicitly rather than guessing. When an area
is clean, report an evidenced per-area verdict, not a bare "no findings".
```

## Workflow

### 1. Determine scope

Pick the diff range. Default to the branch vs its base:

```bash
MERGE_BASE=$(git -C "$DIR" merge-base origin/main HEAD)
DIFF_RANGE="${MERGE_BASE}...HEAD"     # or a range the user gave, e.g. main...HEAD
```

Warn (don't fail) on a large diff (say > 60 KB): reviews are most reliable on a
focused range, GLM may truncate, and Codex may run long. Narrow the range if so.

### 2. Build the shared review prompt

```
<verification preamble>

Review this isolated diff for correctness, security, and maintainability.
Only report issues grounded in this diff and the current repository state.
Cite file:line evidence for every material claim.
A clean pass is a valid outcome when supported by evidence.

Diff range: <DIFF_RANGE>
```

Codex and Gemini drive their own CLI and can run `git diff` / read files
themselves. **GLM cannot explore the repo** - inline the actual diff into its
prompt (`git -C "$DIR" diff "$DIFF_RANGE"`), fenced, after the shared prompt.

### 3. Run all three in parallel

Fire the three reviews concurrently (each as a background call), capturing each
output separately. Use the model flags from the single-model skills:

- **Codex**: `codex exec --full-auto -C "$DIR" "$PROMPT"` (see `codex-review`).
- **Gemini**: `GEMINI_API_KEY="$KEY" gemini -p "$PROMPT" --approval-mode yolo -o text` (see `gemini-review`).
- **GLM**: `curl` the z.ai chat-completions endpoint with the inlined-diff prompt and a generous `max_tokens` (see `zai-review`).

Give Codex the longest timeout (it is the long pole); collect each result as it
lands. Do not block synthesis on a model that wedged or timed out.

### 4. Record a status line + degrade gracefully

Mark each model `ok` or `unavailable` (non-zero exit, a wedged handshake, or an
unfunded/auth error is `unavailable` - NOT a review verdict). Lead your output
with the status so the reader knows the coverage:

```
triple-review: codex=ok gemini=ok glm=unavailable
```

If ALL three are unavailable, stop and report that - there is no review to
present. Otherwise proceed with whatever ran.

### 5. Reconcile and present

Cross-check every external file:line reference against the real files before
surfacing it (models sometimes hallucinate paths). Then synthesize:

```
## Triple Review Results  (codex=ok gemini=ok glm=ok)

### Consensus (2+ models agree)
| # | Severity | Finding | Location | Action |
|---|----------|---------|----------|--------|

### Single-model findings (one model only - verify before acting)
| # | Model | Severity | Finding | Location | Your take |
|---|-------|----------|---------|----------|-----------|

### Disagreements
[Where the models conflict - the highest-signal rows for a human]

### Recommended actions (ranked)
1. ...
```

Weight evidence over source. A finding all three raise is a strong signal; a lone
finding is a lead to verify, not a verdict.

## Triple-review vs ai-debate vs single review

| Use | When |
|-----|------|
| a single `*-review` skill | quick second opinion on a small change |
| `triple-review` (this skill) | pre-merge gate; three models' coverage, one shot |
| `ai-debate` | high stakes; models challenge disputed findings across rounds |

## Edge cases

- **Model unavailable**: record `unavailable`, continue with the rest, say so in
  the status line. Never silently substitute your own opinion for a failed model.
- **Large diff**: warn and narrow the range; inline only the focused diff for GLM.
- **Hallucinated file:line**: cross-check against real files before presenting.
- **Empty diff**: nothing to review - say so and offer a branch diff or a file.
- **All three unavailable**: stop; there is no review to present.

## Example invocations

```
/triple-review                       # review the branch vs origin/main
/triple-review . main...HEAD         # explicit range
/triple-review src/ HEAD~1...HEAD    # a directory + a tight range
```
