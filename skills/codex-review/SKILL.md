---
name: codex-review
description: "Use OpenAI Codex CLI as a second-opinion reviewer for code, decisions, plans, and builds. Runs Codex headlessly to get independent analysis from a different AI model, then synthesizes findings. Triggers on: codex review, second opinion, codex check, review with codex, codex audit, ask codex, cross-review, get codex opinion, rival review."
argument-hint: "[mode: code|decision|plan|build|codebase] [target: file path, branch, or description] [--full-context]"
---

# Codex Review - Second-Opinion Code & Decision Review

Runs OpenAI's Codex CLI (`codex exec`) headlessly to get independent analysis from a competing AI model (GPT-5.5). Use this when you want a second pair of eyes - a fundamentally different model reviewing your work, catching blind spots, or stress-testing decisions.

## Mandatory invocation rules (apply to every call)

Every `codex exec` call in this skill MUST include all of the following. They are the difference between a clean review and a hung or accidentally-destructive one.

- **Pin the model with `-m gpt-5.5`.** gpt-5.5 is OpenAI's current Codex flagship ("strongest for complex coding, computer use, knowledge work") and the recommended default. The CLI otherwise defaults to an older coding-tuned model, so always pin `-m gpt-5.5` so a stale config can't silently downgrade the review. The old "never pass `-m`" rule was a gpt-5.4-era OAuth bug (it broke `-m` under ChatGPT-account auth) - that bug is **resolved**; `-m gpt-5.5` now runs cleanly under ChatGPT-account OAuth. Check `developers.openai.com/codex/models` for newer flagships.
- **Redirect stdin with `< /dev/null`.** `codex exec` reads stdin for additional prompt context and blocks waiting for EOF if stdin isn't closed. From a non-interactive parent (scripts, CI, an agent's shell tool) stdin is not auto-closed, so the process hangs indefinitely with no output (stderr shows `Reading additional input from stdin...`). Append `< /dev/null` to every invocation. This is the single most common source of "Codex is hung" reports.
- **Pass `--skip-git-repo-check` when `-C` points at a non-git directory** (e.g. a skills folder or any path outside a checkout). Without it: `Not inside a trusted directory and --skip-git-repo-check was not specified`. Inside a normal git repo it's a no-op, so it's safe to include by default when you're unsure.
- **Default the sandbox to read-only (`-s read-only`).** `--full-auto` is **deprecated** (Codex >= 0.139 warns `--full-auto is deprecated; use --sandbox workspace-write instead` and may stop being accepted). Reviews only read, so `-s read-only` is the correct, safest tier - Codex can still run read-only commands like `git diff`, `cat`, `grep` under it. Only widen the sandbox when the review must actually run tests or hit the network (see the Sandbox decision tree under Configuration).
- **Use `codex exec`, never bare `codex`** - bare `codex` requires a TTY and errors with `stdin is not a terminal` from non-interactive parents.

Canonical call (read-only review):

```bash
codex exec -m gpt-5.5 -s read-only --skip-git-repo-check -C "$PROJECT_DIR" "$PROMPT" < /dev/null
```

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

## Review preambles (include in every prompt)

Prepend BOTH blocks to every prompt you send to Codex. Build `$PROMPT` as `$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA` + the mode-specific instruction. They are what turn a fast, plausible-sounding answer into a grounded, evidenced one.

### Empirical-verification preamble

Documentation (AGENTS.md, READMEs, plan files, comments) describes *intent* - it rots, drifts, and sometimes lies. A review grounded in stale docs is worse than no review: it confidently repeats fiction. Tell Codex to treat every doc claim as a hypothesis to verify against the live system, and to ask for what it needs rather than guess.

```
BEFORE you answer, read this operating rule:

Documentation, AGENTS.md, plan files, comments, and anything an agent
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

### Success-criteria / evidenced-verdict preamble

A review's success criterion is "the reviewer checked every claim end-to-end and the work stood up to it", not "the reviewer returned N findings". A high reasoning budget is for **checking harder, not flagging harder** - models are especially good at producing plausible-but-wrong issues if they think findings are the expected output. A clean "no material findings" is a valid, valuable outcome, but it must be reported with evidence, not a bare phrase.

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

## Modes

Each example builds `$PROMPT` by prepending both preamble blocks (`$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA`), then runs the canonical read-only call. Default every review to `-s read-only`; only widen the sandbox for a review that must run the test suite or reach the network (see the Sandbox decision tree).

### 1. Code Review (`code`)

Review specific files, diffs, or branches against main.

```bash
PROMPT="$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Review the uncommitted changes (run git diff). Focus on:
- Correctness and edge cases
- Security vulnerabilities
- Performance issues
- Code style and maintainability (only if it actively harms correctness)
Report issues with file:line references. Be direct - no fluff.
Cite the exact evidence (file:line, command output) behind each finding."

codex exec -m gpt-5.5 -s read-only --skip-git-repo-check -C "$PROJECT_DIR" "$PROMPT" < /dev/null
```

Variants (swap the instruction in `$PROMPT`):
- **Specific file:** "Review the file `$FILE_PATH`. Focus on correctness, security, performance, and maintainability."
- **Branch diff:** "Review changes on this branch vs main (run `git diff main...HEAD`). Focus on correctness, security, and whether the implementation matches the intent."
- **Run the tests too:** bump the sandbox to `--sandbox workspace-write` (add `-c 'sandbox_workspace_write.network_access=true'` if the suite needs the network) so Codex can execute the suite, not just read the diff.

### 2. Decision Review (`decision`)

Stress-test an architectural, technical, or business decision.

```bash
PROMPT="$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

I'm considering the following decision:

$DECISION_DESCRIPTION

Context:
$CONTEXT

Play devil's advocate. What are the risks? What could go wrong? What alternatives should I consider? What am I not thinking about? Be blunt and direct.
If after thorough checking the decision holds up, say so plainly rather than manufacturing weak counter-arguments."

codex exec -m gpt-5.5 -s read-only --skip-git-repo-check -C "$PROJECT_DIR" "$PROMPT" < /dev/null
```

### 3. Plan Review (`plan`)

Critique an implementation plan before building.

```bash
PROMPT="$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Read the plan at $PLAN_FILE_PATH and critique it. Consider:
- Is the approach sound? Are there better alternatives?
- What's missing or underspecified?
- What are the riskiest parts?
- Is the sequencing right? Any dependency issues?
- Is it over-engineered or under-engineered?
Be specific and constructive."

codex exec -m gpt-5.5 -s read-only --skip-git-repo-check -C "$PROJECT_DIR" "$PROMPT" < /dev/null
```

For an inline plan, replace the "Read the plan at..." line with the plan text and ask Codex to consider soundness, completeness, risks, sequencing, and complexity.

### 4. Build Review (`build`)

Post-implementation audit of what was just built.

```bash
PROMPT="$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Audit the recent changes on this branch (run git log --oneline -20 and git diff main...HEAD).
Review what was built and assess:
- Does the implementation look correct and complete?
- Any bugs, edge cases, or security issues?
- Is the code well-structured and maintainable?
- Anything that should be refactored before merging?
- Are there missing tests or error handling?
Be thorough but prioritize actionable findings."

# Read-only audit of the diff/log:
codex exec -m gpt-5.5 -s read-only --skip-git-repo-check -C "$PROJECT_DIR" "$PROMPT" < /dev/null
# To run the test suite as part of the audit, bump to --sandbox workspace-write (add network if the suite needs it).
```

### 5. Codebase Review (`codebase`)

General health check or deep-dive into a specific area.

```bash
PROMPT="$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Explore this codebase. Understand the architecture, then provide:
- Overall assessment of code quality and organization
- Top 5 areas of concern (bugs, security, tech debt) - only with evidence
- Specific recommendations with file:line references
Focus on actionable findings, not style nitpicks."

codex exec -m gpt-5.5 -s read-only --skip-git-repo-check -C "$PROJECT_DIR" "$PROMPT" < /dev/null
```

For a targeted area, replace the explore instruction with "Deep-dive into the `$AREA_DESCRIPTION` area" and ask for correctness, security, performance, and test-coverage gaps with file:line references.

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

### 3. Check for AGENTS.md

Check if `AGENTS.md` exists in the target project directory. This file gives Codex project-specific context (like CLAUDE.md does for Claude).

- If it exists: Codex will pick it up automatically
- If it does not exist: Warn once: "No AGENTS.md found in this project. Codex will work without project context. Want me to create one based on CLAUDE.md?"
- If the user says yes: Read the project's CLAUDE.md and craft an AGENTS.md adapted for Codex's conventions. Don't block the review - create it after.

### 4. Build and Execute the Prompt

Construct the appropriate prompt based on mode (see templates above). Always include:
- Both preamble blocks (`$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA`)
- Clear scope (what to review)
- Specific focus areas
- Instruction to be direct and cite file:line references
- The project directory via `-C`

Run headlessly and capture output:

```bash
CODEX_OUTPUT=$(codex exec -m gpt-5.5 -s read-only --skip-git-repo-check -C "$PROJECT_DIR" "$PROMPT" < /dev/null 2>/dev/null)
```

### 4b. Handle Codex's "I need help" responses

If Codex's output says it couldn't verify something - missing access, credentials, an external system it can't reach, or context it doesn't have - **do not suppress or paper over that**. Treat it as a first-class finding:

- Read what Codex asked for.
- Fetch the credential, grant the access, pull the log/config/dashboard, or supply the missing context.
- Re-run Codex with the extra information attached to the prompt.

This round-trip is the whole point of the empirical-verification preamble. Guessed answers are worse than "I don't know, here's what I need."

### 5. Synthesize and Present

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

### 6. Interactive Follow-up

After presenting results, offer:
- "Want me to fix any of these issues?"
- "Want me to ask Codex to dig deeper into any specific finding?"
- "Want me to run another review with a different focus?"

For follow-up questions to Codex, you can run additional `codex exec` calls targeting specific areas.

## Multi-Turn Review Sessions

For complex reviews, run multiple Codex passes:

```bash
# Pass 1: High-level review
PASS1=$(codex exec -m gpt-5.5 -s read-only --skip-git-repo-check -C "$DIR" "Review the codebase architecture and flag top concerns" < /dev/null 2>/dev/null)

# Pass 2: Deep-dive on concerns from Pass 1
PASS2=$(codex exec -m gpt-5.5 -s read-only --skip-git-repo-check -C "$DIR" "Focus on these specific areas: $CONCERNS_FROM_PASS1. Provide detailed analysis with code examples." < /dev/null 2>/dev/null)

# Pass 3: Security-specific
PASS3=$(codex exec -m gpt-5.5 -s read-only --skip-git-repo-check -C "$DIR" "Security audit: check for injection, auth bypass, data exposure, SSRF, and other OWASP top 10 issues." < /dev/null 2>/dev/null)
```

## Configuration

### Model Selection

**Pin `-m gpt-5.5`.** gpt-5.5 is OpenAI's current Codex flagship - "strongest for complex coding, computer use, knowledge work" - and the recommended default (`developers.openai.com/codex/models`). The CLI otherwise defaults to an older coding-tuned model, so pin `-m gpt-5.5` so a stale config can't silently run an older model. The CLI header shows `model: gpt-5.5` when running correctly.

The old "never pass `-m`" rule was a gpt-5.4-era OAuth bug that broke `-m` under ChatGPT-account auth - that bug is **resolved**; `-m gpt-5.5` now runs cleanly under ChatGPT-account OAuth. The lineup (`developers.openai.com/codex/models`): `gpt-5.5` (newest frontier, recommended), `gpt-5.4` / `gpt-5.4-mini`, and coding-specialised variants `gpt-5.3-codex` / `gpt-5.3-codex-spark`. The `-codex` variants are an older base (5.3) than 5.5 - prefer `gpt-5.5` unless a task specifically benefits from a coding-tuned variant.

### Timeout

`codex exec` runs until completion with no ceiling. For large codebases, scope the review to specific directories/files to keep runtime reasonable. Watch for a **wedged handshake**: if `codex exec` produces no output at all within ~60-90s, the model/auth handshake is wedged, not slow - kill it and relaunch attached (foreground) so the startup failure is visible, rather than passively waiting on a background run that may never complete.

### Sandbox decision tree

Codex has two independent dials: the **sandbox** (`-s` - what a command is physically allowed to do) and **approval** (when it pauses to ask). The old `--full-auto` bundled `workspace-write` + auto-approval, but it is **deprecated** (Codex >= 0.139 warns `--full-auto is deprecated; use --sandbox workspace-write instead`). Pick the sandbox explicitly:

| Tier | Sandbox flag | Can write | Network | Use for |
|---|---|---|---|---|
| read-only (default) | `-s read-only` | no (read-only cmds like `git diff` still run) | no | code / decision / plan / codebase / build review - inspection only |
| workspace-write | `--sandbox workspace-write` | cwd + `/tmp` | no | run no-network unit tests, write scratch |
| workspace-write + net | `--sandbox workspace-write -c 'sandbox_workspace_write.network_access=true'` | cwd + `/tmp` | yes | run the full suite/build that needs the network |
| danger-full-access | `-s danger-full-access` | anywhere | yes | last resort: suite also writes outside the workspace |

**Default to `read-only`.** It is the safest tier and prevents an entire class of accident: a review running with write access can accidentally mutate the very repo it is reviewing (a setup or migration script triggered mid-review has corrupted repos this way). read-only makes that structurally impossible, and Codex can still run `git diff`, `cat`, `grep` under it, so most reviews never need to leave it.

> **A sandbox denial is NOT a code bug.** When you run tests under a tighter tier and a command fails with `Could not resolve host` / `Failed to resolve '...googleapis.com'` / `Connection refused` / `Operation not permitted` / `Read-only file system`, that is the **sandbox** blocking it, not a defect in the code under review. Do not surface it as a finding. Either re-run at a looser tier (`--sandbox workspace-write` for scratch/tests, add network access for live calls, `-s danger-full-access` for out-of-workspace writes) or note it as "blocked by sandbox, not verified".

**When to go past read-only:** bump to `workspace-write` for any review that must run the suite or hit live APIs, remotes, public URLs (`curl`), or DNS - i.e. prompts mentioning `live`, `verify`, `audit`, `API`, `logs`, `production state`. Pure code/plan critique stays at `read-only`.

**Scratch-file footgun:** any write-capable tier (`workspace-write` / `danger-full-access`) lets Codex write files into the review directory. If that repo has an auto-commit hook, those scratch files can be committed as a `wip` and pushed to a shared branch. Prefer `-s read-only` when no file writes are intended. If you must use a write tier, tell Codex in the prompt to write scratch to `/tmp`, and `git status` the review repo afterward before any commit or push.

### Skip-git-repo-check

`-C` directories that aren't a git checkout require `--skip-git-repo-check`; inside a normal git repo it's a no-op, so include it by default. Raw form:

```bash
codex exec -m gpt-5.5 -s read-only --skip-git-repo-check -C "$DIR" "$PROMPT" < /dev/null
```

## `--full-context` flag (any mode)

Codex's CLI context window is too small for a full agent-session transcript. `--full-context` on Codex therefore works off a digest, not the raw transcript:

1. **Build a digest first.** Pre-summarise the session into a structured digest - high-level intent, decisions made, files touched (with current contents inlined), commands run, verification done, and any unresolved items.
2. **Pass the digest as the primary context.** Codex reviews the digest + scoped artefacts (diff, plan file, etc.), not the raw transcript.
3. **If the digest can't fit Codex's window** (rare, only on very long sessions): refuse the flag rather than silently truncating - scope the review down instead.

Codex sees a curated picture of the session rather than the raw transcript. That's a feature when the session is mostly noise; a bug when the failure mode you're hunting is in the noise. For raw-transcript full-context reviews, prefer a model with a larger context window.

## Edge Cases

- **Codex not installed**: `npm install -g @openai/codex`
- **Auth expired**: `codex login` to re-authenticate via browser OAuth
- **`stdin is not a terminal`**: you ran bare `codex` instead of `codex exec` - switch to `codex exec`
- **`Reading additional input from stdin...` hangs**: missing `< /dev/null` - see Mandatory invocation rules
- **`Not inside a trusted directory`**: missing `--skip-git-repo-check` - see Mandatory invocation rules
- **`Could not resolve host` / `Operation not permitted` / `Read-only file system` mid-review**: the **sandbox** blocked it, not a code bug. Re-run at `--sandbox workspace-write` (add network) or `-s danger-full-access`; see the Sandbox decision tree. Never report a sandbox denial as a finding.
- **Wedged with no output**: model/auth **handshake hang**. If nothing appears in ~60-90s, kill it and relaunch attached - it is wedged, not slow. Never passively wait on a background `codex exec`.
- **`model not supported when using Codex with a ChatGPT account`**: the model name you passed isn't available on the ChatGPT-account auth path (e.g. an API-only or retired slug). Use `-m gpt-5.5`.
- **Large codebase**: scope to specific files/directories rather than whole-repo review
- **Codex disagrees with Claude**: present both perspectives - the disagreement itself is valuable signal
- **Codex hallucinates file paths**: cross-check all `file:line` references before presenting to user
- **Rate limits**: space out multiple passes with brief delays if hitting OpenAI rate limits
- **Empty diff**: if reviewing uncommitted changes and there are none, tell the user and offer alternatives (branch diff, specific file, codebase review)

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

# Full-context review (Codex sees a digest, not the raw transcript)
/codex-review build --full-context
```

**Pin `-m gpt-5.5`** (current Codex flagship) - see Mandatory invocation rules above.
