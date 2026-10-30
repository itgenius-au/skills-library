---
name: session-wrap
description: "End or checkpoint a working session cleanly with four distinct intents - done (complete: integrate and close), pause (staying in this window), pick up (window closing, compacting or context full: hand off a self-sufficient resume prompt), or skill sweep (deep review of the session's skill and doc lessons, closes nothing). Summarizes work, captures durable docs, and handles git state."
argument-hint: "[done|pause|pick up|skill sweep] [project-name]"
---

# Session Wrap

Use this skill at the end of a working session in a project or worktree.

The goal is to preserve useful state, keep documentation current, and avoid leaving ambiguous git or deployment state for the next person.

## Reference files (read the file when its row applies)

This file holds the intent rules, the gates that apply on every wrap, and the done-mode gate. Procedures that apply to one mode or one branch live in `references/` beside it. Open a file when its row applies, and open it BEFORE you do the step it names: a row is an instruction, and skipping it skips that step's rules. Step 3 picks the mode; Step 6 scans for secrets and pushes the branch to origin in every mode, committed or not; the Done gate in Step 7 binds you before any worktree is removed. Text past the first screens of this file is not kept after a compaction: after one, re-read the Done gate (Step 7), the Step 6 secret scan and push block and the Step 9 closing lines in this file before you remove a worktree or end the wrap.

| When | Read now |
|---|---|
| Step 2, in every mode, right after the summary table | `references/model-fit.md` |
| Step 4, the scan prints a `NOTE` or a `WEAK` line, or finds 0 evidence | `references/deep-scan-details.md` |
| Step 4, in every intent, before you decide what to write or recommend (pause skips the scan and the deep pass, not this file) | `references/learning-capture.md` |
| Step 4, in the native Claude app (the `mcp__ccd_session_mgmt__*` tools exist) | `references/sub-session-sweep.md` |
| Intent is skill sweep | `references/skill-sweep.md`, before Step 4 |
| Intent is pause | `references/pause.md`, in Step 7 (its merge decision sends you to `references/done-merge-path.md`) |
| Intent is pick up | `references/pick-up.md`, in Step 7 before you write anything for the handoff, and again in Step 9 before you write the resume prompt |
| Intent is done and the worktree merges straight into the default branch, or a pause approves a merge to the default branch | `references/done-merge-path.md` |
| Intent is done, and the default branch is PR-protected (a push is rejected with `GH013`) | `references/done-pr-merge-path.md` |
| Intent is done, and there is nothing to merge (discard) | `references/done-discard-path.md` |
| Step 8, and this session drove the Claude-in-Chrome extension | `references/close-browser-tabs.md` |

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
| Discovered | Findings, gotchas, decisions (by ID, once Step 4 writes them), external service behavior |
| Pending | Started but unfinished work, each item with a **Recommend:** line |
| State | Current branch, dirty files, pushed/unpushed commits, deployment state |

If the session included production work, include exact deploy targets, revisions, smoke checks, and rollback pointers.

**Every pending or open item carries a recommendation.** Write each one as the item, what it waits on, and **Recommend:** the action you advise, in a few words. When you have no basis for one, write "No recommendation: <why>" instead of leaving it blank. A list of open items with no recommendations is hard to act on.

**Before you list an item as blocked on the user, check whether you can do it yourself.** "Waits on <person>" is true only when the step needs access or a decision you do not have. Check your own access first: the CLIs on this machine, stored credentials, the tools in this session. Access alone is not approval: authorization changes, secret or data writes, irreversible actions and external messages still need the owner's OK, or a draft. If you can do the step and the wrap mode allows it, do it now, or list it as pending with **Recommend:** do it next session. List an item as blocked on a person only with the missing access or decision named.

### Model fit check (all modes)

Read `references/model-fit.md` now and add its short note to the summary. It runs in every mode (pick up, pause, done).

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
| `this conversation`, `this session`, `deeply`, `only this conversation` (with skill sweep or review wording) | skill sweep: a deep review of the current session |
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

(`$SKILL_DIR` is this skill's base directory, printed when the skill loads. To check the bundled scripts themselves, run `bash "$SKILL_DIR/scripts/tests/run-tests.sh"`; it needs no credentials.) The scan prints a bounded digest of evidence lines (explicit user directives, corrections, repeated tool errors) and a final `DEEP_CANDIDATES=0|1`. It degrades cleanly and never breaks a wrap.

Scan output and edge cases (`NOTE`, `WEAK` and `SPAN` lines, the session-id seed, a main checkout, no git work tree): read `references/deep-scan-details.md` now when the scan prints a `NOTE`, a `WEAK` line or 0 evidence, and before you read `DEEP_CANDIDATES=0` as nothing found.

**Run the scan from inside this session's worktree.** It matches transcripts by working directory, so from a main checkout it matches every session that ran there. If you left your worktree mid-session (for example with `ExitWorktree(action: keep)`), re-enter it with `EnterWorktree(path: ...)` first. Then check that each `EVIDENCE` line names this session's transcript.

**Gating:** run the scan AND the deep pass (agents) when the intent is done, pick up or skill sweep (Step 3). pause uses the checklist and the improvement decision from memory and runs neither. A pick up is usually the longest window, where early corrections have faded most, so it gets the deep pass too. In a context-full pick up, dispatch the deep-pass agents in the background and do not wait for them: write and emit the resume prompt first (Step 7, "Context full"), then fold their findings in as deferred recommendations, or name them on the handover's `In flight` line if the window ends first. In pick up, also use the `EVIDENCE` lines to fill the handover's `Do NOT` and `Corrected` lines (Step 9).

In every intent, read `references/learning-capture.md` now, before you decide what to write or recommend (pause skips the scan and the deep pass, not this file). It holds the depth rule, the checklist, the priority table, the improvement decision with its Recommendations block, and the deep-pass agents. One checklist item applies to every intent and stays here:

- A decision was made (every intent: done, pause, pick up). Give each one exactly one home: an existing decisions block or bullet first, else this session's plan or build doc, else a new `docs/decisions/YYYY-MM-DD-<topic>.md`.

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

Read `references/learning-capture.md` ("Improvement decision") now: it holds the self-assessment, the escalation ladder and the Recommendations output block. The applied-updates line below is required whenever you ran this step.

**Applied-updates line (always, next to the Recommendations block).** Print one line: `Skill and doc updates applied: <list> | none`. List every auto-applied doc and skill update (for example a skill Lessons entry and its PR) by path or PR. A wrap that merged a skill Lesson and printed only "No skill/hook/plugin recommendations" reads as "no skill updates", so the applied updates always get their own line.

### Deep pass (done, pick up and skill sweep, required for a substantive session)

On a done or pick up wrap the deep pass is **required, not optional**, when `DEEP_CANDIDATES=1`, OR the session did **substantive multi-step work** (a real procedure, an integration, a debugging arc, a build - your judgement, not a phrase), OR it was compacted or very long, OR the user said "go deep". Treat `DEEP_CANDIDATES=1` as substantive. A dedicated agent then makes the reusability call on the actual transcript instead of leaning on your fading memory. Skip it only for a trivial session with nothing reusable.

**`DEEP_CANDIDATES=0` is never a skip reason on its own.** The scan reads only typed user turns, so an autonomous session (the user typed little more than "go") reads as empty even after hours of work. When the session made commits, opened or merged PRs, deployed, or ran a long tool-driven build or investigation, treat it as substantive: run the forced general-review subagent below. Skip only when the session was also trivial in what it did, not just in what the user typed.

**Deep pass line (always, in the done and pick up output).** Print exactly one line: `Deep pass: ran (<n> agents)` or `Deep pass: skipped because <reason>`. A skip names why the session was trivial; "not needed" and "0 candidates" alone are not reasons.

To dispatch the deep-pass agents (candidates present, a forced pass with no candidates, slicing a long transcript), read `references/learning-capture.md` ("Deep pass agents") now.

### Sub-session sweep (native Claude app only: done and skill sweep)

Read `references/sub-session-sweep.md` now when this session has the `mcp__ccd_session_mgmt__*` tools (in its tool list or its deferred-tool list). Without them (the CLI, a cloud session, a VM), print `Sub-session sweep: not the native app` and skip. pause skips it.

**Sub-session line (always, next to the `Deep pass:` line).** Print exactly one line: `Sub-session sweep: <n> swept, <m> already wrapped, <k> unreadable (<names>)`, or `Sub-session sweep: none opened`, or `Sub-session sweep: not the native app`.

### Skill sweep (intent: closes nothing)

Intent is skill sweep: read `references/skill-sweep.md` now, before the scan. It says which steps run and which are skipped; Step 9 gives the closing message.

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

Then run session-dsp's commit step WITHOUT its push, starting with its secret scan of the squash. Reset and commit stay in ONE bash call (the wip hook can fire between turns), and the push comes from the unconditional block below:

```bash
git reset --soft "$LAST_NONWIP" && git commit -m "$(cat <<'EOF'
<drafted message>
EOF
)"
```

Then run the post-squash gate: `git diff --stat origin/main..HEAD` (use your default branch) lists only files this session touched.

**Commit message approval.** In worktree mode, the wrap request is the approval: show the drafted message in the wrap summary and commit. In shared-branch mode, show the draft and wait for an OK.

**Nothing to squash.** If there are no wip commits from this session, the squash stops on a mixed window, or the tree has no changes, say so and skip the commit work - but do NOT skip the push below.

**Secret scan before the push - every mode, every push in this wrap.** Run it even when nothing was squashed: a repo without an auto-commit hook never reaches session-dsp's commit step, so this may be the only scan it gets. `CLAUDE_SKILL_DIR` is this skill's folder; the `session-dsp` skill sits beside it and bundles the scanner.

```bash
python3 "${CLAUDE_SKILL_DIR}/../session-dsp/scripts/scan_secrets.py"
```

It scans what the push would publish: each commit not yet on a remote (every commit's own patch, so a value added in one commit and removed in the next is still found), plus anything staged. It covers private-key blocks, cloud and provider API keys and tokens (including Stripe-shape live keys), JWTs, Bearer tokens, OAuth client secrets, password and secret assignments, and an added `.env` file. It prints each finding with the value masked. On Windows, use `python` if `python3` opens the Microsoft Store.

- **Exit 0:** clean. Push.
- **Exit 2:** **STOP. Do not push, merge or hand off.** Show the user the masked findings. Remove the value (and rotate it if it was ever pushed), or put `secret-scan: allow` on a line you have confirmed is a false positive and say so in the wrap; then scan again. Remove the value, or add the marker, by amending the commit that added it (a rebase when that commit is older), never with a new commit on top: the push would still carry the first commit, and the scan keeps reporting it.
- **Exit 1:** the scan could not run (for example no upstream and no `origin` default branch to compare with). Say so and ask the user before you push. Never read it as clean.

If the scanner is not installed beside this skill, use a secret scanner you have (for example `gitleaks` or `trufflehog`) over the same range and apply the same stop rule. With neither, say so and ask the user before you push. Run the scan again before any later push in this wrap, for example the pick up brief commit.

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

Read `references/pause.md` now. It holds what to leave in place, what to report, the timer rule, and the merge decision for a worktree (IS_WORKTREE=1).

### If Intent Is Pick Up

Read `references/pick-up.md` now, before you write anything for the handoff. This step's part holds the branch-on-origin rule, the recommendations-first order, what this window must not touch after the handoff, timers, background tasks and the hand-over while the old window is still working.

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
- **A worktree you handed off belongs to the next session.** Before you merge, discard or remove a worktree this conversation touched, check that no other session works in it now. Signs: its branch has commits you did not make (`git log origin/<branch>`), its tip moved after your pick-up handoff, or a session you handed it to has started. If another session owns it, do not merge, discard or remove it, and do not delete its branch. Name it in the wrap with its owner; that is the reason it cannot close here. Record no "done" or stage move for its build in your task tracker either: that work is still open, and the owner moves the item when it closes.

`git worktree list` shows what physically exists, for orientation ONLY - it does not define the set to close. Never act on a worktree just because the list prints it.

Now close each worktree THIS conversation touched. Classify it against the default branch, then choose **merge** or **discard** (repeat per worktree). **Done is not complete while a worktree this conversation touched is still open** - merge or discard each, or name any that cannot close this session with the reason. Then skip ahead to Step 8, then Step 9.

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

Read `references/done-merge-path.md` now. It holds the guard script (Guard 0, Guards 1 and 2, Gate 3, the atomic merge, Gate 4, the post-push check, then cleanup). Run it as written. Do not run `git worktree remove` or `git branch -d` from memory.

#### Merge path - PR-protected default branch (integrate via a merged PR)

When the default branch is branch-protected (a rule such as "Changes must be made through a pull request" plus required status checks), the direct `git push` above is REJECTED (`remote: error: GH013: Repository rule violations found`), so the integration is a **merged PR**, not a push. Treat this as a first-class case: more repos enable it over time. This is still the done intent: merging the PR IS the integration, so you do not leave it open (leaving a PR open for someone else to merge is a different, hand-off intent).

Detect it by the push rejection (the reliable signal), or check ahead with `gh api "repos/{owner}/{repo}/rulesets" >/dev/null 2>&1`. Guard 2 (worktree branch == `origin/$WT_BRANCH`) from the Merge path still applies; Guard 1 is moot here - the merge happens server-side, not via a local checkout mutation.

Read `references/done-pr-merge-path.md` now. It holds the PR script, the merge gate, the two footguns and the local worktree cleanup that follows.

#### Discard path

Read `references/done-discard-path.md` now, before you remove a worktree that has nothing to merge.

After closeout, verify with `git worktree list` that every worktree THIS conversation touched is gone (merged or discarded) and its branch deleted. Other worktrees still listed belong to other sessions and are EXPECTED - leave them; they are not a sign of an unfinished wrap. A worktree this conversation touched still listed, with no reason recorded, means `done` is not finished. Stop immediately if any command above fails - do not continue cleanup after a failed merge or push. End that stop report with the Step 9 `Not ready to archive: ...` closing line.

## Step 8: Close This Session's Browser Tabs (pick up / done)

Run this only when the window is closing (**pick up** or **done**). **Skip for pause** - work continues and the session may still need its tabs.

When this session drove the Claude-in-Chrome extension, it left a tab group. If the window closes without closing those tabs, the group is orphaned: a later session cannot reach it (the extension's tab tools act only on the *current* session's group), and it lingers as an empty-looking leftover in Chrome. Closing the tabs now lets Chrome auto-remove the group.

**Applies only to sessions that used the Claude-in-Chrome extension.** If this session never drove that extension, or `ToolSearch` finds no `mcp__claude-in-chrome__tabs_*` tools, SKIP this step cleanly - it is a no-op, not an error.

If this session drove the extension, read `references/close-browser-tabs.md` now and close the tabs it lists.

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

Read `references/pick-up.md` again now, from its heading "Step 9: the pick up resume prompt" on. It holds the resume prompt template, the Read-first, Verify and Do NOT lines, the GO block, the short block and the step 1 rule. Do not write the prompt from memory.
