---
name: review-with-gemini
description: "Use Google Gemini CLI as a second-opinion reviewer for code, decisions, plans, and builds. Runs Gemini headlessly and read-only through a bundled safety wrapper to get independent analysis from a different AI model, then synthesizes findings. Triggers on: gemini review, gemini check, review with gemini, gemini audit, ask gemini, gemini opinion, google review."
argument-hint: "[mode: code|decision|plan|build|codebase] [target: file path, branch, or description] [--full-context]"
---

# Review with Gemini - Second-Opinion Code & Decision Review

Runs Google's Gemini CLI (`gemini -p`) headlessly to get independent analysis from a different model family. Use this when you want a second pair of eyes - a fundamentally different model reviewing your work, catching blind spots, or stress-testing decisions.

Every call goes through a **bundled safety wrapper**, `gemini-exec.sh`, that ships in this skill's own directory, together with `review-policy.toml` (a read-only tool policy). You never hand-run raw `gemini -p`.

**The wrapper pins the default model** (Google's top model at the time of writing; it has a 1M-token input window). `gemini-exec.sh` sets it in its `MODEL` variable, which is the only place model names live in this skill; do not pass `--model` for a normal review. **If your key is refused for that model** (not found, no permission, or no quota, for example on a free key), the wrapper re-runs once on the fallback model (`FALLBACK_MODEL` in the same script) and prints `::GEMINI-FALLBACK::`. The re-run gets only the time left on `--timeout` (none if under 30 s), so the call still ends inside its timeout. Only the CLI's stderr decides a refusal. A timeout, a bad key (400) or a busy server (503) never falls back. An explicit `--model` is never swapped. Gemini CLI has no effort/thinking flag, so the model's built-in thinking is what you get; "reasoning effort high" in this skill is prompt framing, not a settable knob.

## Core Principle: Verify Empirically, Don't Trust Docs

Every review prompt sent to Gemini MUST include the empirical-verification directive below. Documentation files (GEMINI.md, CLAUDE.md, AGENTS.md, READMEs, plan docs, comments) describe *intent* - they rot, drift, and sometimes lie. A review grounded in stale docs is worse than no review: it confidently repeats fiction.

Gemini should treat every claim pulled from docs or agent instructions as a **hypothesis to verify** against the live system: read the actual code, check the config, inspect the data. If it can't verify something because it lacks authorization, access, or context, it should **say so explicitly and ask the master agent (the calling Claude session) for help** - an extra round-trip is cheaper than a wrong answer.

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

The read-only `--policy` flag needs a Gemini CLI with the policy engine. If `gemini` rejects `--policy` as an unknown argument, update it with the command above.

### Authentication

Get a Gemini API key from Google AI Studio (a free key works, about 1,000 requests a day) and export it as `GEMINI_API_KEY`, from your shell profile or your own secret manager, before calling the wrapper:

```bash
export GEMINI_API_KEY=...   # e.g. loaded from your secret manager
```

If your harness bans `export` in commands (see "Invocation form" below), set the key at harness level instead, in the `env` block of `~/.claude/settings.json`, so every command the agent runs inherits it:

```json
{
  "env": {
    "GEMINI_API_KEY": "your_api_key"
  }
}
```

Warning: this file holds the key in plain text. Keep it out of version control and shared backups, and prefer a secret manager where you have one.

The wrapper needs `GEMINI_API_KEY` in its environment and exits 2 with a clear message when it is missing. The wrapper never writes the key to disk. Never hard-code the key in source or use someone else's key.

## Invocation form (works in restrictive agent harnesses)

Some agent harnesses refuse a Bash command that contains a `$(...)`/backtick substitution, a variable assigned from command output, `export VAR=...`, a variable used as the command name, a heredoc, a `for`/`while` loop, or `bash -c "..."`. Claude Code does this in a git-worktree session. A literal absolute script path with literal arguments and a plain `>` redirect always passes, so use this canonical form for every Gemini call:

1. Write the prompt with your editor/Write tool to a file in a scratch directory. Do not build the prompt in the shell.
2. Run `gemini-exec.sh` as ONE plain command. Every path is a **literal absolute path** you paste in, never a shell variable:
   `<SKILL_DIR>/gemini-exec.sh --dir <PROJECT_DIR> --stdin-file <SCRATCH>/gemini-diff.txt --prompt-file <SCRATCH>/gemini-prompt.txt > <SCRATCH>/gemini-out.txt 2>&1`
   Gemini cannot run `git` itself (its policy denies the shell - see "Headless Execution Pattern"), so capture the diff first with a plain `git diff <RANGE> > <SCRATCH>/gemini-diff.txt`, and omit `--stdin-file` when there is nothing to pipe.
3. Read `<SCRATCH>/gemini-out.txt`.

Placeholders (used throughout this skill):
- `<SKILL_DIR>` = this skill's base directory path, pasted literally. Not `$SKILL_DIR`.
- `<SCRATCH>` = a scratch directory for prompts and outputs, pasted literally.
- `<PROJECT_DIR>` = the absolute path of the repo (or review snapshot) under review.
- `<RANGE>` = the diff range (e.g. `main...HEAD`).

`--prompt-file` and `-- "PROMPT"` are alternatives (both given: exit 2); a missing or empty prompt file exits 2; a prompt over ~131000 bytes exits 2 (keep large input in `--stdin-file` instead).

## Headless Execution Pattern

**Gemini reviews read-only. It reads files and searches, but it never runs commands and never writes.** You (the master agent) run `git diff`, `git log` and any other command, write the output to a file with a plain redirect, and point the wrapper at it.

```bash
# Review input from a file (a diff, a log, command output):
<SKILL_DIR>/gemini-exec.sh --dir <PROJECT_DIR> --stdin-file <SCRATCH>/gemini-diff.txt --prompt-file <SCRATCH>/gemini-prompt.txt > <SCRATCH>/gemini-out.txt 2>&1

# Nothing to pipe (decision, plan, codebase, a named file):
<SKILL_DIR>/gemini-exec.sh --dir <PROJECT_DIR> --prompt-file <SCRATCH>/gemini-prompt.txt > <SCRATCH>/gemini-out.txt 2>&1
```

`review-policy.toml` is bundled next to this SKILL.md and next to `gemini-exec.sh`.

`gemini-exec.sh` always runs `gemini -p` underneath with these flags baked in, so you never type them yourself:
- the prompt - built from your `--prompt-file` (or `-- "PROMPT"`); anything given via `--stdin-file` is added on stdin after the prompt.
- `--approval-mode default` - Gemini's normal mode. In a headless run it can read files and list and search the workspace.
- `--policy <SKILL_DIR>/review-policy.toml` - the read-only review policy bundled with this skill. It denies the shell, file-write, edit and memory tools by name, so Gemini cannot use them. It also denies Google web search: that tool can loop on HTTP 500 retries for a whole panel time budget and return nothing.
- `-m` (the default model, override with `--model`) - review model. A refused default falls back once to the fallback model, inside the same `--timeout`. The wrapper prints `::GEMINI-MODEL:: <id>` on stderr: the model that actually ran.
- `-o text` - plain text output (no JSON, no formatting artifacts).
- `--skip-trust` - trust the workspace for this session. Needed: in a folder Gemini has not trusted (for example a fresh worktree), headless runs otherwise change behaviour or abort with no useful output.
- `--dir <PROJECT_DIR>` - sets Gemini's workspace (its cwd) so it can read the files under review.
- stdin is your `--stdin-file`, or `/dev/null` when you omit it, so the wrapper never blocks waiting on stdin.
- `--timeout` - a hard ceiling in seconds (default 600; exit 124 on timeout).

Keep the `2>&1` in your invocation so the wrapper's own errors (missing key, bad `--dir`, timeout) land in the same output file you read.

**Never use `--approval-mode yolo`, `-y` or `--yolo`.** A review never needs to write. `gemini-exec.sh` doesn't expose a way to pass those - the policy wins regardless.

**Why Gemini gets no shell at all.** Red-team testing of the policy engine found that a shell allow-list of "read-only" git commands could not be made safe: shell quoting rebuilt denied options (`--o''utput` reached git as `--output` and wrote a file), `git grep -O` and a repo's own diff driver ran programs, and `git diff --no-index` read files outside the workspace. With the shell denied by name, every write and exec attempt failed (including under yolo and through Gemini's sub-agent tool), while file reads and a real review of a piped diff worked.

**When Gemini asks for a command's output** (tests, `git log`, `curl`), run the command yourself, write its output to a file with a plain redirect, and re-run `gemini-exec.sh` with that file as `--stdin-file` (or inlined into a fresh prompt file) - see 4c. This is the expected round-trip, not a failure.

**After each review, run `git status` on the workspace.** It should show no change. A stray file or edit means the policy has a gap: stop, discard it, and report it, rather than treating it as normal.

### Read-only note (include in every prompt, after the two preambles)

Append this block to every prompt (referenced below as `$READ_ONLY_NOTE`). It belongs to this skill only, so the two shared preambles stay word-for-word in sync with the other review skills:

```
READ-ONLY SESSION: you can read files in this workspace, list and search
them. You cannot run commands, cannot search the web, and cannot change
files. Where the rule above says to run a command or check live config,
name the exact command and I will run it and send you the output.
```

## Modes

> **Every example below assumes both preambles and the read-only note are prepended to the prompt file you write** (`$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA` from the two Core Principle sections, `$READ_ONLY_NOTE` from the Headless section). `gemini-exec.sh` always applies the flag set above and reads the key from the environment.

### 1. Code Review (`code`)

Write this to `<SCRATCH>/gemini-prompt.txt` (prepend `$EMPIRICAL_PREAMBLE`, `$SUCCESS_CRITERIA`, and `$READ_ONLY_NOTE`):

```
Review the uncommitted changes in this repo. The diff is in the file given via --stdin-file.
You can read any file in this repo for context, but you cannot run commands: if you need a command's output, name the exact command and I will run it. Focus on:
- Correctness and edge cases
- Security vulnerabilities
- Performance issues
- Code style and maintainability (only if it actively harms correctness)
Report issues with file:line references. Be direct - no fluff.
Cite the exact evidence (file:line, command output) behind each finding.
If GEMINI.md or other docs make claims you relied on, verify them in code before citing.
If everything looks correct, give the per-focus-area evidenced verdict described above - do NOT return a bare 'verified, no material findings'.
```

Then capture the diff and run the wrapper:

```bash
git diff > <SCRATCH>/gemini-diff.txt
<SKILL_DIR>/gemini-exec.sh --dir <PROJECT_DIR> --stdin-file <SCRATCH>/gemini-diff.txt --prompt-file <SCRATCH>/gemini-prompt.txt > <SCRATCH>/gemini-out.txt 2>&1
```

Read `<SCRATCH>/gemini-out.txt`.

Variants:
- Review a specific file: skip the diff capture and `--stdin-file`, and replace the diff sentence with "Review the file <FILE_PATH>" in the prompt.
- Review branch diff: capture with `git diff main...HEAD > <SCRATCH>/gemini-diff.txt` instead, and say "The diff (git diff main...HEAD) is in the file given via --stdin-file".

### 2. Decision Review (`decision`)

Prompt file (prepend the two preambles and the read-only note):

```
I'm considering the following decision:

$DECISION_DESCRIPTION

Context:
$CONTEXT

Play devil's advocate. What are the risks? What could go wrong? What alternatives should I consider? What am I not thinking about? Be blunt and direct.
If your critique depends on claims from the context above (or any docs), verify them against the live codebase/system first, or flag them as unverified.
If after thorough checking the decision holds up, say so plainly.
```

Run the wrapper with `--prompt-file` only (no `--stdin-file`).

### 3. Plan Review (`plan`)

Prompt file (prepend the two preambles and the read-only note):

```
Read the plan at <PLAN_FILE_PATH> and critique it. Consider:
- Is the approach sound? Are there better alternatives?
- What's missing or underspecified?
- What are the riskiest parts?
- Is the sequencing right? Any dependency issues?
- Is it over-engineered or under-engineered?
Be specific and constructive.
The plan describes INTENDED work - before critiquing, verify what the current codebase actually looks like (files, APIs, data shapes the plan references). Flag any mismatch between the plan's assumptions and reality.
If the plan stands up empirically, give a per-area evidenced verdict rather than a bare phrase or padded speculation.
```

Run the wrapper with `--prompt-file` only.

### 4. Build Review (`build`)

Prompt file (prepend the two preambles and the read-only note):

```
Audit the recent changes on this branch. The output of git log --oneline -20 and git diff main...HEAD is in the file given via --stdin-file. You can read any file in this repo, but you cannot run commands: name any command whose output you need.
Review what was built and assess:
- Does the implementation look correct and complete?
- Any bugs, edge cases, or security issues?
- Is the code well-structured and maintainable?
- Anything that should be refactored before merging?
- Are there missing tests or error handling?
Be thorough but prioritize actionable findings.
For any claim that depends on runtime behaviour (API shape, env var, deployed config), read the real file rather than trusting comments/docs, or name the command whose output you need.
If the build is clean, report it as a per-area evidenced verdict, not a bare 'verified, no material findings'.
```

Capture the log and diff with plain commands, then run the wrapper:

```bash
git log --oneline -20 > <SCRATCH>/gemini-diff.txt
echo >> <SCRATCH>/gemini-diff.txt
git diff main...HEAD >> <SCRATCH>/gemini-diff.txt
<SKILL_DIR>/gemini-exec.sh --dir <PROJECT_DIR> --stdin-file <SCRATCH>/gemini-diff.txt --prompt-file <SCRATCH>/gemini-prompt.txt > <SCRATCH>/gemini-out.txt 2>&1
```

### 5. Codebase Review (`codebase`)

Prompt file (prepend the two preambles and the read-only note):

```
Explore this codebase. Understand the architecture, then provide:
- Overall assessment of code quality and organization
- Top 5 areas of concern (bugs, security, tech debt) - only if you have evidence
- Specific recommendations with file:line references
Focus on actionable findings, not style nitpicks.
Build your architectural understanding from the actual source (entry points, routes, modules), not from README/AGENTS.md/CLAUDE.md descriptions - those may be out of date.
```

Run the wrapper with `--prompt-file` only (general health check, nothing to pipe).

## Workflow

### 1. Determine Mode and Target

Parse the user's request to identify:
- **Mode**: code, decision, plan, build, or codebase
- **Target**: file path, branch name, plan file, or inline description
- **Project directory**: which project or repo

If unclear, ask the user. Default to `code` mode reviewing uncommitted changes.

### 2. Check the API key

Confirm `GEMINI_API_KEY` is set in the environment the wrapper will run in. The wrapper stops with a clear message if it is not.

### 3. Check for GEMINI.md

Check whether `GEMINI.md` exists in the target project. If it does not, warn once - "No GEMINI.md found; want me to create one based on CLAUDE.md?" - and offer to draft one from the project's `CLAUDE.md`. Do NOT block the review on this: a missing `GEMINI.md` is a nudge, not a gate.

### 4. Build and Execute the Prompt

Construct the prompt for the mode (see templates above). Always include:
- Both preambles (`$EMPIRICAL_PREAMBLE` + `$SUCCESS_CRITERIA`) and the read-only note (`$READ_ONLY_NOTE`)
- Clear scope (what to review)
- Specific focus areas
- Instruction to be direct and cite file:line references
- An explicit instruction that a clean result must be an evidenced per-focus-area verdict, not a bare "no findings"

Write the prompt to `<SCRATCH>/gemini-prompt.txt`, capture any command output Gemini needs (such as a diff) into a file first, then run the wrapper with the canonical form and read the output file.

**`--dir` matters.** Gemini uses it as its workspace and refuses to read files outside it. Point `--dir` at the directory that contains every file you want reviewed.

### 4a. Files outside the workspace

If a file you need reviewed lives outside `--dir`, Gemini errors with `Path not in workspace: Attempted path "..." resolves outside the allowed workspace directories`. Trust flags don't help - this is a workspace-boundary limit. Two workarounds:

1. **Point `--dir` at a parent directory** that contains every file you need, so Gemini can grep/discover the files itself.
2. **Inline the file contents into the prompt file itself.** Write the prompt (preambles + instructions, ending with a `# File: path/to/foo.sh` marker line), then append the real file body with a plain `cat`:

   ```bash
   cat <PROJECT_DIR>/path/to/foo.sh >> <SCRATCH>/gemini-prompt.txt
   <SKILL_DIR>/gemini-exec.sh --dir <PROJECT_DIR> --prompt-file <SCRATCH>/gemini-prompt.txt > <SCRATCH>/gemini-out.txt 2>&1
   ```

   Inlining is the right choice for small fixed sets of files; pointing `--dir` up is the right choice when you want Gemini to discover files itself.

### 4b. Transient failures (503, UNAVAILABLE, "high demand")

Gemini's API sometimes returns 503 / `UNAVAILABLE` / "model is currently experiencing high demand". Treat these as transient infrastructure noise, not as a verdict:

1. Retry once with ~30s backoff.
2. If the retry also fails, surface the failure as "Gemini infra unavailable, no review produced" - do NOT fall through to a guessed answer or silently substitute Claude's own opinion.
3. Offer the user the choice to retry later, fall back to another reviewer (for example Codex), or skip the second-opinion step.

A `500 INTERNAL` behaves differently: the CLI's own retry loop can burn the WHOLE call timeout with no output (`status: 500` repeated in stderr). Do not just raise the timeout. Retry once with the review packet inlined on stdin (so Gemini makes no file-tool calls, which are retried too) and cap it at about 600 s; if that also fails, surface it as above.

A 503 "high demand" storm can burn the whole timeout the same way: the output holds only `Attempt N failed with status 503. Retrying with backoff...` lines and no review. After one failed re-run, mark the leg unavailable and stop retrying. A third attempt in the same window only costs time. A run that ends at the timeout (exit 124) with `TypeError: fetch failed sending request` retry lines is the same transient class: one re-run with the input cut to the code only and a longer `--timeout` can complete where the first run did not, and a second failure means unavailable. If Gemini times out on every run on one host for days, treat it as a host outage: run it in the background, mark it unavailable at the first timeout, and do not wait for it. Once the outage ends, go back to the one-re-run rule above. Inside a `review-swarm` quick panel its own one-attempt rule wins.

### 4c. Handle Gemini's "I need help" responses

If Gemini's output says it couldn't verify something - missing access, credentials, an external system it can't reach, context it doesn't have, or a command it needs you to run - **do not suppress or paper over that**. Treat it as a first-class finding:

- Read what Gemini asked for.
- Run the command, fetch the credential, grant the access, pull the log/config/dashboard, or supply the missing context.
- Re-run Gemini with the extra information attached to the prompt.

This round-trip is the whole point of the empirical-verification preamble. Guessed answers are worse than "I don't know, here's what I need."

### 5. Synthesize and Present

**Always lead with the exact model that ran, verbatim** - a `MODEL: <id>` line read back from the actual invocation (the wrapper's `::GEMINI-MODEL::` line; if `::GEMINI-FALLBACK::` fired, add `(fallback)`). This is mandatory on every run, standalone or as a `review-swarm` leg - the orchestrator reads this line back to name the leg. Do not omit it and do not assume the pin: state what actually ran.

After receiving Gemini's output:

1. **Present Gemini's findings** clearly, attributed as "Gemini found:" (under the `MODEL:` line above)
2. **Add your own assessment** - agree, disagree, or add nuance to each finding
3. **Highlight disagreements** - where Claude and Gemini see things differently, this is the most valuable signal
4. **Prioritize** - rank findings by severity/impact
5. **Recommend actions** - concrete next steps based on the combined review

(When this skill runs as a `review-swarm` leg, skip steps 2-5: return Gemini's findings only.)

Format the output as:

```
MODEL: <exact model id this run>

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

### 6. Interactive Follow-up

After presenting results, offer:
- "Want me to fix any of these issues?"
- "Want me to ask Gemini to dig deeper into any specific finding?"
- "Want me to run another review with a different focus?"

## `--full-context` flag (any mode)

Use `--full-context` (or the user phrasing "full context", "whole conversation", "this session") to attach the **current session transcript + the live state of files touched during the session** to the review prompt. The flag composes with any mode - it doesn't replace the mode, it gives the reviewer the full conversation as background.

When to use it:
- End-of-session sanity check ("did we miss anything across all this?")
- Skill / workflow design review where the conversation IS the work product
- Plan or build review where decisions made earlier in the session aren't captured in the diff

When NOT to use it:
- Reviewing a clean diff or single file - wasteful; the scoped mode is already cheaper and more focused
- Very small sessions - the marginal context isn't worth the cost
- Very large marathon sessions - won't fit Gemini's input window; scope down or summarise first

### How to assemble it

There's no dedicated tooling required - **assemble the relevant files and context yourself and inline them** into the prompt:

1. **Locate the session transcript** (the conversation record for the active session).
2. **Compress it.** Drop system-reminder blocks, repeated skill-load echoes, and the bulk of large repeated tool-result bodies (keep a head + tail of each). Drop file-content tool results for files that still exist on disk - you'll attach those fresh next.
3. **Inline the working files.** For every file written/edited during the session, append its `path` plus its **current contents from disk** (disk wins over any snapshot in the transcript).
4. **Sanity-check size.** If the assembled prompt gets close to the model's input window, warn the user and offer to scope down (last N turns, only files touched recently, etc.).
5. **Send** with the standard headless invocation.

List the touched files with a plain command (`git diff --name-only main...HEAD > <SCRATCH>/gemini-touched-files.txt`), then build the prompt file yourself (read each file, append a `# File: <path>` marker plus its current contents) rather than a shell loop - restrictive harnesses block `for`/`while` loops. Prepend both preambles, the read-only note, and the full-context framing before the first file, then run the wrapper with `--prompt-file`.

Full-context framing to include after the preambles: "You are reviewing the entire session below - what we did, why, and how. Files touched are attached as path + current contents. The verify-empirically rule still applies. Look for: decisions made on incomplete data; steps skipped that should have been verified; files left in an inconsistent state; tests not run / claims not verified; mismatches between what we said we did and what the diffs show. If the work holds up, give an evidenced per-area verdict - not a bare 'verified, no material findings'."

Models with a small context window can't take a full-session review - either send a digest (pre-summarise the session) or route full-context reviews to Gemini, which has the largest window of the review models.

## Multi-Model Review

For maximum coverage, run Gemini and Codex reviews in parallel (or use the `review-swarm` skill, which fans out all four review legs and synthesizes):

```bash
# Gemini pass (fast)
<SKILL_DIR>/gemini-exec.sh --dir <PROJECT_DIR> --prompt-file <SCRATCH>/gemini-prompt.txt > <SCRATCH>/gemini-out.txt 2>&1

# Codex pass (slower - usually the long pole): the review-with-codex skill's wrapper, a sibling folder
<SKILL_DIR>/../review-with-codex/codex-exec.sh --mode review --dir <PROJECT_DIR> --prompt-file <SCRATCH>/codex-prompt.txt > <SCRATCH>/codex-out.txt 2>&1

# Claude reads both out files and synthesizes
```

Multiple independent models reviewing the same code catch more issues than any single model - but only when each finds *real* issues. If they all return evidenced clean verdicts, that's a stronger signal than any one alone.

**Calibration - Gemini is the faster but shallower reviewer.** In past disagreements Gemini has under-reported where a slower, deeper reviewer caught the real bug (returning "no findings" or "safe to ship" on defects another model flagged), and it runs noticeably faster. That record comes from earlier, faster Gemini models; the current default is not yet calibrated, so keep the rule until your own runs show otherwise. Treat a bare Gemini "all clear" as the **weakest** single signal - never let it alone gate a ship decision; pair it with a second reviewer or the diff itself before trusting a clean pass.

## Configuration

### Model Selection

The default and fallback models are the `MODEL` and `FALLBACK_MODEL` variables near the top of `gemini-exec.sh`. That is the only place to change them; this file deliberately names no version, because versions rot. The default is Google's top model, with a 1M-token input window and built-in thinking. The fallback is a faster model that a free key is more likely to be allowed to call. Older builds are several generations behind and a last resort.

To check for a newer model, list what your key can call: `GET https://generativelanguage.googleapis.com/v1beta/models` with your key in the `x-goog-api-key` header, then test one short call before you change the pin.

Gemini CLI has no `--effort` / `--thinking` flag, so "high effort" is not a settable per-call knob; the model does its own thinking by default.

### Google Search Grounding

Gemini CLI has built-in Google Search grounding, but this skill's read-only policy turns it off on purpose (see `review-policy.toml`): a review reads the repo and the material it is given. If an outside fact matters, name it and fetch it yourself.

### Rate Limits (Free Tier)

AI Studio API key free tier: about 1,000 requests/day. Sufficient for review use cases.

## Edge Cases

- **Gemini not installed**: install with `npm install -g @google/gemini-cli` and retry
- **API key missing**: the wrapper exits 2 with "GEMINI_API_KEY is not set". Export the key in the environment the wrapper runs in.
- **`Path not in workspace` error**: see "Files outside the workspace" above - point `--dir` up or inline file contents
- **`read_file` refuses a git-ignored path INSIDE the workspace** (for example a `.venv`'s installed library source, `... is ignored by configured ignore patterns`): a different limit from "Path not in workspace". Inline that file's contents (or a focused excerpt with line numbers) into the prompt yourself.
- **Gemini says it cannot run a command, or a step is "denied by policy"**: expected. Run the command yourself and re-run Gemini with the output attached (see 4c). Never switch to yolo to get past it
- **Folder is not trusted / review aborts silently**: make sure `--skip-trust` is on the call (the wrapper does this; it matters in a fresh worktree Gemini has not trusted)
- **`--policy` rejected as an unknown argument**: the Gemini CLI is too old for the policy engine; update it (`npm install -g @google/gemini-cli`)
- **Very large input**: put it in `--stdin-file` (or a large `--prompt-file`) rather than `-- "PROMPT"`, which is capped at ~131000 bytes
- **Exit 0 but an empty output file**: a failed leg, not a clean one. The wrapper hides stderr on success. Re-run once; if it is empty again, mark the review unavailable.
- **`JavaScript heap out of memory` inside the CLI** on one particular input: re-run once; if it dies the same way, mark the review unavailable (a larger `NODE_OPTIONS=--max-old-space-size` did not help in testing)
- **503 / UNAVAILABLE / "high demand"**: retry once after ~30s; if it still fails, surface the failure rather than guessing
- **Large codebase**: scope to specific files/directories rather than whole-repo review
- **Gemini disagrees with Claude**: present both perspectives - the disagreement itself is valuable signal
- **Gemini hallucinates file paths**: cross-check all file:line references before presenting to the user
- **Empty diff**: if reviewing uncommitted changes and there are none, tell the user and offer alternatives

## Example Invocations

```
# Quick review of uncommitted changes
/review-with-gemini code

# Review a specific file
/review-with-gemini code src/main.py

# Stress-test a decision
/review-with-gemini decision "Should we migrate from Firestore to PostgreSQL?"

# Critique a plan
/review-with-gemini plan docs/migration-plan.md

# Post-build audit
/review-with-gemini build

# Codebase health check for a project
/review-with-gemini codebase my-project

# Full-session review (whole conversation + working files)
/review-with-gemini build --full-context
/review-with-gemini decision "did we miss anything in this session?" --full-context
```
