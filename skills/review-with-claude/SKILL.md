---
name: review-with-claude
description: "Run a second, isolated Claude Code instance (nicknamed \"Fable\" by this skill) headless and read-only via `claude -p`, as a deep-reasoning second-opinion reviewer for code, decisions, plans, and builds. You choose the model and reasoning effort it runs at - a Fable-tier or other deep-reasoning model is recommended. Isolated from your host session's hooks and MCP servers, and given no shell at all. The Claude-family leg of the review swarm. Triggers on: fable review, review with claude, review-with-claude, review with fable, ask fable, fable check, fable audit, fable opinion, isolated claude review, second claude opinion, deep review with fable."
argument-hint: "[mode: code|decision|plan|build|codebase] [target: file path, branch, or description] [--full-context]"
---

# Review with Claude (Fable) - Second-Opinion Code & Decision Review

Runs a **second, isolated `claude -p` process** - this skill nicknames it "Fable" - headlessly, as an independent reviewer. Use this when you want a deep-reasoning second pair of eyes, with no memory of your current session's assumptions, catching blind spots or stress-testing a decision. It is the Claude-family leg of the `review-swarm` panel alongside Codex (GPT), Gemini, and GLM.

"Fable" here is this skill's name for that isolated reviewing process. **You choose the model**: point it at the strongest deep-reasoning tier your Claude plan gives you (a Fable-tier model if you have one, otherwise your best general model). The value comes from the isolation (a clean context, no inherited assumptions), from the reasoning budget, and from running read-only against the live repo.

Every call goes through a **bundled safety wrapper**, `fable-exec.sh`, that ships in this skill's own directory. You never hand-run raw `claude -p`: the wrapper encodes the mandatory invocation rules in one place, applies your model and effort, forces any sub-agent onto a cheap model, isolates the run from the host project's hooks and MCP servers, gives the reviewer no shell, and runs a hard-timeout watchdog so a wedged run can't eat the session.

## Fable is Claude-family - what that means for the panel

This reviewer is an Anthropic model, so it is NOT "external" the way Codex, Gemini, and GLM are. It runs as a **separate `claude -p` process**, isolated from the orchestrator, so it is a genuinely independent opinion - but it is the same vendor/family as a Claude orchestrator. Weight it accordingly: it is a strong deep-reasoning reviewer and a valuable fourth vote, but a finding that agrees with the Claude orchestrator is weaker evidence of independence than one from an outside model. The orchestrator still never grades its own output.

## The wrapper: `fable-exec.sh` (call it, never raw `claude -p`)

It is a thin wrapper around headless `claude -p` that always:

- **Applies your model and effort** (see Configuration). It never hard-codes a model id that might not exist on your account. If you set none, it omits `--model` so the run uses your `claude` CLI's default, and prints a note to stderr. The effort default is `high`; step up to `xhigh` through the **effort gate** below. The reasoning budget is for **checking harder, not flagging harder**.
- **`--tools Read,Grep,Glob`: no shell.** The reviewer still **explores the repo itself** with Read, Grep and Glob - self-exploring like Codex/Gemini, NOT inline-only like GLM - but it cannot run a command, write a file or spawn a sub-agent. `--permission-mode plan` stays as a second layer (a baked-in system prompt also tells it to review, not plan). Plan mode alone is only an instruction to the model: a plan-mode run once executed a script that emptied a file outside `--dir`.
- **`--diff-range RANGE`**: the reviewer has no shell, so the wrapper runs git for it. `RANGE` is what `git diff` takes: `main...HEAD`, `<sha>..HEAD`, or `HEAD` for uncommitted changes. In `--dir`, the wrapper runs `git status --short`, `git log --oneline` (ranges with `..` only) and `git diff --no-ext-diff --no-textconv RANGE`, with the repo config's program hooks disabled and no network. It writes the output to a temp file, adds that directory with `--add-dir`, and names the file in the prompt. A bad range exits 2 before any model call.
- **Sub-agent backstop.** The wrapper sets `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1`, so any sub-agent a future change allows would run on a cheap model.
- **`--strict-mcp-config`** (with no `--mcp-config`): loads **zero MCP servers**, so no MCP latency and no interactive-auth MCP prompt can wedge a headless run.
- **`--setting-sources user`**: loads only YOUR user settings, skipping the TARGET repo's project/local settings - so that repo's own hooks (a session-start reminder, an auto-commit hook) do NOT fire inside the nested review. Auth and model resolution still work normally.
- **`< /dev/null`** so it never blocks on stdin, and **runs with cwd = `--dir`** so file reads resolve against the target repo.
- **A hard `--timeout` ceiling** (default 720 s at `high` or lower, 1500 s at `xhigh`/`max`) that kills a runaway/wedged run and prints `::FABLE-TIMEOUT::`. There is deliberately **no first-output watchdog** (see the note below).

**Call it by its path in this skill's base directory** (the `Base directory for this skill:` path shown when the skill loads). It is NOT on your `$PATH`.

## Invocation form (works in restrictive agent harnesses)

Some agent harnesses refuse a Bash command that contains a `$(...)` or backtick substitution, a variable assigned from command output, `export VAR=...`, a variable used as the command name, a heredoc, a `for`/`while` loop, or `bash -c "..."`. Claude Code does this in a git-worktree session. A literal absolute script path with literal arguments and a plain `>` redirect always passes, so use this form for every invocation:

1. Write the prompt with your editor/Write tool to a file in a scratch directory **outside the repo under review**. Do not build the prompt in the shell. Keeping scratch files out of the tree also avoids a footgun: the wrapper isolates the NESTED run from the target repo's hooks, but the CALLING session's own auto-commit hook can still commit any file left in that tree.
2. Run the wrapper as ONE plain command. Every path is a **literal absolute path** you paste in, never a shell variable.
3. Read the output file.

Placeholders used in every example below:
- `<SKILL_DIR>` = this skill's base directory path, pasted literally. Not `$SKILL_DIR`.
- `<SCRATCH>` = a scratch directory for prompts and outputs, pasted literally.
- `<PROJECT_DIR>` = the absolute path of the repo (or review snapshot) under review.
- `<RANGE>` = the diff range for `--diff-range`: `main...HEAD`, `<sha>..HEAD`, or `HEAD` for uncommitted changes.

`--prompt-file` and `-- PROMPT` are alternatives (passing both exits 2); a missing or empty prompt file exits 2; a prompt over ~131000 bytes exits 2 (keep large input in a file the reviewer reads instead of pasting it into the prompt).

**Canonical read-only review call:**

```bash
<SKILL_DIR>/fable-exec.sh --dir <PROJECT_DIR> --prompt-file <SCRATCH>/fable-prompt.txt > <SCRATCH>/fable-out.txt 2>&1
```

**Diff form** (use it for any code or branch review):

```bash
<SKILL_DIR>/fable-exec.sh --dir <PROJECT_DIR> --diff-range <RANGE> --prompt-file <SCRATCH>/fable-prompt.txt > <SCRATCH>/fable-out.txt 2>&1
```

## Mandatory invocation rules (apply to every call)

These are the rules the wrapper enforces for you. You get them for free by calling `fable-exec.sh` instead of raw `claude -p`.

- **Effort gate: `high` by default, `xhigh` for high-risk subjects.** Pass `--effort xhigh` when the subject touches ANY of:
  - **authorization**: authn/authz, IAM, roles, permissions, sessions, tokens, access checks;
  - **migrations**: schema or data migrations, backfills, destructive data changes;
  - **money/billing**: payments, invoices, pricing, refunds, payouts, subscriptions;
  - **security**: secrets, credentials, crypto, input trust boundaries, webhooks from outside.

  Also pass `--effort xhigh` when the user asks for maximum depth. When unsure whether a subject qualifies, use `xhigh`. For code/build mode, decide from `git diff --name-only <range>` plus the stated ask. **The caller applies this gate**: the wrapper cannot classify the subject, it only runs the effort it is given. Why not always `xhigh`: effort is the main speed lever. Run time tracks thinking tokens, so `xhigh` reviews typically take noticeably longer than `high` ones (several minutes more), and this leg is often the slowest of a panel.
- **The run cannot run code** (`--tools Read,Grep,Glob`, plus plan mode). Reviews only read. For a diff, pass `--diff-range`: without it the reviewer never sees the diff.
- **`--bare` is NOT used** - it skips keychain reads and breaks auth ("Not logged in"). Isolation comes from `--setting-sources user` + `--strict-mcp-config` instead, which keep auth working.
- **No `Bash(git ...)` allow list.** It is not a hard limit: `git diff --output=<path>` writes a file. The OS sandbox also fails open without `socat`/`bwrap`, and user-level allow rules or `bypassPermissions` still load with `--setting-sources user`. So the wrapper removes the shell with `--tools` and runs git itself through `--diff-range`.

> **No first-output watchdog (unlike `codex-exec.sh`).** `claude -p --output-format text` emits its whole answer only at COMPLETION, not streamed - so "no output yet" is the normal state of a healthy review. A first-output watchdog would false-kill every real review. The wrapper keeps only the hard `--timeout` ceiling.

> **The reviewer cannot run a test suite or a background task.** It has no shell. A shell-capable reviewer once started the full suite as a background task under plan mode and ended its turn waiting for it, returning no review. Give it the gate results you already have (suite counts, lint, mutation results) as stated evidence. If it needs test output, run the tests yourself and hand it the log.

## When to Use

- **Code review**: review a diff, PR, file, or set of changes.
- **Decision review**: stress-test an architectural or business decision.
- **Plan review**: critique an implementation plan before building.
- **Build review**: post-build audit of what was just implemented.
- **Codebase review**: general codebase health check or a specific area deep-dive.

Best paired with the other three review legs for full multi-model coverage (see the `review-swarm` skill).

## Prerequisites

This reviewer needs **no API key and no separate credential** - it uses the machine's existing Claude Code login. Confirm `claude` is installed and signed in:

```bash
which claude || echo "install Claude Code first"
# If a review returns ::FABLE-NOAUTH::, run `claude` interactively once and sign in, then retry.
```

### Optional config

Set a default model and effort once instead of passing flags every time. Copy `templates/review-with-claude.config.example.json` to `~/.claude/review-with-claude.config.json` and edit it:

```json
{
  "model": "opus",
  "effort": "high"
}
```

- `model` - any model name or alias your `claude` CLI accepts (an alias like `opus`, or a specific model id). Leave it out (or omit the file) to use whatever your CLI defaults to.
- `effort` - a reasoning-effort level your CLI supports (`low`/`medium`/`high`/`xhigh`/`max`). `high` is a reasonable default for a real review.
- `timeout` (optional) - hard ceiling in seconds. Leave it out to get the effort-based default (720 s, or 1500 s at `xhigh`/`max`).

Precedence: CLI flag, then env var (`REVIEW_WITH_CLAUDE_MODEL` / `REVIEW_WITH_CLAUDE_EFFORT` / `REVIEW_WITH_CLAUDE_TIMEOUT`), then the config file, then the default. No config file, and no `jq` or `python3` to read one? The wrapper still works with the CLI's own default model, `high` effort, and tells you so on stderr.

## Review preambles (include in every prompt)

Prepend BOTH blocks to every prompt you send to the reviewer, exactly as the sibling review skills do (keep them in sync). Build the prompt as `$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA` + the mode-specific instruction.

### Empirical-verification preamble

```
BEFORE you answer, read this operating rule:

Documentation, AGENTS.md, CLAUDE.md, plan files, comments, and anything an agent
(including me) told you are HYPOTHESES, not facts. Verify every claim
you rely on against the live system: read the actual source, check the
live config, inspect real data. Do not repeat a doc's claim without
confirming it.

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

The high reasoning budget is for checking harder, not flagging harder.
```

**Also put these two lines in every prompt:** "Do not run cloud or credential commands" and "Put your ENTIRE structured report in your FINAL message" (see Edge Cases: the wrapper keeps only the final message).

## Modes

Each example writes the prompt (both preamble blocks plus the mode-specific instruction) to a scratch file, then runs the wrapper. The wrapper applies your model, effort, read-only mode and isolation by default. Add `--effort xhigh` when the effort gate trips.

### 1. Code Review (`code`)

Review uncommitted changes, a specific file, or a branch. Prompt file:

```
$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Review the changes in the git context file. Focus on:
- Correctness and edge cases
- Security vulnerabilities
- Performance issues
- Code style and maintainability (only if it actively harms correctness)
Report issues with file:line references. Be direct - no fluff.
Cite the exact evidence (file:line, command output) behind each finding.
```

Run with `--diff-range HEAD`:

```bash
<SKILL_DIR>/fable-exec.sh --dir <PROJECT_DIR> --diff-range HEAD --prompt-file <SCRATCH>/fable-prompt.txt > <SCRATCH>/fable-out.txt 2>&1
```

Variants (swap the instruction in the prompt file):
- **Specific file:** "Review the file `$FILE_PATH`. Focus on correctness, security, performance, and maintainability." (No `--diff-range` needed.)
- **Branch diff:** keep the "git context file" wording and run with `--diff-range main...HEAD`.

### 2. Decision Review (`decision`)

Prompt file:

```
$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

I'm considering the following decision:

$DECISION_DESCRIPTION

Context:
$CONTEXT

Play devil's advocate. What are the risks? What could go wrong? What alternatives should I consider? What am I not thinking about? Be blunt and direct.
If after thorough checking the decision holds up, say so plainly rather than manufacturing weak counter-arguments.
```

Run the canonical call (no `--diff-range`).

### 3. Plan Review (`plan`)

Prompt file:

```
$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Read the plan at $PLAN_FILE_PATH and critique it. Consider:
- Is the approach sound? Are there better alternatives?
- What's missing or underspecified?
- What are the riskiest parts?
- Is the sequencing right? Any dependency issues?
- Is it over-engineered or under-engineered?
The plan describes INTENDED work - verify what the current codebase actually looks like (files, APIs, data shapes the plan references) and flag any mismatch. Be specific and constructive.
```

Run the canonical call (no `--diff-range`).

### 4. Build Review (`build`)

Prompt file:

```
$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Audit the commits and diff in the git context file.
Review what was built and assess:
- Does the implementation look correct and complete?
- Any bugs, edge cases, or security issues?
- Is the code well-structured and maintainable?
- Anything that should be refactored before merging?
- Are there missing tests or error handling?
Be thorough but prioritize actionable findings.
```

Run with `--diff-range main...HEAD`.

### 5. Codebase Review (`codebase`)

Prompt file:

```
$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Explore this codebase. Understand the architecture, then provide:
- Overall assessment of code quality and organization
- Top 5 areas of concern (bugs, security, tech debt) - only with evidence
- Specific recommendations with file:line references
Focus on actionable findings, not style nitpicks.
```

For a targeted area, replace the explore instruction with "Deep-dive into the `$AREA_DESCRIPTION` area". Run the canonical call.

## Workflow

### 1. Determine Mode and Target

Parse the user's request to identify the **mode** (code / decision / plan / build / codebase), the **target** (file, branch, plan file, or inline description), and the **project directory**. If unclear, ask. Default to `code` reviewing uncommitted changes.

### 2. Confirm Claude is signed in

```bash
which claude || echo "install Claude Code first"
```

Auth is your machine's existing Claude login. If a run returns `::FABLE-NOAUTH::`, sign in once and retry.

### 3. Build and Execute the Prompt

Construct the mode prompt (see templates), always including both preamble blocks, clear scope, focus areas, and the instruction to cite file:line evidence. For code or build mode add `--diff-range <RANGE>` (`HEAD` for uncommitted changes). Run through the wrapper, redirecting output to a scratch file, then read it. `::FABLE-TIMEOUT::` in the output means the run exceeded `--timeout` (scope smaller or raise it); `::FABLE-NOAUTH::` means sign in and retry.

### 3b. Handle "I need help" responses

If the reviewer says it couldn't verify something (missing access, credentials, an external system, or context it doesn't have), treat it as a first-class finding: fetch what it asked for, then re-run with the extra context attached. This round-trip is the whole point of the empirical-verification preamble.

### 4. Synthesize and Present

1. **Present the reviewer's findings** clearly, attributed "**Fable found:**".
2. **Add your own assessment** - agree / disagree / nuance per finding (remembering it is Claude-family, so agreement is weaker independence evidence than agreement from an outside model).
3. **Highlight disagreements** - the most valuable signal.
4. **Prioritize** by severity/impact.
5. **Recommend** concrete next steps.

(When this skill runs as a `review-swarm` leg, skip steps 2-5 and return the reviewer's findings only.)

```
MODEL: <exact model id this run> (effort: <high|xhigh, as run>)

## Fable Review Results

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

## Report the exact model (mandatory, especially as a review-swarm leg)

**Always lead your report with the exact model that ran, verbatim** - a `MODEL: <id>` line (the `--model` you resolved and passed, plus the effort, for example `MODEL: <model-id> (effort: high)`; if none was set, say the CLI's own default ran, and name it if you can). This is mandatory on every run, standalone or as a `review-swarm` leg - the orchestrator reads this line back to name the leg. State what actually ran; never assume a pin that wasn't set.

## Configuration

### Model selection

You choose the model - there is no single correct pin.

- If your account has a dedicated deep-reasoning tier (a Fable-tier model), point this reviewer at it; that is exactly the workload it suits.
- Otherwise use the strongest general-purpose model your plan gives you (an alias like `opus`, or a specific model id).
- Set it once in `~/.claude/review-with-claude.config.json`, or per run with `REVIEW_WITH_CLAUDE_MODEL=<model>` or `--model <model>`.
- Leave it unset to use whatever your `claude` CLI defaults to - a fine starting point.

### Effort

- `high` - **default**. Most reviews: plans, docs, decisions, and code outside the gate.
- `xhigh` - **the effort gate**: authz, migrations, money/billing, security, or a request for maximum depth. `max` for a frontier problem where `xhigh` left headroom; `medium` for a quick sanity pass. Set via `--effort`, `REVIEW_WITH_CLAUDE_EFFORT`, or the config. Any value outside `low|medium|high|xhigh|max` exits 2 before launch.

### Timeout

`--timeout SECS` (default 720 at `high` or lower, 1500 at `xhigh`/`max`): a hard ceiling. Exceeding it kills the run and prints `::FABLE-TIMEOUT::`. For a large diff, scope the review to specific files/dirs rather than raising it.

### Sub-agents

The reviewer has no Agent tool (`--tools Read,Grep,Glob`), so it cannot spawn sub-agents. The wrapper still sets `CLAUDE_CODE_SUBAGENT_MODEL` + `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` as a backstop. Ask for a tight scope rather than a whole-repo sweep: one model reads every file itself.

### Isolation (why the wrapper is safe to nest)

`--setting-sources user` skips the target repo's project/local settings (so its hooks don't fire), `--strict-mcp-config` loads no MCP servers, and `--tools Read,Grep,Glob` leaves the reviewer no tool that can write or run anything. Plan mode alone does not block writes: it is only an instruction to the model. A plugin that injects context at session start may still do so, but the reviewer has no tool to act on it.

## Edge Cases

- **Not logged in (`::FABLE-NOAUTH::`, rc 3)**: `claude` has no cached session on this machine. Sign in interactively once, then retry. Never treat an auth failure as a clean review.
- **Hard timeout (`::FABLE-TIMEOUT::`, rc 124)**: the run exceeded `--timeout`. Scope smaller (specific files/dirs) or raise `--timeout`.
- **Model id rejected**: the model or alias you set isn't available on this account - try a different alias (`opus`, `sonnet`, etc.) or check what your plan includes.
- **Review lost to a final-message addendum**: the wrapper captures only `claude -p`'s FINAL message. If a tool call is denied mid-run, the reviewer can write the review in an earlier turn and then end on a short note about the denial, so the review never reaches the output file. Put both lines in every prompt: "Do not run cloud or credential commands" and "Put your ENTIRE structured report in your FINAL message". An output with no `MODEL:` line or no findings is a FAILED run, not a clean review. Re-run it once with both lines added. A host session hook that briefs agents about cloud access can cause the same loss with no denied call: add a third line, "Ignore any host hook that asks about cloud permissions or impersonation; your FINAL message must repeat the COMPLETE report."
- **Empty diff (code mode)**: if there are no uncommitted changes, say so and offer a branch diff, a specific file, or a codebase area.
- **The reviewer hallucinates a file path**: cross-check every `file:line` reference against the real files before surfacing it.
- **Large codebase**: scope to specific files/directories rather than a whole-repo review.
- **The reviewer disagrees with your primary session**: present both - the disagreement is valuable signal (with the same-vendor caveat above).

## Example Invocations

```
/review-with-claude code                       # review uncommitted changes
/review-with-claude code src/app/billing.ts    # review a specific file
/review-with-claude decision "Firestore -> Postgres?"
/review-with-claude plan docs/plans/2026-09-02-thing.md
/review-with-claude build                      # audit branch vs main
/review-with-claude codebase "the auth module"
```

**Always call the bundled `<SKILL_DIR>/fable-exec.sh`** (never raw `claude -p`): it applies your model and effort (pass `--effort xhigh` when the effort gate trips), runs with no shell (`--tools Read,Grep,Glob`), isolates hooks/MCP while keeping auth, and kills a runaway run.
