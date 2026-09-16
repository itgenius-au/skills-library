---
name: fable-review
description: "Run a second, isolated Claude Code instance (nicknamed \"Fable\" by this skill) headless and read-only via `claude -p`, as a second-opinion reviewer for code, decisions, plans, and builds. You choose the model and reasoning effort it runs at - a deep-reasoning tier is recommended. Isolated from your host session's hooks and MCP servers, and strictly read-only. Triggers on: fable review, fable-review, review with fable, ask fable, fable check, fable audit, fable opinion, isolated claude review, second claude opinion."
argument-hint: "[mode: code|decision|plan|build|codebase] [target: file path, branch, or description]"
---

# Fable Review - Second-Opinion Code & Decision Review

Runs a **second, isolated `claude -p` process** - this skill nicknames it "Fable" - headlessly, as
an independent reviewer. Use this when you want a fresh pair of eyes, with no memory of your current
session's assumptions, catching blind spots or stress-testing a decision.

"Fable" here is just this skill's name for that isolated reviewing process, not a claim about which
model you must run. **You choose the model** - point it at whatever deep-reasoning tier your Claude
plan gives you access to. The value comes from the isolation (a clean context, no inherited
assumptions) and from running the model read-only against the live repo, not from any particular
model name.

Every call goes through a **bundled safety wrapper**, `fable-exec.sh`, that ships in this skill's own
directory. You never hand-run raw `claude -p`: the wrapper isolates the run from your host session's
hooks and MCP servers, keeps it strictly read-only, and runs a hard-timeout watchdog so a wedged run
can't eat your session.

## A note on independence

Because this second-opinion reviewer is also a Claude model, it is not as independent as swapping in
an entirely different vendor's model. It is still valuable: a fresh context window with none of your
primary session's accumulated assumptions, running fully read-only against the live repo. Just weigh
an agreement between this review and your primary session's own take as weaker evidence than an
agreement coming from an outside vendor's model - and never let your primary session grade its own
work by treating a "Fable agrees" as the only check.

## The wrapper: `fable-exec.sh` (call it, never raw `claude -p`)

This skill bundles `fable-exec.sh` in its own directory. It is a thin wrapper around headless
`claude -p` that always:

- **Lets you set the model and effort** (see Configuration below) rather than assuming a specific
  model id is available on your account. If you don't set one, it omits `--model` entirely so the run
  falls back to whatever model your `claude` CLI is already configured to use - and it prints a short
  note to stderr telling you how to point it at a stronger tier.
- **`--permission-mode plan`**: strictly READ-ONLY. The reviewer reads files and runs read-only shell
  (`git diff`, `grep`, `cat`) to **explore the repo itself**, but makes no edits to the repo under
  review (plan mode may write only a scratch plan under `~/.claude/plans`, never a project file), and
  a baked-in system prompt tells it to review, not plan.
- **`--strict-mcp-config`** (with no `--mcp-config`): loads **zero MCP servers**, so no MCP latency and
  no interactive-auth MCP prompt can wedge a headless run.
- **`--setting-sources user`**: loads only your USER settings, skipping the TARGET repo's
  PROJECT/LOCAL settings - so that repo's own hooks (a session-start reminder, an auto-commit hook,
  anything else project-scoped) do NOT fire inside the nested review. Auth and model resolution still
  work normally.
- **`< /dev/null`** so it never blocks on stdin, and **runs with cwd = `--dir`** so `git diff` / file
  reads resolve against the target repo.
- **A hard `--timeout` ceiling** (default 900s) that kills a runaway/wedged run and prints
  `::FABLE-TIMEOUT::`. There is deliberately **no first-output watchdog** (see the note below).

**Call it by its path in this skill's base directory** (the `Base directory for this skill:` path shown
when the skill loads). It is NOT on your `$PATH`:

```bash
"$SKILL_DIR/fable-exec.sh" --dir "$PROJECT_DIR" -- "$PROMPT"
```

That is the **canonical read-only review call**. `--dir` is the project directory (the wrapper `cd`s
into it), and everything after `--` is the single, quoted prompt argument.

## Mandatory invocation rules (apply to every call)

These are the rules the wrapper enforces for you. You get them for free by calling `fable-exec.sh`
instead of raw `claude -p`.

- **The run is read-only** (`--permission-mode plan`). Reviews only read. The reviewer can still run
  read-only commands like `git diff`, `cat`, `grep` under plan mode, so it explores the repo itself.
- **`--bare` is NOT used** - it skips keychain reads and breaks auth ("Not logged in"). Isolation comes
  from `--setting-sources user` + `--strict-mcp-config` instead, which keep auth working.
- **`--restricted` is NOT used** - it removes the shell tool, so the reviewer could no longer run
  `git diff` and would degrade to an inline-only reviewer that can't explore the repo itself. Plan mode
  keeps the shell AND stays read-only.

> **No first-output watchdog.** `claude -p --output-format text` emits its whole answer only at
> COMPLETION, not streamed - so "no output yet" is the normal state of a healthy review. A
> first-output watchdog would false-kill every real review. The wrapper keeps only the hard
> `--timeout` ceiling.

## When to Use

- **Code review**: review a diff, PR, file, or set of changes.
- **Decision review**: stress-test an architectural or business decision.
- **Plan review**: critique an implementation plan before building.
- **Build review**: post-build audit of what was just implemented.
- **Codebase review**: general codebase health check or a specific area deep-dive.

## Prerequisites

This reviewer needs **no API key and no separate credential** - it uses the machine's existing
Claude Code login. Just confirm `claude` is installed and signed in:

```bash
which claude || echo "install Claude Code first"
# If a review returns ::FABLE-NOAUTH::, run `claude` interactively once and sign in, then retry.
```

### Optional config

You can set a default model/effort/timeout once instead of passing flags every time. Copy
`templates/fable-review.config.example.json` to `~/.claude/fable-review.config.json` and edit it:

```json
{
  "model": "opus",
  "effort": "high",
  "timeout": 900
}
```

- `model` - any model name or alias your `claude` CLI accepts (an alias like `opus`, or a specific
  model id). Leave it out (or omit the file entirely) to fall back to whatever model your CLI already
  defaults to.
- `effort` - a reasoning-effort level your CLI supports (e.g. `low`/`medium`/`high`/`xhigh`/`max`,
  where available). `high` is a reasonable default for a real review; step up for a harder problem.
- `timeout` - hard ceiling in seconds before the wrapper kills a wedged run.

No config file, and no `jq` or `python3` to read one? The wrapper still works - it just uses the CLI's
own default model/effort and the 900s default timeout, and tells you so on stderr.

## Review preambles (include in every prompt)

Prepend BOTH blocks to every prompt you send to the reviewer. Build `$PROMPT` as
`$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA` + the mode-specific instruction.

### Empirical-verification preamble

```
BEFORE you answer, read this operating rule:

Documentation, AGENTS.md, CLAUDE.md, plan files, comments, and anything an agent
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

A high reasoning budget is for checking harder, not flagging harder.
```

## Modes

Each example builds `$PROMPT` by prepending both preamble blocks (`$EMPIRICAL_PREAMBLE` +
`$SUCCESS_CRITERIA`), then runs the wrapper.

> In every example below, **`fable-exec.sh` is shorthand for `"$SKILL_DIR/fable-exec.sh"`** - the
> wrapper bundled in THIS skill's base directory. It is NOT on your `$PATH`; always call it by that
> path (`SKILL_DIR` = the "Base directory for this skill" path shown when the skill loads).
> Canonical call: `"$SKILL_DIR/fable-exec.sh" --dir "$PROJECT_DIR" -- "$PROMPT"`.

### 1. Code Review (`code`)

Review uncommitted changes, a specific file, or a branch.

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

"$SKILL_DIR/fable-exec.sh" --dir "$PROJECT_DIR" -- "$PROMPT"
```

Variants (swap the instruction in `$PROMPT`):
- **Specific file:** "Review the file `$FILE_PATH`. Focus on correctness, security, performance, and maintainability."
- **Branch diff:** "Review changes on this branch vs main (run `git diff main...HEAD`). Focus on correctness, security, and whether the implementation matches the intent."

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

"$SKILL_DIR/fable-exec.sh" --dir "$PROJECT_DIR" -- "$PROMPT"
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
The plan describes INTENDED work - verify what the current codebase actually looks like (files, APIs, data shapes the plan references) and flag any mismatch. Be specific and constructive."

"$SKILL_DIR/fable-exec.sh" --dir "$PROJECT_DIR" -- "$PROMPT"
```

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

"$SKILL_DIR/fable-exec.sh" --dir "$PROJECT_DIR" -- "$PROMPT"
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

"$SKILL_DIR/fable-exec.sh" --dir "$PROJECT_DIR" -- "$PROMPT"
```

For a targeted area, replace the explore instruction with "Deep-dive into the `$AREA_DESCRIPTION` area".

## Workflow

### 1. Determine Mode and Target

Parse the user's request to identify the **mode** (code / decision / plan / build / codebase), the
**target** (file, branch, plan file, or inline description), and the **project directory**. If unclear,
ask. Default to `code` reviewing uncommitted changes.

### 2. Confirm Claude is signed in

```bash
which claude || echo "install Claude Code first"
```

Auth is your machine's existing Claude login. If a run returns `::FABLE-NOAUTH::`, sign in once and retry.

### 3. Build and Execute the Prompt

Construct the mode prompt (see templates), always including both preamble blocks, clear scope, focus
areas, and the instruction to cite file:line evidence. Run through the wrapper and capture output:

```bash
REVIEW_OUTPUT=$("$SKILL_DIR/fable-exec.sh" --dir "$PROJECT_DIR" -- "$PROMPT")
rc=$?   # 124 + ::FABLE-TIMEOUT:: => scope smaller / raise --timeout; 3 + ::FABLE-NOAUTH:: => sign in
```

### 3b. Handle "I need help" responses

If the reviewer says it couldn't verify something (missing access, credentials, an external system, or
context it doesn't have), treat it as a first-class finding: fetch what it asked for, then re-run with
the extra context attached. This round-trip is the whole point of the empirical-verification preamble.

### 4. Synthesize and Present

1. **Present the reviewer's findings** clearly, attributed "**Fable found:**".
2. **Add your own assessment** - agree / disagree / nuance per finding (remembering it's also a Claude
   model, so agreement is weaker independence evidence than agreement from an outside-vendor model).
3. **Highlight disagreements** - the most valuable signal.
4. **Prioritize** by severity/impact.
5. **Recommend** concrete next steps.

```
## Fable Review Results  (model: <model>, effort: <effort>)

### Findings
| # | Severity | Finding | Location | My Take |
|---|---|---|---|---|
| 1 | High | ... | file:line | Agree / Disagree / Nuance |

### Key Disagreements
[Where the primary review and Fable differ]

### Recommended Actions
1. ...
```

Then offer: fix the issues, ask the reviewer to dig deeper on one, or run another focus.

## Report the exact model (mandatory)

**Always lead your report with the exact model that ran, verbatim** - a `MODEL: <id>` line (the
`--model` you resolved and passed, or, if none was passed, the CLI's own default - check its output or
`claude --version` context if unsure). State what actually ran; never assume a pin that wasn't set.

## Configuration

### Model selection

You choose the model - there is no single correct pin. Guidance:

- If your account has a dedicated deep-reasoning tier, point this reviewer at it; that is exactly the
  kind of workload it's suited to.
- Otherwise, use the strongest general-purpose model your plan gives you (an alias like `opus`, or a
  specific model id).
- Set it once via `~/.claude/fable-review.config.json` (see Prerequisites), or per-run with
  `FABLE_REVIEW_MODEL=<model>` or `--model <model>`.
- Leave it unset to just use whatever your `claude` CLI already defaults to - a fine starting point.

### Effort

If your CLI supports a reasoning-effort flag, set it via config, `FABLE_REVIEW_EFFORT`, or `--effort`.
`high` is a reasonable default for a real review; step up (`xhigh`/`max`, where available) for a
frontier problem, or down for a quick sanity pass. A higher budget is for **checking harder, not
flagging harder**.

### Timeout

`--timeout SECS` (default 900): a hard ceiling. Exceeding it kills the run and prints
`::FABLE-TIMEOUT::`. For a large diff, scope the review to specific files/dirs rather than raising it.

### Isolation (why the wrapper is safe to nest)

`--setting-sources user` skips the target repo's project/local settings (so its hooks don't fire),
`--strict-mcp-config` loads no MCP servers, and `--permission-mode plan` blocks all writes. A plugin
that injects context at session start may still do so, but under plan mode it cannot mutate anything.

## Edge Cases

- **Not logged in (`::FABLE-NOAUTH::`, rc 3)**: `claude` has no cached session on this machine. Sign in
  interactively once, then retry. Never treat an auth failure as a clean review.
- **Hard timeout (`::FABLE-TIMEOUT::`, rc 124)**: the run exceeded `--timeout`. Scope smaller (specific
  files/dirs) or raise `--timeout`.
- **Model id rejected**: the model/alias you set isn't available on this account - try a different
  alias (`opus`, `sonnet`, etc.) or check what your plan actually includes.
- **Empty diff (code mode)**: if there are no uncommitted changes, say so and offer a branch diff, a
  specific file, or a codebase area.
- **The reviewer hallucinates a file path**: cross-check every `file:line` reference against the real
  files before surfacing it.
- **Large codebase**: scope to specific files/directories rather than a whole-repo review.
- **The reviewer disagrees with your primary session**: present both - the disagreement is valuable
  signal (with the same-vendor caveat above).

## Example Invocations

```
/fable-review code                       # review uncommitted changes
/fable-review code src/app/billing.ts    # review a specific file
/fable-review decision "Move from a relational DB to a document store?"
/fable-review plan docs/plans/2026-09-02-thing.md
/fable-review build                      # audit branch vs main
/fable-review codebase "the auth module"
```

**Always call the bundled `"$SKILL_DIR/fable-exec.sh"`** (never raw `claude -p`): it runs read-only
(plan mode), isolates hooks/MCP while keeping auth, lets you pick the model/effort, and kills a
runaway run.
