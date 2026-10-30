---
name: review-with-codex
description: "Use OpenAI Codex CLI as a second-opinion reviewer for code, decisions, plans, and builds. Runs Codex headlessly through a bundled safety wrapper to get independent analysis from a different AI model, then synthesizes findings. Triggers on: codex review, second opinion, codex check, review with codex, codex audit, ask codex, cross-review, get codex opinion, rival review."
argument-hint: "[mode: code|decision|plan|build|codebase] [target: file path, branch, or description] [--full-context]"
---

# Review with Codex - Second-Opinion Code & Decision Review

Runs OpenAI's Codex CLI headlessly to get independent analysis from a competing AI model. Use this when you want a second pair of eyes - a fundamentally different model reviewing your work, catching blind spots, or stress-testing decisions.

Every call goes through a **bundled safety wrapper**, `codex-exec.sh`, that ships in this skill's own directory. You never hand-run the raw Codex CLI: the wrapper encodes the mandatory invocation rules in one place, pins the model and `xhigh` reasoning effort, defaults to a read-only sandbox, and runs a liveness watchdog that kills a wedged run so a hung auth or model handshake can't silently eat an hour.

## The wrapper: `codex-exec.sh` (call it, never raw Codex)

It is a thin, host-neutral wrapper around `codex exec` that always:

- **Pins the model** (the default is the `MODEL` variable at the top of `codex-exec.sh`, the only place a model name lives in this skill; change it with `--model` or the `CODEX_REVIEW_MODEL` env var) and the **reasoning effort** (default `xhigh`), so a deep review gets the deep reasoning budget without you remembering a flag.
- **Redirects stdin from `/dev/null`** so Codex never blocks waiting on stdin (the most common cause of "Codex is hung").
- **Passes `--skip-git-repo-check`** (a no-op inside a git repo, required for a non-git path such as a skills folder).
- **Picks the sandbox by tier** via `--mode` (default `review` = read-only; see the Sandbox decision tree).
- **Runs a liveness watchdog:** if there is no output within `--first-output` seconds (default 120), it kills the run, prints `::CODEX-WEDGED::`, and tells you to relaunch attached. A hard `--timeout` ceiling (default 900 s) kills a genuinely stuck run and prints `::CODEX-TIMEOUT::`.

**Call it by its path in this skill's base directory** (the `Base directory for this skill:` path shown when the skill loads). It is NOT on your `$PATH`.

## Invocation form (works in restrictive agent harnesses)

Some agent harnesses refuse a Bash command that contains a `$(...)` or backtick substitution, a variable assigned from command output, `export VAR=...`, a variable used as the command name, a heredoc, a `for`/`while` loop, or `bash -c "..."`. Claude Code does this in a git-worktree session. A literal absolute script path with literal arguments and a plain `>` redirect always passes, so use this form for every call:

1. Write the prompt with your editor/Write tool to a file in a scratch directory. Do not build the prompt in the shell.
2. Run the wrapper as ONE plain command. Every path is a **literal absolute path** you paste in, never a shell variable.
3. Read the output file. Codex's whole run is often 350-400 KB and some file readers refuse a file over 256 KB, so find where the final report starts (for example `grep -n '^MODEL:' <file> | tail -1`, or the answer after the LAST line that is exactly `codex`) and read from there.

Placeholders used in every example below:
- `<SKILL_DIR>` = this skill's base directory path, pasted literally. Not `$SKILL_DIR`.
- `<SCRATCH>` = a scratch directory for prompts and outputs, pasted literally.
- `<PROJECT_DIR>` = the absolute path of the repo (or review snapshot) under review.

`--prompt-file` and `-- PROMPT` are alternatives (passing both exits 2); a missing or empty prompt file exits 2; a prompt over ~131000 bytes exits 2 (keep large input in a file Codex reads instead of pasting it into the prompt).

**Canonical read-only review call:**

```bash
<SKILL_DIR>/codex-exec.sh --mode review --dir <PROJECT_DIR> --prompt-file <SCRATCH>/codex-prompt.txt > <SCRATCH>/codex-out.txt 2>&1
```

`--dir` is the project directory (passed through as Codex's `-C`), `--mode review` is the read-only sandbox tier, and `--prompt-file` points at the prompt file you wrote in step 1.

## Review one checkpoint commit: `snapshot-review.sh`

For a review of a change you are building (a single pass, or any diff review), use `snapshot-review.sh` from this skill's base directory. It copies the checkpoint commit's tree to a new temp folder (`git archive`), so the reviewer can never touch your branch. It writes `change.diff` against the **merge-base** with `--base` (default `origin/main`), so commits that landed on the base after you branched are not shown as yours (a plain `git diff origin/main <sha>` shows them, and a reviewer reports them as defects in your change). It copies each `--ref` folder under `ref/`, puts your prompt at `REVIEW_PROMPT.md`, and runs `codex-exec.sh --mode review` on the copy.

```bash
<SKILL_DIR>/snapshot-review.sh --repo <PROJECT_DIR> --sha <checkpoint sha> --prompt-file <SCRATCH>/review-prompt.md --out <SCRATCH>/codex-out.txt --effort high --timeout 600
```

Commit a checkpoint first. In the prompt, tell Codex the files are in its working folder, the diff is `change.diff`, and the ask is in your plan. Add `--ref <dir>` once per reference folder and `--base <ref>` for a branch other than `origin/main`.

- **`--sha` takes the full 40-character SHA.** A short SHA stops at once with `not a commit` (exit 2).
- **Tests in the snapshot need a named interpreter and two flags.** The Codex sandbox is read-only and its system `python3` may have no pytest. If the prompt asks Codex to run tests, name an interpreter that has pytest and the exact command `<python> -B -m pytest -p no:cacheprovider --capture=sys <path>`, and say the review goes on from the code if the run fails. Without this, Codex can stop and return no verdicts at all.

## Mandatory invocation rules (apply to every call)

These are the rules the wrapper enforces for you. You get them for free by calling `codex-exec.sh` instead of raw Codex. They are the difference between a clean review and a hung or accidentally destructive one.

- **The model is pinned** (the default model) so a stale local config can't silently downgrade the review. If you hit `model not supported when using Codex with a ChatGPT account`, pass `--model <id>` with an older flagship your plan supports (check OpenAI's current Codex model list).
- **Reasoning effort is `xhigh`.** The wrapper always sets `model_reasoning_effort="xhigh"` (override with `--effort` only if you have a reason to). Do not drop it for a real review.
- **Stdin is closed (`< /dev/null`).** The process never hangs waiting for EOF.
- **`--skip-git-repo-check` is always passed.** No-op in a normal repo; required when `--dir` points outside a checkout.
- **The sandbox defaults to read-only** (`--mode review`). Reviews only read, so read-only is the correct, safest tier - Codex can still run read-only commands like `git diff`, `cat`, `grep` under it. Only widen the tier when the review must run tests or reach the network (see the Sandbox decision tree).

> **Two different meanings of "mode".** This skill's review *modes* (`code` / `decision` / `plan` / `build` / `codebase`) describe **what to review**. The wrapper's `--mode` flag (`review` / `inspect` / `full` / `danger`) selects the **sandbox tier**. They are independent: a `build` review that must run the suite is still driven by the wrapper at `--mode inspect` or `--mode full`.

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

The wrapper drives the `codex` binary; install it first. Override the binary with `CODEX_BIN` if needed (used by test harnesses).

### Authentication

Codex uses your ChatGPT account via OAuth (cached at `~/.codex/auth.json`). No API key needed. The login is per OS user: on a shared machine each user needs their own `codex login`, or every Codex call fails with HTTP 401.

If auth expires, re-authenticate:

```bash
codex login
```

## Review preambles (include in every prompt)

Prepend BOTH blocks to every prompt you send to Codex. Build the prompt as `$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA` + the mode-specific instruction. They are what turn a fast, plausible-sounding answer into a grounded, evidenced one.

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

Each example writes the prompt (both preamble blocks, `$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA`, plus the mode-specific instruction) to a scratch file, then runs the wrapper at the read-only tier. Default every review to `--mode review`; only widen the tier for a review that must run the test suite or reach the network.

> `<SKILL_DIR>` is this skill's base directory path pasted in literally. The wrapper applies the model pin and `xhigh` by default. Canonical call: `<SKILL_DIR>/codex-exec.sh --mode review --dir <PROJECT_DIR> --prompt-file <SCRATCH>/codex-prompt.txt > <SCRATCH>/codex-out.txt 2>&1`.

### 1. Code Review (`code`)

Write this prompt to `<SCRATCH>/codex-prompt.txt`:

```
$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Review the uncommitted changes (run git diff). Focus on:
- Correctness and edge cases
- Security vulnerabilities
- Performance issues
- Code style and maintainability (only if it actively harms correctness)
Report issues with file:line references. Be direct - no fluff.
Cite the exact evidence (file:line, command output) behind each finding.
```

Then run the canonical call and read `<SCRATCH>/codex-out.txt`.

Variants (swap the instruction in the prompt text you write to the file):
- **Specific file:** "Review the file `$FILE_PATH`. Focus on correctness, security, performance, and maintainability."
- **Branch diff:** "Review changes on this branch vs main (run `git diff main...HEAD`). Focus on correctness, security, and whether the implementation matches the intent."
- **Run the tests too:** bump the tier to `--mode inspect` (add `--net`, or use `--mode full`, if the suite needs the network) so Codex can execute the suite, not just read the diff.

### 2. Decision Review (`decision`)

Stress-test an architectural, technical, or business decision. Prompt file:

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

Run the canonical call.

### 3. Plan Review (`plan`)

Critique an implementation plan before building. Prompt file:

```
$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Read the plan at $PLAN_FILE_PATH and critique it. Consider:
- Is the approach sound? Are there better alternatives?
- What's missing or underspecified?
- What are the riskiest parts?
- Is the sequencing right? Any dependency issues?
- Is it over-engineered or under-engineered?
Be specific and constructive.
```

For an inline plan, replace the "Read the plan at..." line with the plan text. Run the canonical call.

### 4. Build Review (`build`)

Post-implementation audit of what was just built. Prompt file:

```
$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Audit the recent changes on this branch (run git log --oneline -20 and git diff main...HEAD).
Review what was built and assess:
- Does the implementation look correct and complete?
- Any bugs, edge cases, or security issues?
- Is the code well-structured and maintainable?
- Anything that should be refactored before merging?
- Are there missing tests or error handling?
Be thorough but prioritize actionable findings.
```

Run the canonical call. To run the test suite as part of the audit, bump to `--mode inspect` (add `--net`, or `--mode full`, if the suite needs the network).

### 5. Codebase Review (`codebase`)

General health check or deep-dive into a specific area. Prompt file:

```
$EMPIRICAL_PREAMBLE

$SUCCESS_CRITERIA

Explore this codebase. Understand the architecture, then provide:
- Overall assessment of code quality and organization
- Top 5 areas of concern (bugs, security, tech debt) - only with evidence
- Specific recommendations with file:line references
Focus on actionable findings, not style nitpicks.
```

For a targeted area, replace the explore instruction with "Deep-dive into the `$AREA_DESCRIPTION` area" and ask for correctness, security, performance, and test-coverage gaps with file:line references. Run the canonical call.

## Workflow

### 1. Determine Mode and Target

Parse the user's request to identify:
- **Mode**: code, decision, plan, build, or codebase
- **Target**: file path, branch name, plan file, or inline description
- **Project directory**: which project or repo

If unclear, ask the user. Default to `code` mode reviewing uncommitted changes.

### 2. Set Up Environment

```bash
# Verify codex is installed (the wrapper drives it); auth is cached OAuth.
which codex || npm install -g @openai/codex
```

If auth fails, run `codex login`.

### 3. Check for AGENTS.md

Check if `AGENTS.md` exists in the target project directory. This file gives Codex project-specific context (like CLAUDE.md does for Claude).

- If it exists: Codex picks it up automatically
- If it does not exist: warn once: "No AGENTS.md found in this project. Codex will work without project context. Want me to create one based on CLAUDE.md?"
- If the user says yes: read the project's CLAUDE.md and craft an AGENTS.md adapted for Codex's conventions. Don't block the review - create it after.

### 4. Build and Execute the Prompt

Construct the prompt for the mode (see templates above). Always include:
- Both preamble blocks (`$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA`)
- Clear scope (what to review)
- Specific focus areas
- Instruction to be direct and cite file:line references
- The project directory via `--dir`

Run headlessly through the wrapper, redirecting output to a scratch file, then read it. The wrapper's exit code (0 on completion, or 124 if the watchdog or the hard timeout killed it) shows up in the text: `::CODEX-WEDGED::` means the model/auth handshake wedged - relaunch attached (foreground) so the startup failure is visible; do not passively wait on it.

### 4b. Handle Codex's "I need help" responses

If Codex's output says it couldn't verify something - missing access, credentials, an external system it can't reach, or context it doesn't have - **do not suppress or paper over that**. Treat it as a first-class finding:

- Read what Codex asked for.
- Fetch the credential, grant the access, pull the log/config/dashboard, or supply the missing context.
- Re-run the wrapper with the extra information attached to the prompt.

This round-trip is the whole point of the empirical-verification preamble. Guessed answers are worse than "I don't know, here's what I need."

### 5. Synthesize and Present

**Always lead with the exact model that ran, verbatim** - a `MODEL: <id>` line read back from the actual invocation (the `--model` the wrapper used this run). This is mandatory on every run, standalone or as a `review-swarm` leg - the orchestrator reads this line back to name the leg. Do not omit it and do not assume the pin: state what actually ran.

After receiving Codex's output:

1. **Present Codex's findings** clearly, attributed as "Codex found:" (under the `MODEL:` line above)
2. **Add your own assessment** - agree, disagree, or add nuance to each finding
3. **Highlight disagreements** - where Claude and Codex see things differently, this is the most valuable signal
4. **Prioritize** - rank findings by severity/impact
5. **Recommend actions** - concrete next steps based on the combined review

(When this skill runs as a `review-swarm` leg, skip steps 2-5: return Codex's findings only, so the panel gets no extra opinion.)

Format the output as:

```
MODEL: <exact model id this run>

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

For follow-up questions, run additional wrapper calls targeting specific areas.

## Multi-Turn Review Sessions

For complex reviews, run multiple passes through the wrapper. Write each pass's prompt to its own scratch file, run one plain command per pass, and read its output file before writing the next pass's prompt:

1. Pass 1: "Review the codebase architecture and flag top concerns" (`<SCRATCH>/codex-pass1-prompt.txt` -> `<SCRATCH>/codex-pass1-out.txt`).
2. Pass 2: a prompt that names the concerns Pass 1 raised and asks for detailed analysis with code examples.
3. Pass 3: "Security audit: check for injection, auth bypass, data exposure, SSRF, and other OWASP top 10 issues."

Each pass uses the same canonical call with its own prompt and output file.

## Configuration

### Model selection

The wrapper pins OpenAI's frontier Codex model at the time of writing; the `MODEL` variable at the top of `codex-exec.sh` is the one place it is named. Change the default for every call with `CODEX_REVIEW_MODEL`, or per call with `--model`. If the frontier model is unavailable on your account, pass an older flagship with `--model`. Check OpenAI's current model list for newer options, and prefer the strongest model your plan allows for reviews.

### Reasoning effort

The wrapper always applies `model_reasoning_effort="xhigh"` - the deep-review budget. Override only with `--effort <level>` and only for a reason (for example `--effort high --timeout 600` for a quick one-pass review of a small change). Do not drop below `xhigh` for a high-stakes review: the high budget is for checking harder, not flagging harder.

### Timeout and the liveness watchdog

Raw Codex runs until completion with no ceiling, and a wedged model/auth handshake can silently eat an hour. The wrapper removes that failure mode:

- **`--first-output SECS` (default 120):** if Codex emits no output at all within this window, the run is killed and the wrapper prints `::CODEX-WEDGED::`. That is a handshake hang, not slow work - relaunch attached (foreground) so the startup failure is visible; never passively wait on it.
- **`--timeout SECS` (default 900):** a hard ceiling. If the run exceeds it, the wrapper kills it and prints `::CODEX-TIMEOUT::` - scope the review smaller or raise `--timeout`.

Both killed states exit `124`. For large codebases, scope the review to specific directories/files rather than raising the ceiling.

### Sandbox decision tree

Codex has two independent dials: the **sandbox** (what a command is physically allowed to do) and **approval** (when it pauses to ask). The wrapper selects the sandbox tier with `--mode`:

| `--mode` | Underlying sandbox | Can write | Network | Use for |
|---|---|---|---|---|
| `review` (default) | `-s read-only` | no (read-only cmds like `git diff` still run) | no | code / decision / plan / codebase / build review - inspection only |
| `inspect` | `--sandbox workspace-write` | cwd + `/tmp` | no | run no-network unit tests, write scratch |
| `full` | `--sandbox workspace-write` + network | cwd + `/tmp` | yes | run the full suite/build that needs the network |
| `danger` | `-s danger-full-access` | anywhere | yes | last resort: suite also writes outside the workspace |

Two extra flags: `--net` forces network access on (and upgrades a bare `--mode review` to `full`, since network needs workspace-write); `--add-dir DIR` (repeatable) adds an extra writable directory for a suite that writes to a sibling path.

**Default to `--mode review`.** It is the safest tier and prevents an entire class of accident: a review running with write access can accidentally mutate the very repo it is reviewing (a setup or migration script triggered mid-review has corrupted repos this way). Read-only makes that structurally impossible, and Codex can still run `git diff`, `cat`, `grep` under it, so most reviews never need to leave it.

> **A sandbox denial is NOT a code bug.** When you run tests under a tighter tier and a command fails with `Could not resolve host` / `Failed to resolve '...'` / `Connection refused` / `Operation not permitted` / `Read-only file system`, that is the **sandbox** blocking it, not a defect in the code under review. Do not surface it as a finding. Either re-run at a looser tier (`--mode inspect` for scratch/tests, `--mode full` for live calls, `--mode danger` for out-of-workspace writes) or note it as "blocked by sandbox, not verified".

> **The sandbox cannot START at all (host has no unprivileged user namespaces).** On some cloud VMs `--mode review` dies at startup with `bwrap: loopback: Failed RTM_NEWADDR`, and `--mode inspect` / `--mode full` with `bwrap: setting up uid map: Permission denied`. Codex then cannot read a single local file and "reviews" blind, which is a failed leg, not a review. This is a host capability gap: retrying the same tier will not help, and only `--mode danger` (no sandbox) starts. Use it only as a guarded last resort: (1) say in the prompt that the run is strictly read-only and must not write, change git state, or make network mutations; (2) checkpoint-commit first; (3) `touch` a marker before the run and afterwards confirm that `find <PROJECT_DIR> -path <PROJECT_DIR>/.git -prune -o -type f -newer <marker> -print` lists nothing but caches. Never reach for `danger` when the failure is an ordinary mid-run sandbox denial.

> **A suite can HANG in the sandbox, with no error.** Inside the Codex sandbox (bwrap), a Python suite that uses `asyncio.to_thread` can hang; outside the sandbox the same tests pass in seconds. A hung run ends at the wrapper's time cap (exit 124) with no final report. So a Codex build brief names the exact test files to run, and the calling agent runs the full suite itself, outside the sandbox. After a hang, verify the diff and run the tests yourself.

**When to go past `review`:** bump to `inspect`/`full` for any review that must run the suite or hit live APIs, remotes, public URLs, or DNS - that is, prompts mentioning `live`, `verify`, `audit`, `API`, `logs`, `production state`. Pure code/plan critique stays at `review`.

**Scratch-file footgun:** any write-capable tier (`inspect` / `full` / `danger`) lets Codex write files into the review directory. If that repo has an auto-commit hook, those scratch files can be committed as a `wip` and pushed to a shared branch. Prefer `--mode review` when no file writes are intended. If you must use a write tier, tell Codex in the prompt to write scratch to `/tmp`, and `git status` the review repo afterward before any commit or push.

### Non-git directories

`--dir` directories that aren't a git checkout would normally require `--skip-git-repo-check`; the wrapper always passes it, so a skills folder or any path outside a checkout just works, and inside a normal repo it's a harmless no-op.

## `--full-context` flag (any mode)

Codex's CLI context window is too small for a full agent-session transcript. `--full-context` on Codex therefore works off a digest, not the raw transcript:

1. **Build a digest first.** Pre-summarise the session into a structured digest - high-level intent, decisions made, files touched (with current contents inlined), commands run, verification done, and any unresolved items.
2. **Pass the digest as the primary context.** Codex reviews the digest + scoped artefacts (diff, plan file, etc.), not the raw transcript.
3. **If the digest can't fit Codex's window** (rare, only on very long sessions): refuse the flag rather than silently truncating - scope the review down instead.

Codex sees a curated picture of the session rather than the raw transcript. That's a feature when the session is mostly noise; a bug when the failure mode you're hunting is in the noise. For raw-transcript full-context reviews, prefer a model with a larger context window.

## Edge Cases

- **Codex not installed**: `npm install -g @openai/codex`
- **Auth expired**: `codex login` to re-authenticate via browser OAuth
- **Hangs from stdin / non-git dir / bare `codex`**: the wrapper prevents all three - it always closes stdin, always passes `--skip-git-repo-check`, and always uses `codex exec` (never bare `codex`, which needs a TTY). These only bite if you bypass the wrapper and call Codex directly, so don't.
- **Wedged with no output (`::CODEX-WEDGED::`, rc 124)**: model/auth **handshake hang**. The wrapper already killed it after `--first-output` seconds. Relaunch attached (foreground) so the startup failure is visible; never passively wait on a background run.
- **Hard timeout (`::CODEX-TIMEOUT::`, rc 124)**: the run exceeded `--timeout`. Scope the review smaller (specific files/dirs) or raise `--timeout`.
- **`Could not resolve host` / `Operation not permitted` / `Read-only file system` mid-review**: the **sandbox** blocked it, not a code bug. Re-run at `--mode inspect`/`full`/`danger`; see the Sandbox decision tree. Never report a sandbox denial as a finding.
- **`model not supported when using Codex with a ChatGPT account`**: the pinned model isn't available on the ChatGPT-account auth path. Pass `--model <id>` with an older flagship your plan supports.
- **Large codebase**: scope to specific files/directories rather than whole-repo review
- **Codex disagrees with Claude**: present both perspectives - the disagreement itself is valuable signal
- **Codex hallucinates file paths**: cross-check all `file:line` references before presenting to the user
- **Rate limits**: space out multiple passes with brief delays if hitting OpenAI rate limits
- **Empty diff**: if reviewing uncommitted changes and there are none, tell the user and offer alternatives (branch diff, specific file, codebase review)

## Example Invocations

```
# Quick review of uncommitted changes
/review-with-codex code

# Review a specific file
/review-with-codex code src/main.py

# Stress-test a decision
/review-with-codex decision "Should we migrate from Firestore to PostgreSQL?"

# Critique a plan
/review-with-codex plan docs/migration-plan.md

# Post-build audit
/review-with-codex build

# Codebase health check for a project
/review-with-codex codebase my-project

# Full-context review (Codex sees a digest, not the raw transcript)
/review-with-codex build --full-context
```

**Always call the bundled `<SKILL_DIR>/codex-exec.sh`** (never raw Codex): it pins the model and `xhigh`, closes stdin, passes `--skip-git-repo-check`, defaults to the read-only sandbox, and kills a wedged run.
