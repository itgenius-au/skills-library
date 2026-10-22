---
name: review-debate
description: "Orchestrate multi-round debates between Claude, Gemini, and Codex for higher-quality reviews. Three rounds: independent review, targeted challenge on disputes, and synthesis with self-challenge. Triggers on: review debate, review-debate, review with debate, ai debate, debate this, three-model review, consensus review, multi-model debate, 3-way review."
argument-hint: "[mode: code|decision|plan|build|codebase] [target: file path, branch, or description]"
---

# Review Debate - Multi-Model Debate & Consensus Review

Orchestrates a structured 3-round debate between your primary agent (in-process), Gemini, and Codex to produce higher-quality reviews than any single model. Models review independently, challenge each other's disputed findings, and converge on consensus - with minority opinions preserved.

**Use this instead of one-shot `/review-with-gemini` or `/review-with-codex` when the stakes are high enough to justify several minutes and 4 CLI calls.** Reach for it when a `review-swarm` surfaces a genuine disagreement worth litigating.

> **Model pins live in your sibling review skills, not here.** This skill drives Gemini and Codex through the same wrappers as `review-with-gemini` / `review-with-codex` (`gemini-exec.sh`, `codex-exec.sh`). So it reuses their model pins, their guards, and their invocation form. Do NOT restate model versions in this file (they rot). Prepend the shared verification preamble (below) to every model prompt - the debate is only as good as its evidence discipline.

## When to Use

- **High-stakes code review**: Changes to auth, payments, data pipelines, or anything where a missed bug is costly
- **Architectural decisions**: "Should we migrate to X?" - get three independent perspectives before committing
- **Plan validation**: Critique an implementation plan from three angles before building
- **Pre-merge build audit**: Final check before merging a large feature branch
- **Codebase deep-dive**: Comprehensive health check with three models exploring independently

**When NOT to use** (use one-shot `/review-with-gemini` or `/review-with-codex` instead):
- Quick sanity checks on small changes
- Style or formatting reviews
- Anything where speed matters more than thoroughness

## Prerequisites

Same as the sibling review skills:
- **Gemini CLI**: `npm install -g @google/gemini-cli`
- **Codex CLI**: `npm install -g @openai/codex`
- **Gemini API key**: `GEMINI_API_KEY` exported in the environment the wrapper runs in (see `review-with-gemini`). Never handle the key in your own shell commands.
- **Codex auth**: OAuth cached at `~/.codex/auth.json` (run `codex login` if expired)

## Invocation form

Every Gemini and Codex call in this skill uses the invocation form from `review-with-codex` / `review-with-gemini`. Write each prompt to a file in a scratch directory. Then run the wrapper as ONE plain command with literal absolute paths and a plain `>` redirect. Avoid command substitution, shell variables, `export`, and `cd ... &&` in the call: some agent harnesses (Claude Code in a worktree session, for one) refuse them.

Placeholders (paste each one literally, never as a shell variable):
- `<REVIEW_SKILLS>` = the parent of this skill's base directory (the folder that holds the sibling `review-with-*` skills).
- `<SCRATCH>` = your scratch directory.
- `<PROJECT_DIR>` = the absolute path of the repo under review.
- `<RANGE>` = the diff range.

When `<REVIEW_SKILLS>` contains a space, start each wrapper call with `bash` and quote the path, so the command name stays the literal `bash`.

In a worktree-bound session, `git -C <PROJECT_DIR>` must point at your own worktree (or a review snapshot of it); a harness may refuse git aimed at another checkout.

## The verification preamble

Prepend this to every model prompt (the same empirical + evidenced-verdict discipline the one-shot skills use):

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
**Default**: Current working directory. If a subdirectory/project is given, pass it as `--dir`.

## Workflow

### Step 1: Determine Mode and Target

Parse the user's request to identify:
- **Mode**: code, decision, plan, build, or codebase
- **Target**: file path, branch name, plan file, or inline description
- **Project directory**: which project or repo

If unclear, ask the user. Default to `code` mode reviewing uncommitted changes.

### Step 2: Gather Context

How context reaches each model depends on the mode:

**Code / Build / Codebase modes**: Do NOT embed diffs in the prompt files. A prompt over ~131000 bytes makes the wrappers exit 2. Codex re-derives the diff and log itself: its read-only sandbox still runs `git diff` and `git log`. Gemini runs under a read-only policy and cannot run any command. So for code and build modes, the caller captures Gemini's input once with plain commands and passes it with `--stdin-file` in BOTH rounds. Codebase mode needs no input file: both models read the files in `--dir`. Only the primary agent (in-process) reads the context directly.

Each block below is one command. Code mode (for uncommitted changes, drop `<RANGE>`):

```bash
git -C <PROJECT_DIR> diff <RANGE> > <SCRATCH>/debate-input.txt
```

Build mode: two commands, the log first, then the diff appended. `<RANGE>` defaults to `main...HEAD`.

```bash
git -C <PROJECT_DIR> log --oneline -20 > <SCRATCH>/debate-input.txt
```

```bash
git -C <PROJECT_DIR> diff <RANGE> >> <SCRATCH>/debate-input.txt
```

**Code mode with a file target** (for example `/review-debate code src/main.py`): there is no diff and no input file. Both prompt files say "Review `<path>`; read it in the workspace", and Gemini runs without `--stdin-file`.

**Decision / Plan modes**: The context is user text or a plan file. Read it and paste it into both prompt files (Step 3).

### Step 3: Write the Round 1 prompt files

There is no key step: `gemini-exec.sh` reads `GEMINI_API_KEY` from the environment.

Write `<SCRATCH>/debate-r1-codex.txt` and `<SCRATCH>/debate-r1-gemini.txt`. Both files hold the Round 1 prompt below. Only the input line differs (code and build modes):
- Codex file: "Run `git diff <RANGE>` to see the changes (build mode: also `git log --oneline -20`)."
- Gemini file: "The changes are on stdin (build mode: the git log, then the diff). You cannot run commands; read files in the workspace if you need more context."

For a file target, both files say "Review `<path>`; read it in the workspace" instead. For decision and plan modes, paste the context into both files.

```text
<the verification preamble>

Mode: <mode>. Target: <target>.
<decision/plan modes: the context>
<the per-model input line (code/build modes)>

<the mode-specific preamble from the table in Step 4>

For each issue or insight you find, provide:
- Finding: what you found
- Severity: critical, high, medium, or low
- Evidence: file:line reference or specific reasoning
- Confidence: 1-10 (how sure are you?)
- Proposed Action: what should be done

Be thorough but prioritize. Focus on issues that matter, not style nitpicks.
Report a maximum of 10 findings, ranked by severity. A clean result is fine: report it
as an evidenced per-area verdict, not a bare 'no findings'.
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

**Then fire Gemini and Codex in parallel.** Issue both calls in the same response as background tasks. **Use different timeouts: Gemini about 180 s, Codex about 600 s** - a deep Codex review at `xhigh` runs roughly 5-7 minutes, so a uniform 2-minute limit would kill Codex mid-review. Codex is the long pole: collect results as each lands, and **don't block synthesis on a model that wedged or timed out** - degrade gracefully (see Error Handling). The wrappers write their output file only when the run ends, so an empty file while a call runs is normal: do not kill it. A wedged Codex handshake is caught by `codex-exec.sh`'s own watchdog, which exits 124 and tells you to relaunch attached.

Both models read the prompt files written in Step 3.

Gemini (background call 1, caller timeout about 180 s). Keep `--stdin-file` for code/build with an input file; drop it for a file target and for codebase/decision/plan:

```bash
<REVIEW_SKILLS>/review-with-gemini/gemini-exec.sh --dir <PROJECT_DIR> --timeout 170 --stdin-file <SCRATCH>/debate-input.txt --prompt-file <SCRATCH>/debate-r1-gemini.txt > <SCRATCH>/debate-r1-gemini-out.txt 2>&1
```

Codex (background call 2, caller timeout about 600 s). Read-only sandbox; the wrapper adds `< /dev/null`:

```bash
<REVIEW_SKILLS>/review-with-codex/codex-exec.sh --mode review --dir <PROJECT_DIR> --timeout 590 --prompt-file <SCRATCH>/debate-r1-codex.txt > <SCRATCH>/debate-r1-codex-out.txt 2>&1
```

Read each output file when its call completes. If a call fails (non-zero exit or an empty output file), re-run it once. If it fails again, degrade as in Error Handling.

**Note:** Keep both Round 1 output files. Round 2 does not use session resume: the resume options of both CLIs pick the newest session on the machine, which can be another session's run when sessions run in parallel. Round 2 starts a fresh call and gives each model its own Round 1 report (Step 7).

For **decision/plan modes**, the context is already in the prompt files (Step 3).

**Mode-specific preambles:**

| Mode | Preamble |
|------|----------|
| code | "Review the changes named in the Target line. Focus on correctness, edge cases, security vulnerabilities, performance issues, and maintainability." |
| decision | "I'm considering the following decision. Play devil's advocate. What are the risks? What could go wrong? What alternatives should I consider? What am I not thinking about?" |
| plan | "Critique this implementation plan. Is the approach sound? What's missing? What are the riskiest parts? Is the sequencing right? Is it over-engineered or under-engineered?" |
| build | "Audit the recent changes on this branch (the last 20 commits and the diff range in the Target line). Does the implementation look correct and complete? Any bugs, edge cases, or security issues? Missing tests or error handling?" |
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

**Fast path - verify directly instead of debating when you can.** If a disputed finding is independently **code-verifiable** (you can settle it by reading the referenced file or running one command yourself), do that and **skip the Round 2 model round-trip for it** - a model round-trip to re-litigate something you can check in 30 seconds is wasted latency and cost. Send to Round 2 only the disputes that genuinely need another model's *judgment*: design trade-offs, risk calls, anything with no ground truth in the code. If every dispute is code-verifiable, resolve them all directly and go straight to synthesis (Step 8), noting "Round 2 skipped - disputes resolved by direct verification." In the output, mark which disputes were settled by verification vs. by debate.

Send the remaining (judgment-needing) disputes to Gemini and Codex for challenge. The primary agent acts as **moderator only** in this round - does NOT add its own rebuttal.

Write one Round 2 prompt file per model: `<SCRATCH>/debate-r2-codex.txt` and `<SCRATCH>/debate-r2-gemini.txt`.

```text
<the verification preamble>

Mode: <mode>. Target: <target>.
<the mode-specific preamble from Step 4>
<decision/plan modes: the same context as in Round 1>
<the same per-model input line as in Round 1 (code/build modes)>

Three AI models independently reviewed this target. Your own Round 1 review comes first, then the disputed findings only.

## Your Round 1 review
<this model's final Round 1 report only, not the CLI log>

## Disputed items
<each disputed finding, with each model's position>

For each disputed item:
1. State whether you agree or disagree with each model's position.
2. Give more evidence for your view (read the files; Codex may also run read-only git commands).
3. If you changed your mind since Round 1, say so and explain why.

Focus ONLY on these disputed items.
```

Two rules for the Round 2 prompt files:
- Paste only the model's final report from its Round 1 output file, not the CLI log. A Codex output file holds the whole tool transcript (it can be over 200 KB). The final report is the last message at the end of the file.
- Keep each Round 2 prompt file under ~131000 bytes, because the wrappers exit 2 above that. If it is too big, keep only the disputed findings with their evidence, and say in the prompt what you cut.

**Tip:** For sharper critique, frame Round 2 as reviewing another model's output: "You're reviewing findings from two other AI models. Identify weak assumptions, missed edge cases, and better alternatives." This yields more critical, less deferential responses.

Fire both in parallel as background tasks, about 600 s for Codex and about 180 s for Gemini (same long-pole asymmetry as Round 1). Each is a fresh call: its prompt file carries its own Round 1 report, so no session resume is needed.

Gemini R2 (background call 1). Keep the SAME `--stdin-file` as Round 1, or none if Round 1 had none:

```bash
<REVIEW_SKILLS>/review-with-gemini/gemini-exec.sh --dir <PROJECT_DIR> --timeout 170 --stdin-file <SCRATCH>/debate-input.txt --prompt-file <SCRATCH>/debate-r2-gemini.txt > <SCRATCH>/debate-r2-gemini-out.txt 2>&1
```

Codex R2 (background call 2):

```bash
<REVIEW_SKILLS>/review-with-codex/codex-exec.sh --mode review --dir <PROJECT_DIR> --timeout 590 --prompt-file <SCRATCH>/debate-r2-codex.txt > <SCRATCH>/debate-r2-codex-out.txt 2>&1
```

If a Round 2 call fails (non-zero exit or an empty output file), re-run it once. If it fails again, degrade as in Error Handling.

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
## Review Debate Results

**Mode**: [code/decision/plan/build/codebase]
**Target**: [what was reviewed]
**Models**: Primary agent (in-process) + Gemini + Codex
**Model pins**: state the EXACT ids used this run - Gemini `<the model gemini-exec.sh pinned this run>` and Codex `<the model codex-exec.sh pinned this run>`. Do not write "as resolved at run time"; name the actual ids.
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
| `gemini-exec.sh` exits 2 with a key error | `GEMINI_API_KEY` is not set in the wrapper's environment (see review-with-gemini). Degrade to a 2-model debate and say so. |
| Codex auth expired | Report the error and instruct: "Run `codex login` to re-authenticate" |

**Timeouts**: Codex about 600 s, Gemini about 180 s (Codex at `xhigh` runs roughly 5-7 minutes; a uniform 120 s would kill it mid-review). Set the timeout on the background calls. The wrappers' own `--timeout` (170 s Gemini, 590 s Codex) ends a slow leg with exit 124. If Codex emits no output at all, the `codex-exec.sh` watchdog exits 124 and tells you to relaunch attached: treat it as a wedged handshake, not "found nothing".

## Edge Cases

- **Gemini hallucinates file paths**: Cross-check ALL file:line references from external models against the actual codebase before including in results
- **Models produce unstructured output**: If a model ignores the structured format, extract findings manually from the free-text output
- **Large diffs**: For diffs over 500 lines, consider scoping to specific files rather than the full diff
- **Subproject context**: When debating a subproject, pass its absolute path as `--dir` to both wrappers (and capture Gemini's input with `git -C <that path> ...`) so models have the right filesystem context
- **Round 2 context**: Pass the same `--dir` to both wrappers in Round 2, and the same `--stdin-file` to Gemini in code/build mode, so the models can re-examine the disputed files

## Configuration

### Model Selection

Model pins are **owned by your `review-with-codex` and `review-with-gemini` skills**, not restated here - restating is exactly how a multi-model skill drifts to a stale version. Match whatever those skills currently pin. The primary agent runs in-process on its own session model.

### Performance

| Metric | Value |
|--------|-------|
| CLI calls | 4 normally (2 per round x 2 models), plus at most one re-run per failed call; often 2 when the Round 2 fast path applies |
| Wall-clock time | roughly 5-8 min (Codex at `xhigh` is the long pole, 5-7 min; Gemini about 2 min). Skipping Round 2 is about one Codex review of wall-clock. |
| Cost multiplier | about 4x a single one-shot review (less when Round 2 is skipped) |

## Example Invocations

```
/review-debate code                              # Debate uncommitted changes
/review-debate code src/main.py                  # Debate a specific file
/review-debate decision "Migrate to Postgres"    # Debate an architectural decision
/review-debate plan docs/migration-plan.md       # Debate a plan before building
/review-debate build                             # Debate recent build vs main
/review-debate codebase my-project               # Debate a project's health
```
