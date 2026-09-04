---
name: gemini-review
description: "Use Google Gemini CLI as a second-opinion reviewer for code, decisions, plans, and builds. Runs Gemini headlessly to get independent analysis from a different AI model, then synthesizes findings. Triggers on: gemini review, gemini check, review with gemini, gemini audit, ask gemini, gemini opinion, google review."
argument-hint: "[mode: code|decision|plan|build|codebase] [target: file path, branch, or description] [--full-context]"
---

# Gemini Review - Second-Opinion Code & Decision Review

Runs Google's Gemini CLI (`gemini -p`) headlessly to get independent analysis from Gemini 3.1 Pro. Use this when you want a second pair of eyes - a fundamentally different model reviewing your work, catching blind spots, or stress-testing decisions.

**Always use `-m gemini-3.1-pro-preview`** to ensure the latest flagship model is used. Fall back to `gemini-2.5-pro` if the preview is unavailable.

## Core Principle: Verify Empirically, Don't Trust Docs

Every review prompt sent to Gemini MUST include the empirical-verification directive below. Documentation files (GEMINI.md, CLAUDE.md, AGENTS.md, READMEs, plan docs, comments) describe *intent* - they rot, drift, and sometimes lie. A review grounded in stale docs is worse than no review: it confidently repeats fiction.

Gemini should treat every claim pulled from docs or agent instructions as a **hypothesis to verify** against the live system: read the actual code, run the command, hit the API, check the logs, inspect the config. If it can't verify something because it lacks authorization, access, or context, it should **say so explicitly and ask the master agent (Claude) for help** - an extra round-trip is cheaper than a wrong answer.

Frame this to Gemini as curiosity, not paranoia: "what do I need to see with my own eyes before I believe this?" The goal is clear, grounded answers - not fast hand-waving.

### Empirical-verification preamble (include in every prompt)

Prepend this block to every prompt sent to Gemini (referenced below as `$EMPIRICAL_PREAMBLE`):

```
BEFORE you answer, read this operating rule:

Documentation, GEMINI.md, plan files, comments, and anything an agent
(including me) told you are HYPOTHESES, not facts. Verify every claim
you rely on against the live system: read the actual source, run the
command, check the live config, inspect real data. Do not repeat a
doc's claim without confirming it.

If you hit something you cannot verify - missing access, missing
authorization, a secret you need, an external system you cannot reach,
or context only the master agent has - STOP and say exactly what you
need. I (the master agent) will fetch credentials, grant access, or
provide the context. An extra step is fine; guessing is not.

Lead with curiosity. For every important claim in your review, I want
to see evidence you checked it - a file:line, a command output, a
query result. Unverified claims must be labeled as such.
```

## Core Principle: Thoroughness, Not Issue-Hunting

Reasoning effort is set high so the reviewer **looks carefully**, not so it **finds something to justify the visit**. The success criterion of a review is "the reviewer checked every claim end-to-end and the work stood up to it" - not "the reviewer returned N findings".

If the work is robust, a clean verdict is the right outcome - but it must be an **evidenced per-focus-area verdict**, not a bare "no material findings" one-liner (see the success-criteria block). An evidenced clean pass beats a manufactured nitpick, a fabricated risk, or a stylistic preference dressed up as a bug - and unlike the bare phrase, it can't be mistaken for a skim.

### Success-criteria preamble (include in every prompt, alongside the empirical block)

Prepend this block too (referenced below as `$SUCCESS_CRITERIA`). Keep it in sync across your review skills. **Do not authorize the bare phrase "verified, no material findings"** - that one-liner tends to come back too thin to trust and forces a second, more demanding re-run. Require the evidenced per-area verdict up front so the first pass is already trustworthy.

```
Your job is thorough verification, not adversarial finding. Do not invent
issues, manufacture risks, or pad the report with cosmetic suggestions to feel
useful. Cosmetic preferences (style, naming, formatting, micro-refactors) and
speculative "you might want to consider" notes are off-topic unless they
actively harm correctness, security, or maintainability.

A clean result is a valid, valuable outcome - but report it with EVIDENCE, not
a bare phrase. Do NOT answer with just "verified, no material findings". For
EACH focus area you were asked to check, give a one-line verdict (clear /
minor / issue) and cite the specific evidence you checked - a file:line, a
command you ran, a query result. The reader must be able to see WHAT you
verified, so a clean pass is distinguishable from a shallow skim.

The high reasoning budget is for checking harder, not flagging harder.
```

## When to Use

- **Code review**: Get Gemini to review a diff, PR, file, or set of changes
- **Decision review**: Stress-test an architectural or business decision
- **Plan review**: Have Gemini critique an implementation plan before building
- **Build review**: Post-build audit of what was just implemented
- **Codebase review**: General codebase health check or specific area deep-dive

## Prerequisites

### Install Gemini CLI

```bash
npm install -g @google/gemini-cli
```

### Authentication

Get a Gemini API key from Google AI Studio (a free key works, 1,000 req/day) and provide it as the
`GEMINI_API_KEY` env var - from your shell or your own secret manager:

```bash
export GEMINI_API_KEY=...   # e.g. loaded from your secret manager
```

Never hard-code the key in source or point at someone else's key.

## Headless Execution Pattern

```bash
GEMINI_API_KEY="$KEY" gemini -p "$PROMPT" --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

Key flags:
- `-p "$PROMPT"` - non-interactive/headless mode
- `--approval-mode yolo` - auto-approve all tool calls (file reads etc.)
- `-m gemini-3.1-pro-preview` - flagship model
- `-o text` - plain text output (no JSON, no formatting artifacts)
- `2>/dev/null` - suppress stderr warnings (YOLO mode banners etc.)

**⚠️ `--approval-mode yolo` auto-approves WRITES, not just reads - Gemini has no read-only tier.** A Gemini "review" can create scratch files and even edit unrelated files in the workspace. Gemini's only containment is the current working directory / `--dir` workspace boundary. So: (a) prefer scoping the cwd (or `--dir`, if your build supports it) to the specific subtree under review for a smaller blast radius, and (b) **after any Gemini review, run `git status` on the workspace and discard stray files / unsolicited edits before committing.** If the review runs in a repo with an auto-commit hook, this discipline is what keeps junk off a shared branch.

## Modes

> **Every example below assumes both preambles are prepended to the prompt** (`$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA`, defined in the two Core Principle sections above) and the key is exported/resolved per the Authentication section. Common flag set: `--approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null`.

### 1. Code Review (`code`)

```bash
GEMINI_API_KEY="$KEY" gemini -p \
  "$EMPIRICAL_PREAMBLE

   $SUCCESS_CRITERIA

   Review the uncommitted changes in this repo (run git diff). Focus on:
   - Correctness and edge cases
   - Security vulnerabilities
   - Performance issues
   - Code style and maintainability (only if it actively harms correctness)
   Report issues with file:line references. Be direct - no fluff.
   Cite the exact evidence (file:line, command output) behind each finding.
   If GEMINI.md or other docs make claims you relied on, verify them in code before citing.
   If everything looks correct, give the per-focus-area evidenced verdict described above - do NOT return a bare 'verified, no material findings'." \
  --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

`$EMPIRICAL_PREAMBLE` and `$SUCCESS_CRITERIA` refer to the two verification blocks in the "Core Principle" sections above - always prepend both.

Variants:
- Review a specific file: replace git diff instruction with "Review the file $FILE_PATH"
- Review branch diff: "Review changes on this branch vs main (run git diff main...HEAD)"

### 2. Decision Review (`decision`)

```bash
GEMINI_API_KEY="$KEY" gemini -p \
  "$EMPIRICAL_PREAMBLE

   $SUCCESS_CRITERIA

I'm considering the following decision:

$DECISION_DESCRIPTION

Context:
$CONTEXT

Play devil's advocate. What are the risks? What could go wrong? What alternatives should I consider? What am I not thinking about? Be blunt and direct.
If your critique depends on claims from the context above (or any docs), verify them against the live codebase/system first, or flag them as unverified.
If after thorough checking the decision holds up, say so plainly." \
  --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

### 3. Plan Review (`plan`)

```bash
GEMINI_API_KEY="$KEY" gemini -p \
  "$EMPIRICAL_PREAMBLE

   $SUCCESS_CRITERIA

Read the plan at $PLAN_FILE_PATH and critique it. Consider:
   - Is the approach sound? Are there better alternatives?
   - What's missing or underspecified?
   - What are the riskiest parts?
   - Is the sequencing right? Any dependency issues?
   - Is it over-engineered or under-engineered?
   Be specific and constructive.
   The plan describes INTENDED work - before critiquing, verify what the current codebase actually looks like (files, APIs, data shapes the plan references). Flag any mismatch between the plan's assumptions and reality.
   If the plan stands up empirically, give a per-area evidenced verdict rather than a bare phrase or padded speculation." \
  --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

### 4. Build Review (`build`)

```bash
GEMINI_API_KEY="$KEY" gemini -p \
  "$EMPIRICAL_PREAMBLE

   $SUCCESS_CRITERIA

Audit the recent changes on this branch (run git log --oneline -20 and git diff main...HEAD).
   Review what was built and assess:
   - Does the implementation look correct and complete?
   - Any bugs, edge cases, or security issues?
   - Is the code well-structured and maintainable?
   - Anything that should be refactored before merging?
   - Are there missing tests or error handling?
   Be thorough but prioritize actionable findings.
   For any claim that depends on runtime behaviour (API shape, env var, deployed config), run the command or read the real file rather than trusting comments/docs.
   If the build is clean, report it as a per-area evidenced verdict, not a bare 'verified, no material findings'." \
  --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

### 5. Codebase Review (`codebase`)

```bash
# General health check
GEMINI_API_KEY="$KEY" gemini -p \
  "$EMPIRICAL_PREAMBLE

   $SUCCESS_CRITERIA

Explore this codebase. Understand the architecture, then provide:
   - Overall assessment of code quality and organization
   - Top 5 areas of concern (bugs, security, tech debt) - only if you have evidence
   - Specific recommendations with file:line references
   Focus on actionable findings, not style nitpicks.
   Build your architectural understanding from the actual source (entry points, routes, modules), not from README/AGENTS.md/CLAUDE.md descriptions - those may be out of date." \
  --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

## Workflow

### 1. Determine Mode and Target

Parse the user's request to identify:
- **Mode**: code, decision, plan, build, or codebase
- **Target**: file path, branch name, plan file, or inline description
- **Project directory**: Which project or repo

If unclear, ask the user. Default to `code` mode reviewing uncommitted changes.

### 2. Set the API Key

Ensure `GEMINI_API_KEY` is set in your env (see Authentication above):

```bash
export GEMINI_API_KEY=...   # from your shell or secret manager
```

### 3. Build and Execute the Prompt

Construct the appropriate prompt based on mode (see templates above). Always include:
- Both preambles (`$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA`)
- Clear scope (what to review)
- Specific focus areas
- Instruction to be direct and cite file:line references
- An explicit instruction that a clean result must be an evidenced per-focus-area verdict, not a bare "no findings" (so the pass is trustworthy and the reviewer doesn't pad to feel useful)

Run headlessly and capture output:

```bash
GEMINI_OUTPUT=$(GEMINI_API_KEY="$KEY" gemini -p "$PROMPT" --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null)
```

**`cwd` matters.** Gemini uses the current working directory as its workspace and refuses to read files outside it. `cd` into the directory that contains every file you want reviewed before invoking.

### 3a. Files outside the workspace

If a file you need reviewed lives outside the cwd, Gemini errors with `Path not in workspace: Attempted path "..." resolves outside the allowed workspace directories`. Trust flags don't help - this is a workspace-boundary limit, not a trust prompt. Two workarounds:

1. **Move the cwd up** to a parent directory that contains every file you need, then invoke from there so Gemini can grep/discover the files itself.
2. **Inline the file contents into the prompt itself.** Build the prompt with each file body included as fenced text, then invoke from any cwd:

   ```bash
   cat > /tmp/gemini-prompt.txt <<'PROMPT'
   ... preambles + instructions ...

   # File: path/to/foo.sh
   PROMPT
   cat path/to/foo.sh >> /tmp/gemini-prompt.txt
   GEMINI_API_KEY="$KEY" gemini -p "$(cat /tmp/gemini-prompt.txt)" --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
   ```

   Inlining is the right choice for small fixed sets of files; cwd-up is the right choice when you want Gemini to discover files itself.

### 3b. Transient failures (503, UNAVAILABLE, "high demand")

Gemini's API sometimes returns 503 / `UNAVAILABLE` / "model is currently experiencing high demand". Treat these as transient infrastructure noise, not as a verdict:

1. Retry once with ~30s backoff.
2. If the retry also fails, surface the failure as "Gemini infra unavailable, no review produced" - do NOT fall through to a guessed answer or silently substitute Claude's own opinion.
3. Offer the user the choice to retry later, fall back to another reviewer (e.g. Codex), or skip the second-opinion step.

### 3c. Handle Gemini's "I need help" responses

If Gemini's output says it couldn't verify something - missing access, credentials, an external system it can't reach, or context it doesn't have - **do not suppress or paper over that**. Treat it as a first-class finding:

- Read what Gemini asked for.
- Fetch the credential, grant the access, pull the log/config/dashboard, or supply the missing context.
- Re-run Gemini with the extra information attached to the prompt.

This round-trip is the whole point of the empirical-verification preamble. Guessed answers are worse than "I don't know, here's what I need."

### 4. Synthesize and Present

After receiving Gemini's output:

1. **Present Gemini's findings** clearly, attributed as "Gemini found:"
2. **Add your own assessment** - agree, disagree, or add nuance to each finding
3. **Highlight disagreements** - where Claude and Gemini see things differently, this is the most valuable signal
4. **Prioritize** - rank findings by severity/impact
5. **Recommend actions** - concrete next steps based on the combined review

Format the output as:

```
## Gemini Review Results

### Findings

| # | Severity | Finding | Location | Claude's Take |
|---|---|---|---|---|
| 1 | High | ... | file:line | Agree / Disagree / Nuance |

### Key Disagreements
[Where Claude and Gemini see things differently]

### Recommended Actions
1. ...
2. ...
```

### 5. Interactive Follow-up

After presenting results, offer:
- "Want me to fix any of these issues?"
- "Want me to ask Gemini to dig deeper into any specific finding?"
- "Want me to run another review with a different focus?"

## `--full-context` flag (any mode)

Use `--full-context` (or the user phrasing "full context", "whole conversation", "this session") to attach the **current session transcript + the live state of files touched during the session** to the review prompt. The flag composes with any mode (`code`, `decision`, `plan`, `build`, `codebase`) - it doesn't replace the mode, it gives the reviewer the full conversation as background.

When to use it:
- End-of-session sanity check ("did we miss anything across all this?")
- Skill / workflow design review where the conversation IS the work product
- Plan or build review where decisions made earlier in the session aren't captured in the diff

When NOT to use it:
- Reviewing a clean diff or single file - wasteful; the scoped mode is already cheaper and more focused
- Very small sessions - the marginal context isn't worth the cost
- Very large marathon sessions - won't fit Gemini 3.1 Pro's ~1M-token input window; scope down or summarise first

### How to assemble it

There's no dedicated tooling required - **assemble the relevant files and context yourself and inline them** into the prompt:

1. **Locate the session transcript** (the conversation record for the active session).
2. **Compress it.** Drop system-reminder blocks, repeated skill-load echoes, and the bulk of large repeated tool-result bodies (keep a head + tail of each). Drop file-content tool results for files that still exist on disk - you'll attach those fresh next.
3. **Inline the working files.** For every file written/edited during the session, append its `path` plus its **current contents from disk** (disk wins over any snapshot in the transcript).
4. **Sanity-check size.** If the assembled prompt gets close to the model's input window, warn the user and offer to scope down (last N turns, only files touched recently, etc.).
5. **Send** with the standard headless invocation - the prompt will be large but the flagship model handles a large input window.

### Example assembly pattern

```bash
# Start from the compressed transcript (however you capture it), then append working files:
for f in $(git diff --name-only main...HEAD); do
  echo "# File: $f" >> /tmp/gemini-prompt.txt
  cat "$f" >> /tmp/gemini-prompt.txt
done

# Prepend both preambles + the full-context framing, then invoke:
GEMINI_API_KEY="$KEY" gemini -p "$(cat /tmp/gemini-prompt.txt)" --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

Full-context framing to include after the preambles: "You are reviewing the entire session below - what we did, why, and how. Files touched are attached as path + current contents. The verify-empirically rule still applies. Look for: decisions made on incomplete data; steps skipped that should have been verified; files left in an inconsistent state; tests not run / claims not verified; mismatches between what we said we did and what the diffs show. If the work holds up, give an evidenced per-area verdict - not a bare 'verified, no material findings'."

Note: models with a small context window can't take a full-session review - either send a digest (pre-summarise the session) or route full-context reviews to Gemini, which has the largest window of the review models.

## Multi-Model Review

For maximum coverage, run both Gemini and Codex reviews (in parallel where possible):

```bash
# Gemini pass (fast)
GEMINI_OUT=$(GEMINI_API_KEY="$KEY" gemini -p "$PROMPT" --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null)

# Codex pass (slower - usually the long pole)
CODEX_OUT=$(codex exec -s read-only -m gpt-5.5 -C "$DIR" "$PROMPT" 2>/dev/null)

# Claude synthesizes both
```

Three independent models reviewing the same code catches more issues than any single model - but only when each finds *real* issues. If they all return evidenced clean verdicts, that's a stronger signal than any one alone.

**Calibration - Gemini is the faster but shallower reviewer.** In past disagreements Gemini has under-reported where a slower, deeper reviewer caught the real bug (returning "no findings" or "safe to ship" on defects another model flagged), and it runs noticeably faster. Treat a bare Gemini "all clear" as the **weakest** single signal - never let it alone gate a ship decision; pair it with a second reviewer or the diff itself before trusting a clean pass.

## Configuration

### Model Selection

Always specify `-m gemini-3.1-pro-preview` (latest flagship). Available models:
- `gemini-3.1-pro-preview` - Latest flagship preview (always use this), ~1M-token input window
- `gemini-3-pro-preview` - Previous preview
- `gemini-2.5-pro` - Stable GA release, fallback if previews are unavailable
- `gemini-2.5-flash` / `gemini-3-flash-preview` - Faster, good for quick checks

### Google Search Grounding

Gemini CLI has built-in Google Search grounding - it can fetch real-time information during reviews. This is unique vs Codex and Claude. Useful for:
- Checking if a dependency has known CVEs
- Verifying API behaviour against current docs
- Checking if a pattern is considered best practice

The model uses search automatically when needed. No extra flags required.

### Rate Limits (Free Tier)

AI Studio API key free tier: 1,000 requests/day. Sufficient for review use cases.

## Edge Cases

- **Gemini not installed**: Install with `npm install -g @google/gemini-cli` and retry
- **API key missing**: set `GEMINI_API_KEY` in your env or fetch it from your own secret manager (see Authentication).
- **`Path not in workspace` error**: see "Files outside the workspace" above - `cd` up or inline file contents
- **`--approval-mode yolo` left stray files / unsolicited edits**: yolo auto-approves writes; `git status` the workspace after every review and discard anything you didn't ask for before committing
- **503 / UNAVAILABLE / "high demand"**: retry once after ~30s; if it still fails, surface the failure rather than guessing
- **Large codebase**: Scope to specific files/directories rather than whole-repo review
- **Gemini disagrees with Claude**: Present both perspectives - the disagreement itself is valuable signal
- **Gemini hallucinates file paths**: Cross-check all file:line references before presenting to user
- **Rate limits**: Free tier is 1,000 requests/day - space out multi-pass reviews if needed
- **Empty diff**: If reviewing uncommitted changes and there are none, tell the user and offer alternatives

## Example Invocations

```
# Quick review of uncommitted changes
/gemini-review code

# Review a specific file
/gemini-review code src/main.py

# Stress-test a decision
/gemini-review decision "Should we migrate from Firestore to PostgreSQL?"

# Critique a plan
/gemini-review plan docs/migration-plan.md

# Post-build audit
/gemini-review build

# Codebase health check for a project
/gemini-review codebase my-project

# Full-session review (whole conversation + working files)
/gemini-review build --full-context
/gemini-review decision "did we miss anything in this session?" --full-context
```
