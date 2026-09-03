---
name: codex-review
description: "Use OpenAI Codex CLI as a second-opinion reviewer for code, decisions, plans, and builds. Runs Codex headlessly to get independent analysis from a different AI model, then synthesizes findings. Triggers on: codex review, second opinion, codex check, review with codex, codex audit, ask codex, cross-review, get codex opinion, rival review."
argument-hint: "[mode: code|decision|plan|build|codebase] [target: file path, branch, or description]"
---

# Codex Review - Second-Opinion Code & Decision Review

Runs OpenAI's Codex CLI (`codex exec`) headlessly to get independent analysis from a competing AI model (GPT-5.4). Use this when you want a second pair of eyes - a fundamentally different model reviewing your work, catching blind spots, or stress-testing decisions.

**Use the Codex CLI's current flagship model.** At time of writing that is `-m gpt-5.4` (the CLI otherwise defaults to a code-tuned model such as `gpt-5.3-codex`). Check `codex --help` or OpenAI's model list for the current flagship.

## When to Use

- **Code review**: Get Codex to review a diff, PR, file, or set of changes
- **Decision review**: Stress-test an architectural or business decision
- **Plan review**: Have Codex critique an implementation plan before building
- **Build review**: Post-build audit of what was just implemented
- **Codebase review**: General codebase health check or specific area deep-dive

## Prerequisites

### Install Codex CLI

```bash
npm install -g @openai/codex
```

### Authentication

Codex uses your ChatGPT account via OAuth (cached at `~/.codex/auth.json`). No API key needed.

If auth expires, re-authenticate:

```bash
codex login
```

## Modes

### 1. Code Review (`code`)

Review specific files, diffs, or branches against main.

```bash
# Review uncommitted changes
codex exec --full-auto -m gpt-5.4 -C "$PROJECT_DIR" \
  "Review the uncommitted changes (run git diff). Focus on:
   - Correctness and edge cases
   - Security vulnerabilities
   - Performance issues
   - Code style and maintainability
   Report issues with file:line references. Be direct - no fluff."

# Review a specific file
codex exec --full-auto -m gpt-5.4 -C "$PROJECT_DIR" \
  "Review the file $FILE_PATH. Focus on correctness, security, performance, and maintainability. Report issues with line references."

# Review branch diff against main
codex exec --full-auto -m gpt-5.4 -C "$PROJECT_DIR" \
  "Review changes on this branch vs main (run git diff main...HEAD). Focus on correctness, security, and whether the implementation matches the intent. Be critical."
```

### 2. Decision Review (`decision`)

Stress-test an architectural, technical, or business decision.

```bash
codex exec --full-auto -m gpt-5.4 -C "$PROJECT_DIR" \
  "I'm considering the following decision:

$DECISION_DESCRIPTION

Context:
$CONTEXT

Play devil's advocate. What are the risks? What could go wrong? What alternatives should I consider? What am I not thinking about? Be blunt and direct."
```

### 3. Plan Review (`plan`)

Critique an implementation plan before building.

```bash
# Review a plan file
codex exec --full-auto -m gpt-5.4 -C "$PROJECT_DIR" \
  "Read the plan at $PLAN_FILE_PATH and critique it. Consider:
   - Is the approach sound? Are there better alternatives?
   - What's missing or underspecified?
   - What are the riskiest parts?
   - Is the sequencing right? Any dependency issues?
   - Is it over-engineered or under-engineered?
   Be specific and constructive."

# Review a plan described inline
codex exec --full-auto -m gpt-5.4 -C "$PROJECT_DIR" \
  "Critique this implementation plan:

$PLAN_DESCRIPTION

Consider soundness, completeness, risks, sequencing, and complexity. Be specific."
```

### 4. Build Review (`build`)

Post-implementation audit of what was just built.

```bash
codex exec --full-auto -m gpt-5.4 -C "$PROJECT_DIR" \
  "Audit the recent changes on this branch (run git log --oneline -20 and git diff main...HEAD).
   Review what was built and assess:
   - Does the implementation look correct and complete?
   - Any bugs, edge cases, or security issues?
   - Is the code well-structured and maintainable?
   - Anything that should be refactored before merging?
   - Are there missing tests or error handling?
   Be thorough but prioritize actionable findings."
```

### 5. Codebase Review (`codebase`)

General health check or deep-dive into a specific area.

```bash
# General health check
codex exec --full-auto -m gpt-5.4 -C "$PROJECT_DIR" \
  "Explore this codebase. Understand the architecture, then provide:
   - Overall assessment of code quality and organization
   - Top 5 areas of concern (bugs, security, tech debt)
   - Specific recommendations with file:line references
   Focus on actionable findings, not style nitpicks."

# Targeted area review
codex exec --full-auto -m gpt-5.4 -C "$PROJECT_DIR" \
  "Deep-dive into the $AREA_DESCRIPTION area of this codebase.
   Review all relevant files and assess:
   - Correctness and edge cases
   - Security posture
   - Performance characteristics
   - Test coverage gaps
   Be specific with file:line references."
```

## Workflow

### 1. Determine Mode and Target

Parse the user's request to identify:
- **Mode**: code, decision, plan, build, or codebase
- **Target**: file path, branch name, plan file, or inline description
- **Project directory**: Which project or repo

If unclear, ask the user. Default to `code` mode reviewing uncommitted changes.

### 2. Set Up Environment

```bash
# Verify codex is installed and authenticated
which codex || npm install -g @openai/codex
```

Auth is handled via cached OAuth session (`~/.codex/auth.json`). If auth fails, run `codex login`.

### 3. Build and Execute the Prompt

Construct the appropriate prompt based on mode (see templates above). Always include:
- Clear scope (what to review)
- Specific focus areas
- Instruction to be direct and cite file:line references
- The project directory via `-C`

Run with `--full-auto` for headless operation. Capture output:

```bash
CODEX_OUTPUT=$(codex exec --full-auto -m gpt-5.4 -C "$PROJECT_DIR" "$PROMPT" 2>/dev/null)
```

### 4. Synthesize and Present

After receiving Codex's output:

1. **Present Codex's findings** clearly, attributed as "Codex found:"
2. **Add your own assessment** - agree, disagree, or add nuance to each finding
3. **Highlight disagreements** - where Claude and Codex see things differently, this is the most valuable signal
4. **Prioritize** - rank findings by severity/impact
5. **Recommend actions** - concrete next steps based on the combined review

Format the output as:

```
## Codex Review Results

### Findings

| # | Severity | Finding | Location | Claude's Take |
|---|---|---|---|---|
| 1 | High | ... | file:line | Agree / Disagree / Nuance |

### Key Disagreements
[Where Claude and Codex see things differently]

### Recommended Actions
1. ...
2. ...
```

### 5. Interactive Follow-up

After presenting results, offer:
- "Want me to fix any of these issues?"
- "Want me to ask Codex to dig deeper into any specific finding?"
- "Want me to run another review with a different focus?"

For follow-up questions to Codex, you can run additional `codex exec` calls targeting specific areas.

## Multi-Turn Review Sessions

For complex reviews, run multiple Codex passes:

```bash
# Pass 1: High-level review
PASS1=$(codex exec --full-auto -m gpt-5.4 -C "$DIR" "Review the codebase architecture and flag top concerns" 2>/dev/null)

# Pass 2: Deep-dive on concerns from Pass 1
PASS2=$(codex exec --full-auto -m gpt-5.4 -C "$DIR" "Focus on these specific areas: $CONCERNS_FROM_PASS1. Provide detailed analysis with code examples." 2>/dev/null)

# Pass 3: Security-specific
PASS3=$(codex exec --full-auto -m gpt-5.4 -C "$DIR" "Security audit: check for injection, auth bypass, data exposure, SSRF, and other OWASP top 10 issues." 2>/dev/null)
```

## Configuration

### Model Selection

This skill always specifies `-m gpt-5.4` (flagship). The CLI defaults to `gpt-5.3-codex` if not specified. Override for specific use cases:

Available models:
- `gpt-5.4` - Flagship frontier model (example; use the current flagship)
- `gpt-5.3-codex` - Optimised for pure code tasks (CLI default)
- `gpt-5.3-codex-spark` - Fastest, good for quick checks (Pro plan only)

### Timeout

Codex exec runs until completion by default. For large codebases, consider scoping the review to specific directories or files to keep runtime reasonable (under 2 minutes).

### Sandbox

`--full-auto` uses `workspace-write` sandbox with auto-approval. Since we're only reading (reviewing), this is safe. For pure read-only:

```bash
codex exec -s read-only -C "$DIR" "$PROMPT"
```

## Edge Cases

- **Codex not installed**: Install with `npm install -g @openai/codex` and retry
- **Auth expired**: Run `codex login` to re-authenticate via browser OAuth
- **Large codebase**: Scope to specific files/directories rather than whole-repo review
- **Codex disagrees with Claude**: Present both perspectives - the disagreement itself is valuable signal
- **Codex hallucinates file paths**: Cross-check all file:line references before presenting to user
- **Rate limits**: Space out multiple passes with brief delays if hitting OpenAI rate limits
- **Empty diff**: If reviewing uncommitted changes and there are none, tell the user and offer alternatives (branch diff, specific file, codebase review)

## Example Invocations

```
# Quick review of uncommitted changes
/codex-review code

# Review a specific file
/codex-review code src/main.py

# Stress-test a decision
/codex-review decision "Should we migrate from Firestore to PostgreSQL?"

# Critique a plan
/codex-review plan docs/migration-plan.md

# Post-build audit
/codex-review build

# Codebase health check for a project
/codex-review codebase my-project

# Review with a specific model
/codex-review code --model gpt-5.3-codex
```
