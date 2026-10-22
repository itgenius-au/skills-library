---
name: session-wrap
description: "End or checkpoint a working session cleanly with four distinct intents - done (complete: integrate and close), pause (staying in this window), pick up (window closing, compacting or context full: hand off a self-sufficient resume prompt), or skill sweep (deep review of the session's skill and doc lessons, closes nothing). Summarizes work, captures durable docs, and handles git state."
argument-hint: "[done|pause|pick up|skill sweep] [project-name]"
---

# Session Wrap

Use this skill at the end of a working session in a project or worktree.

The goal is to preserve useful state, keep documentation current, and avoid leaving ambiguous git or deployment state for the next person.

## Step 1: Detect Active Project

Identify the project from:

- Current working directory.
- Git root.
- Worktree path.
- Files changed during the session.
- What the user said the session was about at the start.

If multiple repos were touched, handle each separately. Wrap nested repos before the parent repo that contains them.

Run:

```bash
pwd
git rev-parse --show-toplevel
git status --short --branch
git branch --show-current
```

## Step 2: Summarize The Session

Prepare a concise summary before changing git state.

**Output style.** Fill the table and notes below in the reader's active output style. If none is set, default to: answer-first, short sentences, plain words, no idiom. Keep every required section; the style governs wording only, never the structure.

Include:

| Section | Content |
|---|---|
| Done | Features, fixes, reviews, deploys, docs completed |
| Discovered | Findings, gotchas, decisions, external service behavior |
| Pending | Started but unfinished work, each item with a **Recommend:** line |
| State | Current branch, dirty files, pushed/unpushed commits, deployment state |

If the session included production work, include exact deploy targets, revisions, smoke checks, and rollback pointers.

**Every pending or open item carries a recommendation.** Write each one as the item, what it waits on, and **Recommend:** the action you advise, in a few words. When you have no basis for one, write "No recommendation: <why>" instead of leaving it blank. A list of open items with no recommendations is hard to act on.

**Before you list an item as blocked on the user, check whether you can do it yourself.** "Waits on <person>" is true only when the step needs access or a decision you do not have. Check your own access first: the CLIs on this machine, stored credentials, the tools in this session. Access alone is not approval: authorization changes, secret or data writes, irreversible actions and external messages still need the owner's OK, or a draft. If you can do the step and the wrap mode allows it, do it now, or list it as pending with **Recommend:** do it next session. List an item as blocked on a person only with the missing access or decision named.

### Model fit check (all modes)

After the summary, add a short **model fit** note so model choices can be calibrated over time.

1. **Name the model that ran this session** (self-identify from the environment), and note the reasoning effort used.
2. **Judge it against the work actually done**, using four signals: *reasoning depth* (subtle multi-step correctness such as concurrency, ordering, idempotency, auth precedence, versus mechanical edits); *impact* (production data, money, security or irreversible effects versus low-stakes and reversible); *breadth* (large cross-file diffs held in view at once versus small localized changes); *autonomy* (long unattended agentic runs versus interactive back-and-forth).
3. **Give a one-line verdict:** **Well matched**; **Over-powered** (a cheaper tier would very likely have done this as well); or **Under-powered** (subtle-correctness or high-impact elements where a stronger tier was worth it - name the specific thing).

Keep it to a few lines; a trivial session gets one ("Model fit: fine, trivial session"). In **pick up** mode the handoff (Step 9) adds a forward-looking suggestion for the model the *next* session should start on, graded against the remaining work. Compute that at the handoff, not here.

## Step 3: Decide Wrap Intent

Four distinct intents, with different downstream behaviour. The key split is whether this window stays open:

- **done**: work is complete. Integrate to the default branch and clean up (worktree removed, branch pruned). The next session starts fresh, and when the closeout finishes with nothing left open, this conversation is ready to archive (exact closing lines in Step 9).
- **pause**: work continues in THIS window - you are staying, usually waiting on something external. Make the work durable (commit and push) and keep the worktree mounted, but do NOT clean up and do NOT emit a full resume prompt. The open window keeps the context alive, so the full handoff would be wasted.
- **pick up**: this window is CLOSING or being COMPACTED - work continues in a future or freshly-compacted session. Preserve everything (worktree and branch stay) and hand off a single copyable resume prompt. Write it to be self-sufficient enough to survive a full window close, even when you expect to resume right after compacting (a compact keeps only a little context).
- **skill sweep**: a deep review, not a close. Run the deep session scan and the deep-pass subagents (Step 4), apply the auto-apply doc and skill lessons, and emit the Recommendations block. Close NOTHING: no worktree closeout, no merge, no archive line, no resume prompt. The window stays open. See "Skill sweep" at the end of Step 4.

Infer from the user's words:

| User wording | Intent |
|---|---|
| `done`, `finished`, `close it out`, `ship it`, `merge it` | done |
| `pause`, `hold`, `waiting on`, `keep the window open`, `standby` | pause |
| `pick up`, `pickup`, `compact`, `continue later`, `new session`, `for now` | pick up |
| `context full`, `context is filling up`, `running out of context`, `compacting soon` | pick up |
| `skill sweep`, `sweep the skills`, `deep review without closing` | skill sweep |
| `wrap up` with no qualifier | ask before proceeding (worktree cleanup is destructive) |

**A full context window: start pick up early, and start nothing new.** When the user says the window is filling up, believe it and start the wrap now, not after one more task. A handover written with room to spare is complete; one written against the limit gets cut off. During the wrap, finish a half-done edit if you must, but start no new build, module or investigation. Recommendations do not hold the resume prompt back (Step 7, "Context full").

**"Pick up" at the START of a session means resume.** When a session's first message is "pick up" (or "pickup") followed by an instruction to re-read a thread or continue open items, the user is resuming earlier work in this window: do the work, and do not run this wrap. The pick up intent applies only when the user is closing or compacting the window. When the pasted resume prompt has `Read first` and `Verify` lines, read the brief at that branch and commit, check each `Verify` value live, and report any drift before acting on the brief. Re-dispatch a handed-over subagent only for the part its output does not already cover.

When in doubt and a worktree exists, default to **pick up**, never done - never auto-delete a worktree. pick up, pause and skill sweep are all non-destructive.

## Step 4: Scan For Documentation Updates

Review the session for anything that should outlive the conversation.

### Deep session scan (done, pick up and skill sweep)

Do not rely on live memory alone - late in a long or compacted session it has faded. In done, pick up and skill sweep, run the bundled deterministic scan first and let its evidence feed both the doc decision and the improvement decision (below):

```bash
bash "$SKILL_DIR/scripts/session-scan.sh"
```

(`$SKILL_DIR` is this skill's base directory, printed when the skill loads. Invoke it through `bash` so a lost executable bit does not matter. It needs only `python3`.) The scan resolves THIS session's transcript, stitches its sibling windows on the same worktree, filters injected content (system reminders, task notifications, skill bodies, tool output, heartbeats), and prints a bounded digest: `EVIDENCE <file>:<line> | role | directive | quote` lines, `INFERRED ...` lines, `SPAN <file>` lines for the transcripts it read, and a final `DEEP_CANDIDATES=0|1`. It degrades cleanly (one `NOTE` plus `DEEP_CANDIDATES=0`) and never breaks a wrap. It never loads a whole transcript into your context. It looks for:

- **Explicit directives** (typed by the user, fire at n=1): "from now on", "going forward", "next time", "update the skill", "why isn't this a skill", "make this a hook", "always ...", "never ...", and scope rejections such as "I didn't ask for that".
- **Corrections and redos** (inferred, need n>=2): the user rewording the same instruction, "no, ...", "that's wrong", "are you sure".
- **Repeated tool errors** (inferred, need n>=2): the same failure twice or more. Pure harness noise (a worktree-isolation refusal, an expired MCP login prompt) is ignored.

**Run the scan from inside this session's worktree.** It matches transcripts by working directory, so from a main checkout it can match every session that ever ran there. If you left your worktree mid-session (for example with `ExitWorktree(action: keep)`), re-enter it with `EnterWorktree(path: ...)` first. Then check that each `EVIDENCE` line names this session's transcript.

When `CLAUDE_CODE_SESSION_ID` is set, the scan finds `<session id>.jsonl` by searching every folder under the projects directory, and uses it as the seed transcript before any path-based guessing. A session that entered and exited worktrees keeps writing to its launch folder, so a path-based match alone can read an empty folder. If the variable is unset or no file matches, the scan prints one `NOTE` and falls back to path-based discovery. It never prints a `SPAN` line for a file that does not exist.

If it finds 0 evidence on a seed transcript over 200 KB with 5 or more typed user turns (a genuine user turn longer than an ack such as "go"), it prints `NOTE SCAN-SUSPECT: 0 evidence on a <size> transcript; check the transcript path`. Treat that note as "check the path", never as "nothing found". With fewer typed turns it prints `NOTE 0 evidence is expected: only <n> typed user turns ...` instead: an autonomous session where the user typed only "go" has nothing to find. This note explains the scan only. It is never a reason to skip the deep pass (see "Deep pass").

Outside a git work tree, the scan still runs when `CLAUDE_CODE_SESSION_ID` names a transcript: it scans only that transcript and prints `NOTE not in a git work tree: scanning only this session's transcript`. With no id, it prints `NOTE not in a git work tree; deep scan skipped`.

The session-id transcript counts in full, whatever working folder each record carries, so a session that worked inside worktrees still has its evidence when it wraps from elsewhere. From a main checkout (not a linked worktree) with the session id resolved, the scan reads ONLY that transcript and prints `NOTE main checkout: scanning only this session's transcript`: the folder path appears in nearly every session that ever ran there, so it identifies nothing.

If `python3` or the transcript folder is missing, the scan skips with a `NOTE`. Then fall back to reading the transcript yourself in slices (`find "$HOME/.claude/projects" -name "${CLAUDE_CODE_SESSION_ID}.jsonl"`), or hand it to a subagent. Never load the whole file into your own context, and only the user's typed turns carry lessons: skip injected content such as system reminders, tool output, and skill bodies.

**Gating:** run the scan AND the deep pass (agents) when the intent is done, pick up or skill sweep (Step 3). pause uses the checklist and the improvement decision from memory and runs neither. A pick up is usually the longest window, where early corrections have faded most, so it gets the deep pass too. In pick up, also use the `EVIDENCE` lines to fill the handover's `Do NOT` and `Corrected` lines (Step 9).

To check the bundled scripts themselves, run `bash "$SKILL_DIR/scripts/tests/run-tests.sh"` (no credentials needed).

**Depth goes in project docs; keep memory and project instruction files lean.** Project docs (`docs/*.md`) are where comprehensiveness belongs: capture the full context, the *why*, how it works, and how to operate or reproduce it - err toward more detail. Memory files and `CLAUDE.md` are the opposite discipline: tight one-line pointers and routing, never doc-level prose (they load into every session). When a session surfaces a reusable *procedure*, it belongs in a skill, not one-off prose: a new skill or a behaviour change goes through the improvement decision below, and a lesson-type note to an existing skill auto-applies (see "Skill files: what auto-applies"). Strong bias: extend the relevant project's existing doc rather than create a new memory entry; reserve new memory for patterns that genuinely span projects.

Checklist:

- Architecture changed.
- Infrastructure or environment changed.
- External service behavior learned.
- New credentials, services, webhooks, or scheduled jobs introduced.
- Deployment process changed.
- Project instructions or routing became stale.
- A gotcha was discovered.
- A decision was made (every intent). Give each one exactly one home: an existing decisions block or bullet first, else this session's plan or build doc, else a new `docs/decisions/YYYY-MM-DD-<topic>.md`.
- A deploy or rollback happened.
- A reusable workflow emerged - a skill, not prose. A new skill or a behaviour change is a recommendation (improvement decision below); a lesson-type note to an existing skill auto-applies.
- A transferable rule is stuck in a dated doc (plan, deploy record, audit): promote it to `gotchas.md` or the evergreen topic doc. If this session restated a rule that already sits in an earlier dated doc, that promotion is overdue - do it now.
- Project-instruction routing: (a) any doc created or substantially extended this session gets a routing line; (b) re-read the existing lines for THIS session's feature area and confirm they still tell the truth (a stale index is read first, fixed last).
- Core docs exist AND are accurate: every project needs `docs/gotchas.md`; `architecture.md` and `deployment.md` only where something deploys. Re-read the ones touching this session's subject - an exists-but-wrong doc is worse than a missing one.
- Stale `AGENTS.md` fork: if an `AGENTS.md` duplicates `CLAUDE.md` and has drifted, make it a symlink to `.claude/CLAUDE.md` or maintain it deliberately.

Prefer project documentation over global memory.

Priority order:

| Priority | Target | What belongs there |
|---|---|---|
| 1 | Project `docs/architecture.md` | System shape, components, data flow |
| 1 | Project `docs/deployment.md` | Deploy commands, environment, verification |
| 1 | Project topic docs | Integration-specific behavior |
| 2 | Project `docs/gotchas.md` | Project-specific footguns |
| 2 | Project `.claude/CLAUDE.md` or `AGENTS.md` | Routing pointers to new docs |
| 3 | Shared or parent-repo docs | Cross-project patterns only |

Do not create new memory files for project-specific details when an existing project doc can be extended.

### How to apply updates (auto-apply, undoable)

Doc updates are **applied immediately, not proposed**. Proposed updates are almost never rejected, so a propose-and-wait round-trip is pure overhead. Write the updates, then present an undoable summary.

**Repo escape hatch:** if the repo's own `CLAUDE.md` / `AGENTS.md` explicitly requires propose-first for documentation changes, honour that instead - propose and wait. Auto-apply is the default, not an override of a repo that opted out.

1. **Read the target doc first** - understand what is already there; do not duplicate.
2. **Apply the updates directly** - write the doc / memory / instruction-file changes now, in this wrap, without stopping for approval.
3. **Prefer updating existing docs over creating new ones** - create a new doc only if the topic genuinely fits nowhere.
4. **Check routing** - if you created or renamed a doc, point the project's `CLAUDE.md` context section at it.
5. **Present an "Applied doc updates" summary** in the wrap output: one line per file - path, what changed, and the one-clause why. After the commit, add the SHA(s) and the exact undo command (`git -C <repo> revert <sha>` for the whole commit; `git -C <repo> checkout <sha>^ -- <file>` for one file). Any "undo X" reply is approval to revert immediately - do it, commit, and push the same way.
6. **Still propose-first (the only carve-outs):** deleting or retiring a doc, memory entry, or index line; rewriting substantial human-authored content; and anything privacy- or externally-sensitive. These are rare - everything additive auto-applies.

**Skill files: what auto-applies.** A skill file is half doc, half behaviour, so it splits on one test: *would the next run of the skill act differently, beyond knowing one more fact?* No: it is a doc update. Yes: it is a recommendation.

- **Auto-apply** (list it under "Applied doc updates", with the undo line): additive text in an EXISTING skill (its `SKILL.md` or a reference file) that does not change what the skill does. Examples: a Lessons or gotchas entry, a corrected fact (an ID, a path, a field name), a clarifying example.
- **Recommend** (improvement decision below): a new skill; any change to a skill's steps, their order, its triggers or description, its scripts or code, its guardrails, approval gates, or defaults; deleting or rewriting skill text; every hook and plugin change.
- **Unsure:** recommend.

If nothing qualifies, say "No doc updates needed" and move on.

### Improvement decision (skills, hooks, plugins)

Docs, and lesson-type notes in an existing skill, auto-apply above. New skills, skill behaviour changes, hooks, and plugins are a different class, and the PRIMARY way to surface them is **your own judgement of the conversation, not phrase-matching.**

**Run this self-assessment on EVERY done wrap, whether or not the user named it:** ask *"did a reusable procedure, workflow, or rule emerge this session?"* Look for a novel multi-step process, a non-obvious sequence, a workaround for how a system behaves, an integration recipe, or a correction that should hold next time. If it is plausibly reusable, recommend it (skill / hook / plugin / doc) - even if the user never asked and it happened once. The directive and error signals from the deep session scan are a **supplement** that catches explicit asks and repeated friction your memory may have dropped; they are not the trigger.

**How to judge (do NOT gate this on repetition):**

- **A clearly reusable procedure or rule fires at n=1** - your semantic call. If a future session would benefit from repeating what happened here (a working sequence, a recipe, a rule that should hold), recommend it even if it was unnamed and occurred once.
- **Explicit user directives fire at n=1** and are self-authorising: "from now on", "update the skill", "why isn't this a skill", "make this a hook", "next time do X", and scope rejections like "I didn't ask for that". (Assistant prose like "I've updated the skill" is not a directive.)
- **Weak or ambiguous friction signals need n>=2** - a bare repeated correction or a recurring tool error counts only when it recurs. The n>=2 bar is for THESE noisy signals, NOT for a procedure you judge clearly reusable.

**Escalation ladder - which target holds the lesson:**

| Signal | Target | Handling |
|---|---|---|
| A rule that was wrong or restated (especially twice) | `CLAUDE.md` / `gotchas.md` | doc auto-apply |
| A lesson, gotcha, or corrected fact for an existing skill | that skill's Lessons / notes | doc auto-apply |
| A reusable procedure (even once) or a re-typed prompt | a new skill, or a behaviour change in an existing one | recommend-only |
| Something that must happen every time | a hook | recommend-only |
| A lesson a second repo also needs | a plugin | recommend-only |

**Recommendations output block.** Emit one consolidated block as a numbered list (1, 2, 3), one item per candidate: the target (new skill `x` / fold into skill `y` / hook / plugin), the evidence quote (from the session), the proposed change in a clause, the next step (open a PR to wherever that skill lives; edit the hooks or plugin manifest for a hook or plugin), and a **Recommend:** disposition (approve / decline / defer) with a few words of why. End the block with one line: Reply "go" to accept every recommendation, or answer by number (for example "1: approve, 2: defer"). These are shipped at Step 7, not here. If nothing qualifies, say "No skill/hook/plugin recommendations" - that sentence covers recommendations ONLY.

**Applied-updates line (always, next to the Recommendations block).** Print one line: `Skill and doc updates applied: <list> | none`. List every auto-applied doc and skill update (for example a skill Lessons entry and its PR) by path or PR. A wrap that merged a skill Lesson and printed only "No skill/hook/plugin recommendations" reads as "no skill updates", so the applied updates always get their own line.

### Deep pass (done, pick up and skill sweep, required for a substantive session)

On a done or pick up wrap the deep pass is **required, not optional**, when `DEEP_CANDIDATES=1`, OR the session did **substantive multi-step work** (a real procedure, an integration, a debugging arc, a build - your judgement, not a phrase), OR it was compacted or very long, OR the user said "go deep". Treat `DEEP_CANDIDATES=1` as substantive. A dedicated agent then makes the reusability call on the actual transcript instead of leaning on your fading memory. Skip it only for a trivial session with nothing reusable.

**`DEEP_CANDIDATES=0` is never a skip reason on its own.** The scan reads only typed user turns, so an autonomous session (the user typed little more than "go") reads as empty even after hours of work. When the session made commits, opened or merged PRs, deployed, or ran a long tool-driven build or investigation, treat it as substantive: run the forced general-review subagent below. Skip only when the session was also trivial in what it did, not just in what the user typed.

**Deep pass line (always, in the done and pick up output).** Print exactly one line: `Deep pass: ran (<n> agents)` or `Deep pass: skipped because <reason>`. A skip names why the session was trivial; "not needed" and "0 candidates" alone are not reasons.

- **Candidates present:** dispatch one small subagent (a mid-tier or small model) per strong candidate (bounded, top 5; log any you drop - never silently cap). Each reads the transcript span the scan named and returns: is this a real reusable procedure or rule? which skill, doc or hook holds it? a drafted change? Merge its verdicts into the Recommendations block.
- **Forced but zero candidates** (compacted, long, or "go deep" with none found): run ONE bounded general-review subagent over the stitched spans, so "go deep" has real work - do not no-op.
- **In a context-full pick up,** dispatch the deep-pass agents in the background and do not wait for them: write and emit the resume prompt first (Step 7, "Context full"), then fold their findings in as deferred recommendations, or name them on the handover's `In flight` line if the window ends first.

### Sub-session sweep (native Claude app only: done and skill sweep)

In the native Claude desktop app, a session can open sub-sessions with `mcp__ccd_session__start_session` and archive them with `mcp__ccd_session_mgmt__archive_session`. A sub-session often runs a whole procedure on its own and is archived before the parent wraps, so its lessons never reach a wrap. This step sweeps the sub-sessions the wrapping session opened, including archived ones.

**When it runs.** In done, pick up and skill sweep, after the deep pass, when this session has the `mcp__ccd_session_mgmt__*` tools (in its tool list or its deferred-tool list). Without them (the CLI, a cloud session, a VM), print `Sub-session sweep: not the native app` and skip. pause skips it. In pick up, sweep only the sub-sessions that have finished (idle or archived), and list each one still running (id and title) on the handover's `In flight` line, so the wrap that follows can sweep it. In a context-full pick up, treat these agents like the deep-pass agents: dispatch them in the background, emit the resume prompt first, and do not wait for them.

1. **Find the sub-sessions.** Take every `mcp__ccd_session__start_session` call in this session that started a session (it carried a `prompt` or a `proposal_id`; a bare `initiation: offer` call only proposes one). Add `mcp__ccd_session_mgmt__list_sessions` with `linked: true`. Merge the two lists by id. Archived ones count. A sub-session id is not a CLI transcript id, so the deep session scan cannot find a sub-session: read it through the app tools.
2. **Skip the ones that swept themselves.** If a sub-session's own transcript holds a done, pick up or skill sweep wrap with a `Deep pass: ran` line, take its `Skill and doc updates applied:` line and its Recommendations as they are, and do not sweep it again.
3. **Sweep the rest.** Dispatch one small subagent per sub-session, in parallel, top 8 by work done (log any you drop; never cap silently). Each one reads the sub-session with `mcp__ccd_session_mgmt__list_events` (page until done; `get_session` gives the title and state) and returns what a deep pass returns: corrections in the user's or parent's words, reusable procedures, doc gotchas, repeated tool errors, each with a short quote, a holder (skill / doc / hook) and a drafted change. If `list_events` refuses an archived session, retry `mcp__ccd_session_mgmt__search_session_transcripts` with `include_archived: true`. If that fails too, count it as unreadable and name it.
4. **Merge.** Treat each finding as this session's own: the same escalation ladder, the same auto-apply rules and the same Recommendations block, tagged with the sub-session's title. A lesson for a repo the sub-session worked in goes to that repo's doc or skill, through its normal path.

**Sub-session line (always, next to the `Deep pass:` line).** Print exactly one line: `Sub-session sweep: <n> swept, <m> already wrapped, <k> unreadable (<names>)`, or `Sub-session sweep: none opened`, or `Sub-session sweep: not the native app`.

### Skill sweep (intent: closes nothing)

When Step 3 picks skill sweep, run Steps 1 to 4 in full, run Steps 5 and 6 only if the sweep changed files, skip Steps 7 and 8, and finish at Step 9. The sweep is the done wrap's learning capture without its closeout, for a window that stays open.

1. **Scan and deep pass.** Run the deep session scan and the deep pass exactly as in done mode. The deep pass is required: the user asked for the review by name, so the "trivial session" skip does not apply. Print the `Deep pass:` line. Then run the sub-session sweep and print the `Sub-session sweep:` line.
2. **Apply and recommend.** Auto-apply the doc and skill lessons (see "How to apply updates" and "Skill files: what auto-applies"), print the `Skill and doc updates applied:` line, and emit the Recommendations block (or "No skill/hook/plugin recommendations").
3. **Make the edits durable, and only that.** If the sweep changed files, run Steps 5 and 6 as pause does (commit and push the branch). The worktree and branch stay mounted. If it changed nothing, skip both steps.
4. **Close nothing.** Skip Step 7 (no worktree closeout, no merge, no task-tracker wrap comment) and Step 8 (the browser tabs stay open). Do not write a resume prompt, and do not print the archive line.
5. **Recommendations ship on the reply**, the way the done path does under "On approval". Shipping them still closes nothing.

Step 9 gives the sweep's closing message.

## Step 5: Detect Worktree State

Run:

```bash
GIT_DIR=$(git rev-parse --git-dir)
COMMON_DIR=$(git rev-parse --git-common-dir)
if [ "$GIT_DIR" != "$COMMON_DIR" ]; then
  IS_WORKTREE=1
  WORKTREE_PATH=$(git rev-parse --show-toplevel)
  MAIN_PATH=$(dirname "$COMMON_DIR")
  WT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
  WT_NAME=$(basename "$WORKTREE_PATH")
  echo "In worktree at $WORKTREE_PATH on branch $WT_BRANCH (main checkout: $MAIN_PATH)"
else
  IS_WORKTREE=0
  echo "Not in a linked worktree."
fi
```

Then check branch relationship:

```bash
git fetch origin --prune
# Resolve the default branch robustly - do NOT assume it is main. A single
# symbolic-ref can come back empty (origin/HEAD never set locally), and a
# hardcoded origin/main fallback is wrong on master/trunk repos, which sends the
# whole closeout at the wrong branch. Try symbolic-ref, then repair it with
# `remote set-head`, then probe the common names, and only then fall back.
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|^refs/remotes/||')
if [ -z "$DEFAULT_BRANCH" ]; then
  git remote set-head origin -a >/dev/null 2>&1
  DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|^refs/remotes/||')
fi
if [ -z "$DEFAULT_BRANCH" ]; then
  for b in main master trunk; do
    git rev-parse --verify "origin/$b" >/dev/null 2>&1 && { DEFAULT_BRANCH="origin/$b"; break; }
  done
fi
[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH="origin/main"
git status --short --branch
git rev-list --left-right --count "$DEFAULT_BRANCH"...HEAD
```

## Step 6: Clean Up Commits, Then Push The Branch

If the repo uses auto-commit hooks, squash session `wip` commits into one descriptive commit before pushing.

**Use `session-dsp` for the squash. Do not re-derive it here.** Follow its mode detection, the squash window, the attribution check (shared-branch mode only), and the drafted message. That check is what stops a wrap from sweeping another session's `wip` commits into your commit on a shared feature branch. A naive "soft-reset to the last non-wip commit" has no such guard.

Then run session-dsp's commit step WITHOUT its push. Reset and commit stay in ONE bash call (the wip hook can fire between turns), and the push comes from the unconditional block below:

```bash
git reset --soft "$LAST_NONWIP" && git commit -m "$(cat <<'EOF'
<drafted message>
EOF
)"
```

Then run the post-squash gate: `git diff --stat origin/main..HEAD` (use your default branch) lists only files this session touched.

**Commit message approval.** In worktree mode, the wrap request is the approval: show the drafted message in the wrap summary and commit. In shared-branch mode, show the draft and wait for an OK.

**Nothing to squash.** If there are no wip commits from this session, the squash stops on a mixed window, or the tree has no changes, say so and skip the commit work - but do NOT skip the push below.

**Always push the branch to origin - unconditional, every mode (pick up / pause / done).** Run this whether or not anything was squashed or committed, so the branch and every local commit are durable on the remote and a handoff is never machine-bound. A **pick up** relies on this invariant: a branch that is not on origin cannot be resumed on another machine.

```bash
# Push HEAD to origin no matter what happened above. A plain push also sets the
# upstream on a branch that has never been pushed.
git push -u origin HEAD
# ONLY if that push was rejected as non-fast-forward BECAUSE this wrap squashed commits
# that were already pushed, run this as a SEPARATE command. It refuses if the remote
# advanced, so it is safe. Any other rejection: stop and read it, do not force.
#   git push --force-with-lease
# Verify the branch is actually on origin at this exact commit before any handoff.
BR=$(git rev-parse --abbrev-ref HEAD)
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$BR" 2>/dev/null)" ]; then
  echo "BLOCKED: $BR not level with origin after push; resolve before handoff (an off-origin pick up is machine-bound)."
fi
```

## Step 7: Handle Worktree Closeout

If your team tracks work in a task tracker, post the wrap note there at this step in whatever way your team does it, before any worktree is removed. Treat it as fail-soft: a tracker error never blocks closeout.

### If Intent Is Pause

Leave the worktree and branch in place.

Provide:

- Worktree path.
- Branch name.
- Current dirty or committed state.
- Next command to resume.
- Remaining tasks.

If the user asks for a check or an alarm after the pause, set a durable timer (see "Dated follow-ups get a timer" in Step 9). Every dated follow-up the recap promises gets a timer in this same turn, with its id printed in the recap.

Example (a Markdown numbered list, not a fenced block; see "Line-per-item lists" in Step 9):

1. Paused on `wt/fix-auth-refresh` at `/path/to/project/.claude/worktrees/fix-auth-refresh`.
2. Resume with: `cd /path/to/project/.claude/worktrees/fix-auth-refresh`
3. Next: finish OAuth callback tests and rerun `npm test`.

#### Pause: merge decision (only if IS_WORKTREE=1)

Step 6 already squashed and pushed this checkpoint to the worktree branch, so the work is durable no matter what follows. The only question is whether this increment should ALSO land on the default branch now. Other sessions and parallel agents read the default branch, not your worktree branch, so documentation or a skill stranded on the branch is invisible to all of them until it merges.

**Rule:** merge to the default branch when the increment is self-contained and low-risk - documentation, memory, `CLAUDE.md`/`AGENTS.md`, or skills. Keep it branch-only when it touches code, config, or infra, because a partial build is incoherent and deploy-risky on the shared branch. Docs-class is the auto-yes; a partial build is the auto-no. **If ANY non-docs path is present, default to branch-only** (merge the docs later, when the build lands).

Classify the checkpoint's diff and recommend:

```bash
# What this checkpoint changed, relative to the default branch.
CHANGED=$(git -C "$WORKTREE_PATH" diff --name-only "${DEFAULT_BRANCH}...${WT_BRANCH}")
# "Safe-to-merge" class: docs, memory, CLAUDE/AGENTS, skills. Everything else = code/config.
NON_DOCS=$(printf '%s\n' "$CHANGED" | grep -vE '(\.md$|^docs/|^memory/|(^|/)CLAUDE\.md$|(^|/)AGENTS\.md$|^\.claude/)' | sed '/^$/d' || true)
echo "=== changed in this checkpoint ==="; printf '%s\n' "$CHANGED"
if [ -z "$CHANGED" ]; then
  echo "RECOMMEND: nothing to merge (no diff vs $DEFAULT_BRANCH)."
elif [ -z "$NON_DOCS" ]; then
  echo "RECOMMEND: merge to the default branch (docs-class only, low risk)."
else
  echo "RECOMMEND: branch-only (code/config present):"; printf '  %s\n' "$NON_DOCS"
fi
```

Present the file list and recommendation and **confirm before merging** (the default branch is shared; the merge is hard to unwind).

- **Branch-only** (recommended for code): nothing more to do - the work is already on `origin/$WT_BRANCH`. Go to Step 9; pause skips the browser-tab cleanup in Step 8.
- **Merge to the default branch** (recommended for docs-class, once confirmed): run the guards and integration from the **Merge path** below - Guards 0-2, the test gate, `pull --ff-only`, `merge`, `push`, ancestor verify - but **STOP before the destructive cleanup**. Do NOT run `git worktree remove`, `git branch -d`, or `git push origin --delete`. Then fast-forward the worktree branch so continued work stays a clean diff:

```bash
BASE_BRANCH=${DEFAULT_BRANCH#origin/}
# Bring the worktree branch back up to the just-merged default branch so the next
# checkpoint is a clean diff.
git -C "$WORKTREE_PATH" merge --ff-only "origin/$BASE_BRANCH" \
  || echo "note: worktree branch diverged from origin/$BASE_BRANCH; ff-realign skipped - resolve manually before continuing."
git -C "$WORKTREE_PATH" push || true   # keep origin/$WT_BRANCH in sync if the realign moved it
```

After a pause-merge the worktree is still mounted, still on `$WT_BRANCH`, now level with the default branch. Keep working in the same window.

### If Intent Is Pick Up

Also non-destructive: leave the worktree and branch mounted exactly as they are. The only difference from pause is the handoff - because the window is closing (or about to be compacted), Step 9 emits a full, copyable resume prompt instead of a short recap. Do not clean up, merge, or delete the worktree or its branch here. Shipping approved recommendations (below) is separate from the worktree.

**Branch must be on origin before you hand off.** Step 6 already pushed it unconditionally. If Step 6's verify printed `BLOCKED`, fix that now - resolve the push and re-verify `HEAD == origin/<branch>`. Never emit a pick up handoff for a branch that is not on remote: the resume may run on a different machine, and an off-origin branch cannot be pulled there.

**Recommendations ship first, the pickup prompt comes last.** The resume prompt must describe the state after this window stops working, so it is written after any approved recommendation lands.

- **No recommendations** (Step 4 said "No skill/hook/plugin recommendations"): emit the Step 9 prompt in this message.
- **Recommendations pending:** present the Recommendations block and end your turn. Do NOT emit the resume prompt in this message. Say that the prompt follows once every item is dispositioned. In pick up mode, "defer" means carry the item forward: it becomes a next step in the resume prompt.
- **Context full** (the user said the window is filling up, Step 3): do not wait for a reply. The window can end before it comes, and then no prompt exists. Defer every recommendation (each becomes a next step), save and emit the Step 9 prompt in this message, and show the Recommendations block under it. If the user then approves an item, ship it as the next bullet says and emit the prompt again (see "After the handoff" below).
- **On the reply:** ship each approved skill through your normal PR route for that skill, and state the next step for an approved hook or plugin rec, as in the done path. A rec that is a build (code that ships and needs review) is not built in this window: carry it forward. If a ship fails (red check, merge refused), report it and carry that item forward with its PR link. Then emit the Step 9 prompt, with the merged PR links and every carried-forward item in it.

**After the handoff, this window does not write to the handed-off worktree or branch.** The next session owns them. Work this window still does (a recommendation, a follow-up the user asks for) goes in a NEW worktree from `origin/<default>` in each repo it touches, or in a fresh clone. Never commit it on the handed-off branch. If that work changes what the resume prompt says (it merges an item the prompt lists as open, or adds a step), emit the full prompt again at the end and say it replaces the earlier one. Otherwise both sessions end up writing to one worktree.

**Session-bound timers and machine-only state.** A timer or scheduled message this session set fires into THIS window, not the next session. List every one in the resume prompt's `In flight` line with its id, fire time, what its message tells the session to do, and which window owns that job. A timer whose job moves to the next session should be deleted before the handoff, but the call may be refused (an unattended session often cannot delete scheduled tasks). Do not retry or work around a refusal: keep that job with this window, or name the id for the user to turn off, and say which in the prompt. When the work continues on another machine or user account, also copy any private, non-git state the next session needs (data files, run scripts, audit logs) to storage both can reach, after a secret scan and a file-count check, and name that location in the prompt instead of a home-folder path the other machine cannot read.

**Stop background tasks tied to the handed-off branch or PR before the handoff, and never start a new one on it.** A merge loop, a CI watcher or a deploy watcher acts on the work the next session now owns. Stop each one (`TaskStop`) before you emit the Step 9 prompt, say in the prompt that it is stopped, and make restarting it the next session's job. If the next session has already started one, leave it alone. Two sessions running merge loops on one PR is a failure mode.

**Hand-over while the old window is still working.** Sometimes the user opens the new session while this window still runs live work (a production run, builders, a merge loop), or the window keeps working after the pick-up prompt. Then exactly one session must own the work at any moment:

1. **The new session asks first.** Before it acts, it messages the old session once, naming the user's hand-over words and time, and asks the old window to: stop everything that can act or write (sub-agents, merge loops, watchers, background shells; read-only jobs whose output it needs may keep running, named); not flip, deploy, merge, commit, push or write to any live system again; and reply with (a) `STOPPED`, (b) everything it did after a named time, (c) unfinished work with its branch, worktree and state, (d) the exact command lines it planned and any file paths and counts the handoff file does not hold, and (e) whether the shared worktree has uncommitted changes.
2. **The old window complies, then goes idle.** Stopping is the safe direction, so it does not wait for the user to confirm the hand-over. It stops each task, checks the worktree and its own processes, replies with (a)-(e) in one message, and ends its turn. It does nothing more unless the new session or the user messages it.
3. **The new session acts only after `STOPPED`.** No reply means the old window may still be acting: ask the user, do not proceed.

The old window may still do work the user asks for in it, outside the handed-off scope (for example a done wrap's doc and skill updates), in a NEW worktree from `origin/<default>`, never on the handed-off branch.

### If Intent Is Done

**Gate - present the applied-updates summary before any destructive op.** This binds the **done** path only (pick up and pause never destroy the worktree). Docs auto-apply (Step 4), so closeout no longer waits for approval, but before running ANY destructive worktree op (`git worktree remove`, `git branch -d`/`-D`, or `git push origin --delete`):

- The **"Applied doc updates" summary, with commit SHAs and undo commands, must appear in a message BEFORE the destructive op** (same turn is fine). The transcript is keyed to the worktree path, so the user must be able to see what was written from a live window before it is removed.
- **Any carve-out item still requiring approval** (deletion or retirement, rewriting human-authored content, sensitive material - Step 4 item 6) blocks closeout: present it, end your turn, and wait. Never destroy the worktree with a carve-out proposal unanswered.
- The **Recommendations block** (skills / hooks / plugins, from Step 4) must appear in that SAME consolidated message. This is the single approval point: the user gives a disposition per numbered item (approve / decline / defer), or replies "go" (or "yes to all"), which gives every item its recommended disposition. When any recommendation is pending, it **blocks the destructive closeout until every item is dispositioned** - present them, end your turn, and wait; do not remove the worktree with a recommendation unanswered (its evidence lives in the session being closed). Nothing ships without an approve for that item, given directly or through "go" on an item recommended approve. "Defer" records it for later and ships nothing.
- The wrap's FIRST message, when it stops here to wait for a reply (a carve-out, a recommendation, or a closeout confirm), is **leg 1** of the wrap. Put the reply prompt above its closing line, and end it with the leg-1 closing line from Step 9.
- If Step 4 found nothing to update ("No doc updates needed") and no recommendations, this gate is already satisfied - proceed.

**On approval, carry through in order - no extra stops** (the consolidated gate is the one stop):

1. Apply any approved doc carve-outs, then **commit and push each affected repo and show the SHAs / undo commands**. This runs BEFORE the integration guards below so the tree is clean (the merge and discard guards reject a dirty worktree).
2. **Filter the ship queue first:** drop a recommendation only when the worktree branch being merged this wrap already lands that exact content at the same destination repo and skill path the ship targets. A merge into some other repo does not publish there, so those recs still ship.
3. **Ship each approved SKILL** through the PR route for the repo the skill lives in, end to end: open the PR, wait for checks, merge it under that repo's rules. If you own the repo and the change is a non-deploy skill or doc, do not stop at an opened PR once the item was approved.
4. **Approved HOOK / PLUGIN recs** are surfaced with their real next step (edit the hooks file or plugin manifest, then the normal build), NOT auto-shipped: a hook runs every session.
5. On a ship failure (checks red, a branch rule refuses, the PR cannot merge): STOP, report, keep the worktree - shipping runs before any destructive op precisely so a failure never strands work in a removed worktree. End that report with the Step 9 `Not ready to archive: ...` closing line.

Only then continue to the worktree closeout.

First, **close every worktree THIS conversation touched - merge or discard - and leave every other worktree alone.** The set to close is scoped to THIS conversation, NOT the whole repo.

- **"Touched" =** a worktree this session created, resumed into, or committed / edited in. You know this set from your own actions this session - normally just the one you are in now, plus any you entered earlier.
- **Other worktrees in the repo are NOT your concern.** A repo almost always has other worktrees open because OTHER sessions are working in them - that is the normal state, not a mess `done` must clear. Do NOT merge, discard, remove, or even flag them.
- **A worktree you handed off belongs to the next session.** Before you merge, discard or remove a worktree this conversation touched, check that no other session works in it now. Signs: its branch has commits you did not make (`git log origin/<branch>`), its tip moved after your pick-up handoff, or a session you handed it to has started. If another session owns it, do not merge, discard or remove it, and do not delete its branch. Name it in the wrap with its owner; that is the reason it cannot close here.

`git worktree list` shows what physically exists, for orientation ONLY - it does not define the set to close. Never act on a worktree just because the list prints it.

Now close each worktree THIS conversation touched. Classify it against the default branch, then choose **merge** or **discard** (repeat per worktree). **Done is not complete while a worktree this conversation touched is still open** - merge or discard each, or name any that cannot close this session with the reason.

```bash
DIRTY=$(git -C "$WORKTREE_PATH" status --porcelain | wc -l | tr -d ' ')
AHEAD=$(git -C "$WORKTREE_PATH" rev-list --count "${DEFAULT_BRANCH}..${WT_BRANCH}" 2>/dev/null || echo "?")
BEHIND=$(git -C "$WORKTREE_PATH" rev-list --count "${WT_BRANCH}..${DEFAULT_BRANCH}" 2>/dev/null || echo "?")
echo "dirty=$DIRTY ahead=$AHEAD behind=$BEHIND"
```

**Before any removal, look for git-ignored files that exist nowhere else.** Merge and discard both end in `git worktree remove`, and that deletes git-ignored files too. Run `git -C "$WORKTREE_PATH" status --ignored --short` and read each `!!` line. If a git-ignored folder holds files with no other copy (case files, local data, generated outputs that are the only copy), do NOT remove the worktree until a durable copy is verified: for example a storage mirror, checked by listing it and comparing size and hash with the local files. If you cannot verify a copy, keep the worktree, name the folder in the wrap, and end with the Step 9 `Not ready to archive: ...` closing line. Build output and caches (`node_modules`, `__pycache__`, `.venv`) are not at risk: ignore them.

Present the state and choose:

- `dirty=0 ahead=0 behind=0` - **discard** (no work happened).
- `dirty=0 ahead>0 behind=0` - **merge** (clean fast-forward).
- `dirty=0 ahead>0 behind>0` - default branch moved; **merge** with a merge commit.
- `dirty>0` - Step 6 should have committed everything; find out why before proceeding.

#### Merge path

Operate from the main checkout, not the worktree. Every step has a safety rail - if any check fails, **stop immediately and report**. Do not proceed to destructive cleanup with broken state. The gate sequence: Guard 0 (hard clean-tree + real branch), Guards 1-2 (checkout + branch sync), Gate 3 (test before integrating), the atomic merge, then Gate 4 (merged-result test) before push, and only then cleanup.

```bash
BASE_BRANCH=${DEFAULT_BRANCH#origin/}   # "main", "master", whatever origin/HEAD points at
cd "$MAIN_PATH"

# Guard 0 (HARD clean-tree + real branch): never integrate a dirty tree or a
# detached HEAD. Step 6 should have committed everything, so either state means
# work would be dropped or misattributed by the merge. Stop and resolve first.
# Fail CLOSED: verify the path is a real work tree first. A failed `git status`
# would pipe empty to `wc` (count 0) and falsely read as clean.
git -C "$WORKTREE_PATH" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "BLOCKED: '$WORKTREE_PATH' is not a valid git work tree; cannot verify clean state."; return 1 2>/dev/null || exit 1; }
WT_DIRTY=$(git -C "$WORKTREE_PATH" status --porcelain | wc -l | tr -d ' ')
if [ "$WT_DIRTY" != "0" ]; then
  echo "BLOCKED: worktree has $WT_DIRTY uncommitted file(s). Commit or discard before integrating - never merge a dirty tree."
  return 1 2>/dev/null || exit 1
fi
if ! git -C "$WORKTREE_PATH" symbolic-ref -q HEAD >/dev/null; then
  echo "BLOCKED: worktree HEAD is DETACHED (not on a branch). 'git switch -c <branch>' before integrating - a detached HEAD has no branch to merge, and cleanup would strand the commits."
  return 1 2>/dev/null || exit 1
fi

# Guard 1: primary checkout safe to mutate?
# Switching its branch or polluting it with the merge would silently break another
# session working in the same checkout. If it is mid-work, refuse - let the user resolve.
PRIMARY_BRANCH=$(git rev-parse --abbrev-ref HEAD)
PRIMARY_DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$PRIMARY_BRANCH" != "$BASE_BRANCH" ] || [ "$PRIMARY_DIRTY" != "0" ]; then
  echo "BLOCKED: primary checkout is on '$PRIMARY_BRANCH' with $PRIMARY_DIRTY uncommitted file(s)."
  echo "Switch primary to '$BASE_BRANCH' (clean) before closeout, or close out manually."
  return 1 2>/dev/null || exit 1
fi

# Guard 2: worktree branch in sync with origin?
# Another session (or an auto-commit hook) may have pushed extra commits to the
# branch. If we merge only the local tip and then delete the remote, we lose those
# remote-only commits.
git fetch --quiet origin "$BASE_BRANCH" "$WT_BRANCH" || { echo "BLOCKED: fetch failed."; return 1 2>/dev/null || exit 1; }
LOCAL_TIP=$(git rev-parse "$WT_BRANCH")
REMOTE_TIP=$(git rev-parse "origin/$WT_BRANCH" 2>/dev/null || echo "")
if [ -n "$REMOTE_TIP" ] && [ "$LOCAL_TIP" != "$REMOTE_TIP" ]; then
  echo "BLOCKED: $WT_BRANCH local ($LOCAL_TIP) diverged from origin/$WT_BRANCH ($REMOTE_TIP)."
  echo "Resolve manually before closeout - otherwise remote-only commits are lost when the branch is deleted."
  return 1 2>/dev/null || exit 1
fi

# Gate 3 (test before integrating) - EXECUTABLE, not a note. A branch never merges to
# the default branch RED. Set TEST_GATE to the repo's OWN test command (the same gate
# its build process runs, e.g. `npm test && npm run build`, or `pytest`), discovered from
# the repo and its CLAUDE.md - or to the literal DOCS_ONLY to waive it for a genuinely
# test-less repo. Unset = you have not decided = BLOCK (never silently skip the gate).
if [ -z "${TEST_GATE:-}" ]; then
  echo "BLOCKED: TEST_GATE not set. Set it to the repo's test command, or DOCS_ONLY to waive (docs-only repo)."; return 1 2>/dev/null || exit 1
fi
if [ "$TEST_GATE" != "DOCS_ONLY" ]; then
  bash -c "$TEST_GATE" || { echo "BLOCKED: $WT_BRANCH is RED - not integrating a failing branch."; return 1 2>/dev/null || exit 1; }
fi

# Atomic integration - any failure aborts before destructive ops.
git pull --ff-only || { echo "BLOCKED: pull --ff-only failed; '$BASE_BRANCH' moved unexpectedly."; return 1 2>/dev/null || exit 1; }
if git merge --ff-only "$WT_BRANCH"; then :; \
elif git merge --no-ff "$WT_BRANCH" -m "merge: $WT_BRANCH"; then :; \
else echo "BLOCKED: merge of $WT_BRANCH into $BASE_BRANCH failed."; return 1 2>/dev/null || exit 1; fi

# Gate 4 (merged-result test) - EXECUTABLE. The merge can break the default branch
# even when both sides were green (a semantic conflict git can't see). Re-run the
# same gate on the merged result; RED -> undo the merge and STOP (never push red).
if [ -n "${TEST_GATE:-}" ] && [ "$TEST_GATE" != "DOCS_ONLY" ]; then
  bash -c "$TEST_GATE" || { echo "BLOCKED: merged result is RED - undoing the merge."; git reset --hard 'HEAD@{1}'; return 1 2>/dev/null || exit 1; }
fi
git push || { echo "BLOCKED: push failed (origin advanced? auth? branch-protected?). Worktree preserved; resolve and re-run."; return 1 2>/dev/null || exit 1; }

# Post-push verify: the worktree tip is genuinely on origin/$BASE_BRANCH now. If not, something raced.
if ! git merge-base --is-ancestor "$LOCAL_TIP" "origin/$BASE_BRANCH"; then
  echo "BLOCKED: $WT_BRANCH tip ($LOCAL_TIP) is NOT an ancestor of origin/$BASE_BRANCH after push. Worktree preserved - investigate."
  return 1 2>/dev/null || exit 1
fi

# Only now is destruction safe.
git worktree remove "$WORKTREE_PATH"
git branch -d "$WT_BRANCH"
git push origin --delete "$WT_BRANCH" || echo "warning: remote $WT_BRANCH delete failed (auth/permission/already-gone) - local cleanup already done."
```

If your task tracker has a link to this branch, update it to point at the merged commit now that the branch is deleted.

#### Merge path - PR-protected default branch (integrate via a merged PR)

When the default branch is branch-protected (a rule such as "Changes must be made through a pull request" plus required status checks), the direct `git push` above is REJECTED (`remote: error: GH013: Repository rule violations found`), so the integration is a **merged PR**, not a push. Treat this as a first-class case: more repos enable it over time. This is still the done intent: merging the PR IS the integration, so you do not leave it open (leaving a PR open for someone else to merge is a different, hand-off intent).

Detect it by the push rejection (the reliable signal), or check ahead with `gh api "repos/{owner}/{repo}/rulesets" >/dev/null 2>&1`. Guard 2 (worktree branch == `origin/$WT_BRANCH`) from the Merge path still applies; Guard 1 is moot here - the merge happens server-side, not via a local checkout mutation.

```bash
BASE_BRANCH=${DEFAULT_BRANCH#origin/}
# The branch is already pushed (Step 6). Bring it up to base first so the PR is a
# clean, current diff, then open and merge the PR.
git -C "$WORKTREE_PATH" fetch origin "$BASE_BRANCH" -q
git -C "$WORKTREE_PATH" merge --ff-only "origin/$BASE_BRANCH" && git -C "$WORKTREE_PATH" push
gh pr create --base "$BASE_BRANCH" --head "$WT_BRANCH" \
  --title "<type>(<scope>): <summary>" --body "<what + why>"

# The merge gate: use the gate-merge.sh script bundled with the dev-deploy-safely skill
# (<plugin root>/skills/dev-deploy-safely/scripts/gate-merge.sh; it runs pr-checks-green.sh from
# the same folder). It waits up to 30 minutes for every check on the PR (run it in the
# background), merges ONLY the commit it gated (squash, pinned to that commit's SHA), and
# confirms the PR shows MERGED. It prints "MERGED <n>" on success and "STOP: <why>" otherwise.
# Never gate on the exit code of `gh pr checks` (some gh versions exit 0 on a CANCELLED
# check) and never hand-roll the check-rollup read.
GATE_MERGE=<plugin root>/skills/dev-deploy-safely/scripts/gate-merge.sh
gh pr view <n> --json mergeable,mergeStateStatus,reviewDecision   # look first
# --allow-none passes a PR with no checks ONLY when the repo has no CI. The script exits 0
# only when the PR shows MERGED, so the delete below runs only after a confirmed merge.
bash "$GATE_MERGE" <n> --allow-none && git push origin --delete "$WT_BRANCH"
# If the merge is refused because a review is required (reviewDecision=REVIEW_REQUIRED:
# a PR author cannot approve their OWN PR) AND you hold an authorised bypass and the owner
# has said to use it: re-run the same script with --admin. Otherwise stop and get a reviewer.
```

The script is the only merge path for this step: do not rebuild the check read or call `gh pr merge` by hand. If the bundled script is not available, stop and report that instead of merging on a hand-read of the checks. The remote-branch delete in the block above is safe only because the script confirmed `MERGED` first.

Two footguns in this path, both easy to hit:

- **`mergeStateStatus: BEHIND`** - rules usually require the branch up to date with base. The merge is refused until the branch is merged up to base, and that update **RESTARTS the required checks**. `gate-merge.sh` handles this itself (it updates the branch with a merge, never a force-push, then gates again, a few times at most); if it still stops with "still behind", merge `origin/$BASE_BRANCH` into the branch by hand, push, and run the script again. Confirm the merge actually landed (`gh pr view <n> --json state` = `MERGED`) before any cleanup. A chained `merge && cleanup` one-liner built from a hand-rolled merge will happily clean up around a still-refused merge.
- **Never delete the remote branch while the PR is OPEN.** Deleting the head branch auto-closes the PR and strands the commits. The `state=MERGED` check is the gate on the delete, not a formality.

Also, do NOT pass `--delete-branch` to `gh pr merge` from inside a worktree: gh then tries to check out the base branch locally and fails (`fatal: '<base>' is already used by worktree at ...`). The server-side merge still succeeds, but the branch is left undeleted - so merge, THEN delete the remote branch as a separate pure-remote op once `state=MERGED`.

Then the LOCAL worktree cleanup (the PR path above deleted only the REMOTE branch). **If this session RESUMED into the worktree (a pick up) rather than creating it with `EnterWorktree` this session, `ExitWorktree(action: remove)` refuses** (not the owner, or a liveness lock is held), and you cannot `git worktree remove` a checkout the session is standing in. The working sequence: call **`ExitWorktree(action: keep)` first** - it returns the session to the main checkout and releases the resume lock - THEN from the main checkout run `git worktree remove "$WORKTREE_PATH"` and `git branch -D "$WT_BRANCH"` (the local branch reads as unmerged after a PR squash-merge, so `-D`; its content is on the base branch and the remote branch is already gone). Only fall back to a manual post-session command if `git worktree remove` still refuses and names another live session as the lock owner.

#### Discard path

```bash
BASE_BRANCH=${DEFAULT_BRANCH#origin/}
cd "$MAIN_PATH"

# Guard 1: primary checkout sanity. We do not mutate it on discard, but a non-clean
# primary suggests another session is mid-work in the same repo - pause to confirm
# before destroying anything.
PRIMARY_BRANCH=$(git rev-parse --abbrev-ref HEAD)
PRIMARY_DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$PRIMARY_BRANCH" != "$BASE_BRANCH" ] || [ "$PRIMARY_DIRTY" != "0" ]; then
  echo "WARNING: primary checkout is on '$PRIMARY_BRANCH' with $PRIMARY_DIRTY uncommitted file(s). Confirm explicitly before discarding the worktree."
  return 1 2>/dev/null || exit 1
fi

# Guard 2: worktree itself clean? --force will SILENTLY delete uncommitted work.
WT_DIRTY=$(git -C "$WORKTREE_PATH" status --porcelain | wc -l | tr -d ' ')
if [ "$WT_DIRTY" != "0" ]; then
  echo "BLOCKED: worktree at $WORKTREE_PATH has $WT_DIRTY uncommitted file(s)."
  echo "Discard with --force would silently delete this work. Commit/stash first, or get explicit OK to throw it away."
  return 1 2>/dev/null || exit 1
fi

# Guards passed: no uncommitted work at risk, so a plain (non --force) remove is safe.
git worktree remove "$WORKTREE_PATH"
git branch -D "$WT_BRANCH"
git push origin --delete "$WT_BRANCH" || echo "warning: remote $WT_BRANCH delete failed - local cleanup already done."
```

After closeout, verify with `git worktree list` that every worktree THIS conversation touched is gone (merged or discarded) and its branch deleted. Other worktrees still listed belong to other sessions and are EXPECTED - leave them; they are not a sign of an unfinished wrap. A worktree this conversation touched still listed, with no reason recorded, means `done` is not finished. Stop immediately if any command above fails - do not continue cleanup after a failed merge or push. End that stop report with the Step 9 `Not ready to archive: ...` closing line.

## Step 8: Close This Session's Browser Tabs (pick up / done)

Run this only when the window is closing (**pick up** or **done**). **Skip for pause** - work continues and the session may still need its tabs.

When this session drove the Claude-in-Chrome extension, it left a tab group. If the window closes without closing those tabs, the group is orphaned: a later session cannot reach it (the extension's tab tools act only on the *current* session's group), and it lingers as an empty-looking leftover in Chrome. Closing the tabs now lets Chrome auto-remove the group.

**Applies only to sessions that used the Claude-in-Chrome extension.** If this session never drove that extension, or `ToolSearch` finds no `mcp__claude-in-chrome__tabs_*` tools, SKIP this step cleanly - it is a no-op, not an error.

1. If the extension tab tools are not loaded, load them: `ToolSearch "select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_close_mcp"`. If that returns no such tools, skip this step.
2. Read this session's group **without creating one**: call `tabs_context_mcp` with no arguments (do NOT pass `createIfEmpty`). "No tab group exists for this session" means nothing to clean - stop here.
3. For each tab id returned, call `tabs_close_mcp`. Closing the last tab auto-removes the group.
4. Report which tabs closed (title / url) in one line.

Guardrails: never pass `createIfEmpty` here (that would spawn a fresh group, the opposite of cleanup); if the user asked to keep a tab open, skip that tab; this cleans only the **current** session's group.

## Step 9: Final Handoff

Branch on intent - the four modes end differently.

**Output style.** Write each mode's handoff in the reader's active output style if one is set, or answer-first with short plain sentences if not. Keep every required field and block below; the style shapes wording only. The done mode's last line stays its closing line (below), with nothing after it. The closing lines are fixed strings: do not restyle or reword them.

**Line-per-item lists go in a Markdown numbered list.** Chat Markdown joins plain lines that have no blank line between them into one paragraph. So any list the reader asked for as one item per line goes in a Markdown numbered list (`1.`, `2.`), one item per entry. Do not put such a list in a fenced `text` block: the reader sees raw, unformatted text. Keep fenced blocks for text the reader will copy, such as the pick-up resume prompt.

**Dated follow-ups get a timer in the same turn (every intent).** Before you print the handoff, list each dated action the wrap promises: a checkout or worktree to remove after a lock date, a check on a date, a re-run after a deadline. Each one gets a durable timer in this same turn (a scheduled task, a calendar reminder, or whatever scheduler you have), and the handoff prints the timer id beside it (`timer <id>`). A dated action with no timer is printed as `NO TIMER: <why>`; never leave it as a date in prose. Write the timer message so the session that receives it can act alone: what to check, the exact command, and what to do on each result. Writing the date into the resume prompt or recap is not a timer.

### done

A readable close-out; there is nothing to resume. State the outcome, the branch/worktree disposition (merged and removed, or discarded), and deploy state if relevant. The body always carries the `Deep pass: ...` line, the `Sub-session sweep: ...` line and the `Skill and doc updates applied: ...` line from Step 4, next to the Recommendations block or the "No skill/hook/plugin recommendations" sentence.

**Ordering is mandatory: the closing line is the LAST line of the message.** Nothing goes after it - not open threads, not follow-ups, not a sign-off. A reader scans to the bottom of a wrap specifically to confirm the session is closed out and the tree is clean; when that line sits mid-message it cannot be found, which defeats the purpose of the wrap. Any warm close or "open threads" section belongs in the body, above the closing line. Before sending, re-read your own final line: if it is anything other than the closing line, move the closing line to the bottom.

**Pick the closing line by leg.** A done wrap often runs in two legs. Leg 1 applies the docs and presents the Recommendations block (Step 7 gate). Leg 2 carries out the approved items after the user replies "go". The two legs end with different lines, so the user can tell from the last line alone whether this conversation is finished:

- **Leg 1** (the wrap's FIRST message, when it waits for a reply: a recommendation, a carve-out, or a closeout confirm): end with `Next session starts fresh.` The work is pushed and the docs are captured, but this conversation still has work to do. Only this message uses this line. Every later message in the same wrap ends with one of the two lines below.
- **Final message, fully complete:** end with `You can archive this conversation now.` Write it only when ALL of these hold:
  - every carve-out and recommendation is dispositioned and carried through (a declined or deferred item counts as carried through; an approved hook or plugin rec counts once its next step is in the body);
  - every approved ship PR, and the worktree's own integration PR, shows `MERGED` (an unmerged one blocks, even when someone else must approve it). The one exception: the integration PR of a worktree that now belongs to another session the body names as its owner;
  - every worktree this conversation touched is closed, or now belongs to another session that the body names as its owner;
  - nothing came up that needs the user to act or decide in this conversation.

  Follow-ups that live outside this conversation (logged in your task tracker or a doc, tasks for other people) and fail-soft warnings do not block it; list them in the body. A one-leg done wrap (nothing to approve) is a final message too, so it ends with this line when the same conditions hold.
- **Final message, not complete:** never write the archive line. Name each open item in the body, then end with `Not ready to archive: <the open item, in a few words>.` Examples: a ship failed and the worktree was kept, a PR is open but not merged, a check is red, or a new question came up that needs the user.

### pause

A short status recap, NOT a resume prompt - the window stays open and context is live. Say what was pushed, what docs were captured, and what you are waiting on, then the exact next action for when you resume.

### skill sweep

A short report, NOT a wrap. Print the `Deep pass:` line, the `Sub-session sweep:` line, the `Skill and doc updates applied:` line and the Recommendations block (or the "No skill/hook/plugin recommendations" sentence), then one line on branch state (pushed, or nothing changed). End with exactly `Skill sweep done. This window stays open.` Never print the archive line or `Next session starts fresh.`, and never write a resume prompt.

### pick up

**Precondition:** the branch is on origin, including the brief commit when one was made ("Save the brief" below): it is pushed and `HEAD == origin/<branch>` passed again after that commit. Do not emit the block before then; the resume may run on another machine that can only pull what is on remote. A save that was skipped or refused does not block the block (see "Save the brief"). Also, every recommendation is dispositioned and the approved ones are shipped (Step 7 "If Intent Is Pick Up"; a context-full pick up defers them all).

Put one line in the prose above the block: start the new session only after this window stops working, and treat this window as closed from then on. The prose above the block also carries the `Deep pass: ...` and `Sub-session sweep: ...` lines from Step 4.

Emit ONE copyable, self-sufficient resume prompt as a single fenced block. It must let a fresh (or freshly-compacted) session continue without the prior context, so include: project, worktree path + branch, deployed/branch state, known blockers (who owes what, since when), the exact next steps, and any reference doc. Even when you expect to resume right after compacting, write it so it stands alone if the window is gone.

Give every worktree the prompt names (to resume OR to close) as an absolute path: on a machine with several users, each has its own checkout and cannot read the others, so a relative `.claude/worktrees/<name>` can point the next session at the wrong checkout. The absolute path can still be missing where the session resumes (a pickup written on one machine and resumed on another names a path that does not exist there). So add one fallback line to the worktree-mode prompt: if that path is missing on this machine, run `git fetch origin <branch>`, then `git worktree add -b <branch> <repo>/.claude/worktrees/<name> origin/<branch>` from the repo's main checkout (if a local `<branch>` already exists, check it is level with `origin/<branch>` and add it without `-b`), then `EnterWorktree(path: ...)`. The branch is on origin (Step 6), so the worktree can always be rebuilt from it.

**Machine-bound next steps name the machine.** The fallback above rebuilds a branch on any machine, but it cannot move data that lives on one machine only. When a next step needs one machine (its local files, a desktop-app tool, or config only that machine holds), name the machine in the prompt's first line. Directly under that line, add `If this is not <machine>, stop and tell the user before any step.`, with the machine's name in place of `<machine>`.

**What the handover must also carry.** The next session gets only this block and the docs. Anything that lives only in this window is lost, so fill each of these lines, in the template's order (write "none" rather than dropping a line):

- **Read first:** the saved brief's path, the branch it is on, and the commit that holds it (see "Save the brief" below), or `none` and why, when no brief was saved.
- **Not live yet:** work fixed in source but not yet live, per layer. Examples: code on a branch vs the deployed service, a config file vs the live system, a script vs the rendered output. "Fixed" is false if only the source changed.
- **Blocked on:** who owes what, and since when, so the next session does not chase it again.
- **Do NOT:** decisions the next session must not helpfully undo.
- **Corrected:** anything this session believed that turned out wrong, and the truth. Wrong beliefs are the most expensive thing to hand off, because they get acted on.
- **In flight:** every subagent (what it owned, finished or failed, where its findings are saved), every background job (tell the next session to check for its output, not the job, and say if a rerun is safe), every timer this session set (see "Session-bound timers"), and every outward-facing item left mid-flight (unsent draft, unanswered mention, pending approval) with its ID. In the native Claude app, also every sub-session this session opened and has not swept (id and title; see "Sub-session sweep").
- **Subagent assignments:** a subagent that is still running or unfinished does not carry over to the next session. For each one, write its assignment so the next session can dispatch it again: the goal, the scope, the files or items it owns, the model, and what it already finished. The next session checks for its output first and re-dispatches only what is missing. Keep long assignments in the saved brief and point to them.
- **Verify:** the live values the next session checks before it acts: PR head SHA and state, task status, deploy revision, the last reply in a thread you wait on. The line itself tells the next session to report any drift before acting, because that session may not have this skill loaded.

Cheap handovers are banked earlier. A read-only subagent cannot write files, and the harness can refuse a subagent's report file. So the main session saves each report when it arrives, in a folder beside the saved brief, named after it without `.md` (for `docs/handoffs/2026-10-20-x.md`, the folder `docs/handoffs/2026-10-20-x/`). Then the roster is one line pointing at that folder, and the findings survive if the window ends mid-wrap. Never commit customer data, personal data or a secret: keep such a report outside the repo (for example the session scratchpad), and say in `In flight` that it was not carried.

**Read-back test before saving.** Re-read the block as a stranger: could you act on it without asking one question it could have answered? Rewrite any line that assumes something only this window knows. Then name, outside the block, anything that was NOT captured, so "safe to close" is true when you say it.

**Save the brief, then print it.** A prompt that exists only in chat is lost if the user closes the window before copying it. After the read-back test, write the full brief (the block plus any long subagent assignments) to the first of these that exists: a hand-off doc already built for this work; the handoff doc the repo's start-up instructions name; this work's runbook or plan; or a new `docs/handoffs/YYYY-MM-DD-<branch-slug>.md`. Do not pick a shared file the repo does not name: two branches that both change it conflict when they merge. Commit it in one commit with any reports saved during the wrap, push, and re-run the Step 6 verify (`HEAD == origin/<branch>`). The saved copy names its branch only, since a file cannot hold the SHA of its own commit. The printed block's `Read first` line names the branch AND that commit's short SHA, not only the path: the saved brief can sit on a branch that is not merged yet, and a resume that reads the default branch then starts from an older entry.

Never commit the brief on the default branch. In single mode on the default branch, skip the save, and print the block with `Read first: none (on the default branch, nothing saved)`. If the push of the brief commit is refused (a protected branch, a rule), print the block anyway with `Read first: none (save refused: <the error>)`, and say above the block that the brief exists only in this message. With no saved brief, the block must hold what the brief would have held: write long subagent assignments in full, mark each report path `not carried (local only)`, and run the read-back test again. A failed save never withholds the prompt.

Give a one-line **next-session model suggestion** in the wrap PROSE (above the fenced block), graded against the *remaining* work (the forward-looking companion to the Step 2 model-fit check): name the tier and reasoning effort you would start on and why. **Do NOT put it inside the copyable resume prompt** - the block is fed verbatim to the next session, and a model line there would instruct that agent, whereas the model choice is the user's to make.

**Step 1 of "Next steps" is always the same: bring the branch up to date with main.** Between this handoff and the resume, `main` may have moved. So the resume session's first step updates the worktree branch from the latest `origin/main` before it touches the work - this keeps the branch current and the eventual merge clean. Keep this as the fixed step 1 in both blocks below, ahead of the work-specific steps. (With a GO block it is step 2: see the GO rule below.)

When the branch is on origin and shared (another session or an open PR reads it) or force-push is not allowed, step 1 is a merge: `git fetch origin`, then `git merge origin/main`. On a conflict, run `git merge --abort` and flag it. A merge needs no force-push. The blocks below use this wording.

Keep the rebase wording only for a private, unshared branch. Then write step 1 as: `git fetch origin`, then `git rebase origin/main`. "If possible" means a clean rebase ONLY: on conflict the step runs `git rebase --abort`, surfaces the conflict, and does NOT force. The next wrap's Step 6 push uses `--force-with-lease`, so the rewritten history pushes without clobbering anyone.

**Exception: never rebase a branch that a deploy clone tracks.** When a server or VM checkout deploys this branch by fast-forward (for example `git fetch` then `git merge --ff-only`), a rebase rewrites history the clone cannot fast-forward to, and the next deploy fails. For such a branch, step 1 instead merges `origin/main` into the branch (no rebase, no force) when main has moved, and is skipped when the branch is 0 behind. Write that version of step 1 in the block, and say why in the handoff prose.

**Already-merged branch: restart it without a force-push.** When the branch's work is already squash-merged to main, step 1 restarts the branch from main instead of rebasing (`git checkout -B <branch> origin/main`). The old tip is still on `origin/<branch>`, so a plain push of the restarted branch is refused as non-fast-forward. Write step 1 to handle it: first confirm the old tip's content is on main (`git diff HEAD origin/<branch>` shows only lines that main changed later), then, before the first push, run `git merge -s ours origin/<branch> -m "merge: record old tip (already on main)"`. The `ours` merge keeps the tree exactly as main and makes the push a fast-forward, with no force. The PR diff still shows only the new work.

**A go from the user for work in the next session: add a GO block.** If the user gave a go for work in the next session, add a GO block to the resume prompt, after the State lines and before "Next steps". The block does six things:

- Quotes the user's exact words and the UTC time.
- States what the go covers.
- States what it does NOT cover (other writes, charges, merges, deletions, customer messages).
- Makes the user's condition (for example "after a recheck of everything") the first numbered step. The fixed branch update then becomes step 2, because it changes the branch and the user's condition comes first.
- Tells the resume session to confirm, before it acts, that nothing said since that time has withdrawn, paused or narrowed the go. If anything has, the resume session asks the user in its own chat. It also asks again if the recheck changes the scope.
- For a high-risk go (money, authorization changes, data, a migration, external communications), states when it lapses. A sensible default is 60 minutes after the go; use the lapse the user or your team set. A resume session that starts later asks for a fresh go in its own chat before the first such write.

```text
GO: "<the user's exact words>" (<UTC date and time>).
Covers: <the work the go covers>.
Does NOT cover: <other writes, charges, merges, deletions, customer messages>.
Condition: <the user's condition> is the first numbered step below.
Before you act: confirm nothing said since that time has withdrawn, paused or narrowed this go. If it has, ask the user in this chat.
Ask again if the recheck changes the scope.
Expires: <UTC time> for money, authorization, data, migration or external communications; after that, ask for a fresh go in this chat before the first such write.
```

Worktree mode:

```text
Resume <project> in worktree <wt-name> (branch <branch>). Pick up from the <date> session.
Read first: <handoff doc path> on origin/<branch> @ <short sha>, or none (<why>).
State: worktree at <path> on branch <branch> - <commits ahead>, <clean/dirty>.
Deployed: <what is live, if any>.
Not live yet: <fixed in source but not yet deployed / synced / re-rendered, or none>.
Blocked on: <who owes what, since when, or none>.
Do NOT: <decisions not to undo, or none>.
Corrected: <beliefs proved wrong this session and the truth, or none>.
In flight: <subagents + report paths, background jobs (check the output), timers, outward items with IDs, or none>.
Subagent assignments: <per unfinished subagent: goal, scope, files it owns, model, what it finished; or none>.
Verify: <PR head + state, task status, deploy revision; or none>. Check each live and report any drift before acting on this brief; re-dispatch a subagent only for what its output lacks.
Next steps:
1. Bring the branch up to date with main: git fetch origin && git merge origin/main. On conflict, git merge --abort and flag it - do not force.
2. <highest priority>
3. <second priority>
Reference: <plan or doc, if any>
Decisions: <where this session's decisions are written, or none>
Skills to invoke by name (repo-local or plugin): <each skill the next session must load with the Skill tool, and whether it is repo-local or from a plugin; or none>.
Standing rules: <rules the user set that still apply, each with its date; or none>.
```

Single mode (no worktree):

```text
Resume <project>. Pick up from the <date> session.
Read first: <handoff doc path> on origin/<branch> @ <short sha>, or none (<why>).
State: <what is deployed, what branch>.
Not live yet: <fixed in source but not yet deployed / synced / re-rendered, or none>.
Blocked on: <who owes what, since when, or none>.
Do NOT: <decisions not to undo, or none>.
Corrected: <beliefs proved wrong this session and the truth, or none>.
In flight: <subagents + report paths, background jobs (check the output), timers, outward items with IDs, or none>.
Subagent assignments: <per unfinished subagent: goal, scope, files it owns, model, what it finished; or none>.
Verify: <PR head + state, task status, deploy revision; or none>. Check each live and report any drift before acting on this brief; re-dispatch a subagent only for what its output lacks.
Next steps:
1. Bring the branch up to date with main, skip if already on main: git fetch origin && git merge origin/main. On conflict, git merge --abort and flag it.
2. <highest priority>
3. <second priority>
Reference: <plan or doc, if any>
Decisions: <where this session's decisions are written, or none>
Skills to invoke by name (repo-local or plugin): <each skill the next session must load with the Skill tool, and whether it is repo-local or from a plugin; or none>.
Standing rules: <rules the user set that still apply, each with its date; or none>.
```

**The last two lines of each block carry what a new session cannot guess.** `Skills to invoke by name` lists every skill the next session must load with the Skill tool, each with its exact name and whether it is repo-local or from a plugin. A prompt that only says "see the doc" leads a fresh session to read SKILL.md as a file, and it then skips the skill's steps. `Standing rules` lists the user's rules that outlive this window (policy, limits, no-go areas), each with its date. A new session does not know a rule that was said only in chat. Write "none" rather than dropping a line.

Keep every handoff short enough that another engineer, or your next session, can resume without reading the whole conversation. For pick up, the copyable prompt must be one unbroken block, not split across prose.
