# Pick up: the Step 7 handoff rules and the Step 9 resume prompt

## Step 7: if intent is pick up

Also non-destructive: leave the worktree and branch mounted exactly as they are. The only difference from pause is the handoff - because the window is closing (or about to be compacted), Step 9 emits a full, copyable resume prompt instead of a short recap. Do not clean up, merge, or delete the worktree or its branch here. Shipping approved recommendations (below) is separate from the worktree.

**Branch must be on origin before you hand off.** Step 6 already pushed it unconditionally. If Step 6's verify printed `BLOCKED`, fix that now - resolve the push and re-verify `HEAD == origin/<branch>`. Never emit a pick up handoff for a branch that is not on remote: the resume may run on a different machine, and an off-origin branch cannot be pulled there.

If your team tracks work in a task tracker, post a wrap note there stating what is done, what is left, and the next step.

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

## Step 9: the pick up resume prompt

**Precondition:** the branch is on origin, including the brief commit when one was made ("Save the brief" below): it is pushed and `HEAD == origin/<branch>` passed again after that commit. Do not emit the block before then; the resume may run on another machine that can only pull what is on remote. A save that was skipped or refused does not block the block (see "Save the brief"). Also, every recommendation is dispositioned and the approved ones are shipped (Step 7 "If Intent Is Pick Up"; a context-full pick up defers them all).

Put one line in the prose above the block: start the new session only after this window stops working, and treat this window as closed from then on. The prose above the block also carries the `Deep pass: ...` and `Sub-session sweep: ...` lines from Step 4.

Emit ONE copyable, self-sufficient resume prompt as a single fenced block. It must let a fresh (or freshly-compacted) session continue without the prior context, so include: project, worktree path + branch, deployed/branch state, known blockers (who owes what, since when), the exact next steps, and any reference doc. Even when you expect to resume right after compacting, write it so it stands alone if the window is gone.

Give every worktree the prompt names (to resume OR to close) as an absolute path: on a machine with several users, each has its own checkout and cannot read the others, so a relative `.claude/worktrees/<name>` can point the next session at the wrong checkout. The absolute path can still be missing where the session resumes (a pickup written on one machine and resumed on another names a path that does not exist there). So add one fallback line to the worktree-mode prompt: if that path is missing on this machine, run `git fetch origin <branch>`, then `git worktree add -b <branch> <repo>/.claude/worktrees/<name> origin/<branch>` from the repo's main checkout (if a local `<branch>` already exists, check it is level with `origin/<branch>` and add it without `-b`), then `EnterWorktree(path: ...)`. The branch is on origin (Step 6), so the worktree can always be rebuilt from it.

**Machine-bound next steps name the machine.** The fallback above rebuilds a branch on any machine, but it cannot move data that lives on one machine only. When a next step needs one machine (its local files, a desktop-app tool, or config only that machine holds), name the machine in the prompt's first line. Directly under that line, add `If this is not <machine>, stop and tell the user before any step.`, with the machine's name in place of `<machine>`.

**What the handover must also carry.** The next session gets only this block and the docs. Anything that lives only in this window is lost, so fill each of these lines, in the template's order (write "none" rather than dropping a line). They all go in the saved brief; the printed block can be the short block (see "Print the SHORT block" below):

- **Read first:** the saved brief's path, the branch it is on, and the commit that holds it (see "Save the brief" below), or `none` and why, when no brief was saved.
- **Not live yet:** work fixed in source but not yet live, per layer. Examples: code on a branch vs the deployed service, a config file vs the live system, a script vs the rendered output. "Fixed" is false if only the source changed.
- **Blocked on:** who owes what, and since when, so the next session does not chase it again.
- **Do NOT:** decisions the next session must not helpfully undo. End every Do NOT line with whose decision it is and the date: `(user's ruling, <date>)` or `(agent limit, <date>)`. A request the user made that the agent declined is an OPEN decision, never the user's refusal: write it under `Blocked on` or in the next steps as open, and ask the user.
- **Corrected:** anything this session believed that turned out wrong, and the truth. Wrong beliefs are the most expensive thing to hand off, because they get acted on.
- **In flight:** every subagent (what it owned, finished or failed, where its findings are saved), every background job (tell the next session to check for its output, not the job, and say if a rerun is safe), every timer this session set (see "Session-bound timers"), and every outward-facing item left mid-flight (unsent draft, unanswered mention, pending approval) with its ID. In the native Claude app, also every sub-session this session opened and has not swept (id and title; see "Sub-session sweep").
- **Subagent assignments:** a subagent that is still running or unfinished does not carry over to the next session. For each one, write its assignment so the next session can dispatch it again: the goal, the scope, the files or items it owns, the model, and what it already finished. The next session checks for its output first and re-dispatches only what is missing. Keep long assignments in the saved brief and point to them.
- **Verify:** the live values the next session checks before it acts: PR head SHA and state, task status, deploy revision, the last reply in a thread you wait on. The line itself tells the next session to report any drift before acting, because that session may not have this skill loaded.

Cheap handovers are banked earlier. A read-only subagent cannot write files, and the harness can refuse a subagent's report file. So the main session saves each report when it arrives, in a folder beside the saved brief, named after it without `.md` (for `docs/handoffs/2026-10-20-x.md`, the folder `docs/handoffs/2026-10-20-x/`). Then the roster is one line pointing at that folder, and the findings survive if the window ends mid-wrap. Never commit customer data, personal data or a secret: keep such a report outside the repo (for example the session scratchpad), and say in `In flight` that it was not carried.

**Read-back test before saving.** Re-read the block as a stranger: could you act on it without asking one question it could have answered? Rewrite any line that assumes something only this window knows. Then name, outside the block, anything that was NOT captured, so "safe to close" is true when you say it.

**Save the brief, then print it.** A prompt that exists only in chat is lost if the user closes the window before copying it. After the read-back test, write the full brief (the block plus any long subagent assignments) to the first of these that exists: a hand-off doc already built for this work; the handoff doc the repo's start-up instructions name; this work's runbook or plan; or a new `docs/handoffs/YYYY-MM-DD-<branch-slug>.md`. Do not pick a shared file the repo does not name: two branches that both change it conflict when they merge. Commit it in one commit with any reports saved during the wrap, run the Step 6 secret scan again (briefs and saved reports are where pasted tokens tend to land; a hit means remove the value and amend that commit before any push, never add a new commit on top), push, and re-run the Step 6 verify (`HEAD == origin/<branch>`). The saved copy names its branch only, since a file cannot hold the SHA of its own commit. The printed block's `Read first` line names the branch AND that commit's short SHA, not only the path: the saved brief can sit on a branch that is not merged yet, and a resume that reads the default branch then starts from an older entry.

Never commit the brief on the default branch. In single mode on the default branch, skip the save, and print the block with `Read first: none (on the default branch, nothing saved)`. If the push of the brief commit is refused (a protected branch, a rule), print the block anyway with `Read first: none (save refused: <the error>)`, and say above the block that the brief exists only in this message. With no saved brief, the block must hold what the brief would have held: write long subagent assignments in full, mark each report path `not carried (local only)`, and run the read-back test again. A failed save never withholds the prompt.

Give a one-line **next-session model suggestion** in the wrap PROSE (above the fenced block), graded against the *remaining* work (the forward-looking companion to the Step 2 model-fit check): name the tier and reasoning effort you would start on and why. **Do NOT put it inside the copyable resume prompt** - the block is fed verbatim to the next session, and a model line there would instruct that agent, whereas the model choice is the user's to make.

**Step 1 of "Next steps" is always the same: bring the branch up to date with main.** Between this handoff and the resume, `main` may have moved. So the resume session's first step updates the worktree branch from the latest `origin/main` before it touches the work - this keeps the branch current and the eventual merge clean. Keep this as the fixed step 1 in every block below, ahead of the work-specific steps. (With a GO block it is step 2: see the GO rule below.)

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

**Print the SHORT block when the brief is saved.** The saved brief already holds every line of the full block. So when `Read first` names a saved brief, print the short block below instead of the full one, and keep it to about 15 lines: it points at the brief and keeps only what must be in front of the next session before it reads anything. A GO block, when there is one, still goes in it, before `Next steps`. Print the full block (worktree or single mode, below) only when `Read first` is `none`: then the block is the only copy. A long paste block is harder to paste and to check. Step 1 of the short block takes the rebase, deploy-clone or already-merged wording above when that case applies.

Short block (brief saved):

```text
Resume <project>[ in worktree <wt-name>]. Pick up from <date> session.
Read first: <handoff doc path> on origin/<branch> @ <short sha>. Read it in full before you act: it holds State, Not live yet, Blocked on, Corrected, In flight and Subagent assignments.
Worktree: <absolute path> on <branch>; if missing here: git fetch origin <branch>, then from the repo's main checkout git worktree add -b <branch> <repo>/.claude/worktrees/<name> origin/<branch> (if a local <branch> already exists, check it is level with origin/<branch> and add it without -b), then EnterWorktree(path: ...). Or none.
Do NOT: <decisions not to undo, each ending (user's ruling, date) or (agent limit, date), or none>.
Verify: <PR head + state, task status, deploy revision; or none>. Check each live and report any drift before acting on this brief; re-dispatch a subagent only for what its output lacks.
Next steps:
1. Bring the branch up to date with main: git fetch origin && git merge origin/main. On conflict, git merge --abort and flag it - do not force.
2. <highest priority>
3. <second priority>
Skills to invoke by name (repo-local or plugin): <each skill and whether it is repo-local or from a plugin; or none>.
Standing rules: <rules the user set that still apply, each with its date; or none>.
```

Worktree mode (full block, when nothing was saved):

```text
Resume <project> in worktree <wt-name> (branch <branch>). Pick up from the <date> session.
Read first: <handoff doc path> on origin/<branch> @ <short sha>, or none (<why>).
State: worktree at <path> on branch <branch> - <commits ahead>, <clean/dirty>.
Deployed: <what is live, if any>.
Not live yet: <fixed in source but not yet deployed / synced / re-rendered, or none>.
Blocked on: <who owes what, since when, or none>.
Do NOT: <decisions not to undo, each ending (user's ruling, date) or (agent limit, date), or none>.
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

Single mode (no worktree; full block, when nothing was saved):

```text
Resume <project>. Pick up from the <date> session.
Read first: <handoff doc path> on origin/<branch> @ <short sha>, or none (<why>).
State: <what is deployed, what branch>.
Not live yet: <fixed in source but not yet deployed / synced / re-rendered, or none>.
Blocked on: <who owes what, since when, or none>.
Do NOT: <decisions not to undo, each ending (user's ruling, date) or (agent limit, date), or none>.
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
