---
name: gemini-review
description: "Use Google Gemini CLI as a second-opinion reviewer for code, decisions, plans, and builds. Runs Gemini headlessly to get independent analysis from a different AI model, then synthesizes findings. Triggers on: gemini review, gemini check, review with gemini, gemini audit, ask gemini, gemini opinion, google review."
argument-hint: "[mode: code|decision|plan|build|codebase] [target: file path, branch, or description]"
---

# Gemini Review - Second-Opinion Code & Decision Review

Runs Google's Gemini CLI (`gemini -p`) headlessly to get independent analysis from Gemini 3.1 Pro. Use this when you want a second pair of eyes - a fundamentally different model reviewing your work, catching blind spots, or stress-testing decisions.

**Use the Gemini CLI's current flagship model.** At time of writing that is `-m gemini-3.1-pro-preview`; fall back to a stable release such as `gemini-2.5-pro`. Check the CLI or Google's model list for the current flagship.

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

Get a Gemini API key from Google AI Studio. Provide it as an env var (from your own secret manager or shell):

```bash
export GEMINI_API_KEY=...   # e.g. loaded from your secret manager
```

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

## Modes

### 1. Code Review (`code`)

```bash
GEMINI_API_KEY="$KEY" gemini -p \
  "Review the uncommitted changes in this repo (run git diff). Focus on:
   - Correctness and edge cases
   - Security vulnerabilities
   - Performance issues
   - Code style and maintainability
   Report issues with file:line references. Be direct - no fluff." \
  --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

Variants:
- Review a specific file: replace git diff instruction with "Review the file $FILE_PATH"
- Review branch diff: "Review changes on this branch vs main (run git diff main...HEAD)"

### 2. Decision Review (`decision`)

```bash
GEMINI_API_KEY="$KEY" gemini -p \
  "I'm considering the following decision:

$DECISION_DESCRIPTION

Context:
$CONTEXT

Play devil's advocate. What are the risks? What could go wrong? What alternatives should I consider? What am I not thinking about? Be blunt and direct." \
  --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

### 3. Plan Review (`plan`)

```bash
GEMINI_API_KEY="$KEY" gemini -p \
  "Read the plan at $PLAN_FILE_PATH and critique it. Consider:
   - Is the approach sound? Are there better alternatives?
   - What's missing or underspecified?
   - What are the riskiest parts?
   - Is the sequencing right? Any dependency issues?
   - Is it over-engineered or under-engineered?
   Be specific and constructive." \
  --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

### 4. Build Review (`build`)

```bash
GEMINI_API_KEY="$KEY" gemini -p \
  "Audit the recent changes on this branch (run git log --oneline -20 and git diff main...HEAD).
   Review what was built and assess:
   - Does the implementation look correct and complete?
   - Any bugs, edge cases, or security issues?
   - Is the code well-structured and maintainable?
   - Anything that should be refactored before merging?
   - Are there missing tests or error handling?
   Be thorough but prioritize actionable findings." \
  --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null
```

### 5. Codebase Review (`codebase`)

```bash
# General health check
GEMINI_API_KEY="$KEY" gemini -p \
  "Explore this codebase. Understand the architecture, then provide:
   - Overall assessment of code quality and organization
   - Top 5 areas of concern (bugs, security, tech debt)
   - Specific recommendations with file:line references
   Focus on actionable findings, not style nitpicks." \
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

```bash
export GEMINI_API_KEY=...   # from your own secret manager or shell
```

### 3. Build and Execute the Prompt

Construct the appropriate prompt based on mode (see templates above). Always include:
- Clear scope (what to review)
- Specific focus areas
- Instruction to be direct and cite file:line references

Run headlessly and capture output:

```bash
GEMINI_OUTPUT=$(GEMINI_API_KEY="$KEY" gemini -p "$PROMPT" --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null)
```

Note: Gemini CLI uses the current working directory as its workspace. `cd` into the target project directory before running.

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

## Multi-Model Review

For maximum coverage, run both Gemini and Codex reviews:

```bash
# Gemini pass
GEMINI_OUT=$(GEMINI_API_KEY="$KEY" gemini -p "$PROMPT" --approval-mode yolo -m gemini-3.1-pro-preview -o text 2>/dev/null)

# Codex pass
CODEX_OUT=$(codex exec --full-auto -m gpt-5.4 -C "$DIR" "$PROMPT" 2>/dev/null)

# Claude synthesizes both
```

Three independent models reviewing the same code catches more issues than any single model.

## Configuration

### Model Selection

Always specify `-m gemini-3.1-pro-preview` (latest flagship). Available models:
- `gemini-3.1-pro-preview` - Latest flagship preview (always use this)
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
- **API key missing**: Set `GEMINI_API_KEY` from your own secret manager or shell
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
```
