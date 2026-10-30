---
name: session-recovery
description: "Bring offline Claude Code background sessions back and clear the backlog: find each session that claude.ai/code shows as disconnected or offline, wake it on its own thread (never a copy), have it review itself read-only in a fixed readable format, merge duplicates under one owner, prepare each owner so the user only types `go`, and run a real session-wrap (done mode) on finished ones so the user can archive them. For a Linux VM that runs `claude --bg --remote-control` sessions, set up as in docs/claude-code-vm-setup-spec.md (section 11). Not a read-only report of live sessions (session-status-sweep) and not a slow or full VM (claude-vm-ops). Triggers on: session recovery, recover this session, reconnect sessions, disconnected sessions, offline sessions, sessions went offline, revive sessions, dedupe sessions, duplicate sessions, clean up sessions, wrap up sessions, session backlog, pin sessions, sessions keep going stale, session wrap done."
---

# Session recovery

Turns a backlog of offline background sessions into two lists: sessions ready to archive (each ends with "Session Wrap done"), and owner sessions that each wait for one typed `go`.

It builds on the guide [`docs/claude-code-vm-setup-spec.md`](../../docs/claude-code-vm-setup-spec.md), section 11 (background sessions from scripts). Read that section first: it holds the rules for resuming a session, and this skill puts them into a repeatable procedure. The guide's label **[seen]** means observed, not documented, so it may change.

## Why sessions go offline

- A `claude --bg` session is a daemon job. The daemon retires it after about **8 h idle** when it is bridged to claude.ai (`--remote-control`), and about 1 h when it is plain: `[bg] bg retire <short>: settled|idle-prompt, idle 8h` in `~/.claude/daemon.log`. **[seen]** There is no setting for this time.
- Sessions the user starts from claude.ai or the mobile app are served by the account's Remote Control server (`claude-remote-control-N`) and are not retired when idle. They go offline when the server loses them, for example when the account's sign-in fails. See "Sessions served by the server" below.
- A retired session keeps its transcript and thread. Typing in its thread does **not** wake it: the message waits until something resumes it, then it is delivered right after the wake.
- **The keep-alive is a pin.** The daemon skips a pinned session. The user pins it in the interactive `claude agents` view with Ctrl+T (guide section 11); a headless agent cannot press keys there. A pinned idle session costs no tokens and about 200 MB of memory, so pin only what must stay up, and size the number of pins against the VM's free memory.

## Sessions served by the server (sign-in loss)

When a Remote Control account loses its sign-in, its server stops the session workers. Fix the sign-in first, with the [`claude-vm-ops`](../claude-vm-ops/SKILL.md) skill ("needs to sign in again"). A session that stopped in the middle of a turn belongs to that skill's "resume the casualties" step (its `references/signin.md`): the user sends its failed message again. For idle sessions, the user opens each thread in claude.ai/code and sends one message, and the server starts the worker again. **[seen]**

- These sessions have no job in `~/.claude/jobs`, so the scripts below do not see them. Do not use `resume` on them.
- **Never reattach a session whose environment is live.** `claude remote-control --session-id` takes the session from the server's own worker, and when you stop it the session goes offline again. Reattach is only for a session whose environment is gone (guide section 14).

## Hard rules

1. **A review is read-only.** The wake prompt allows no writes. Nothing is sent, paid, changed, committed or archived by a review.
2. **Never relay an approval.** A `go` for a risky action must come from the user, typed in the session's own thread. Never wake a session with text that reads as the user's approval. Relay data and plan changes; the user types `go`.
3. **Resume only offline sessions.** `claude --bg --resume` on a live session starts a COPY with a new id and thread. Message a live session instead (see "Sending to sessions").
4. **Check for queued messages before a wake.** A message typed while offline is delivered after the wake and runs with the session's permissions. A queued "yes" can trigger the action it answered (guide section 11).
5. **Batches of about five, duplicates first.** One proposed owner per duplicate group; the others review as DUPLICATE and list only what the owner lacks.
6. **"Session Wrap done" means a real wrap.** A finished session runs the [`session-wrap`](../session-wrap/SKILL.md) skill in done mode and puts the line "Session Wrap done" after its summary, followed by the skill's own closing line ("You can archive this conversation now." means DONE; "Not ready to archive: ..." or "Next session starts fresh." means HELD). Typing the line alone is not a wrap.
7. **Archive is the user's click.** Do not archive sessions yourself.

## Settings

No config file. `scripts/recovery.py` takes `--work DIR` (default `~/.claude/session-recovery`, for the inventory file) and `resume --default-cwd DIR` (the folder to wake a job from when it has none saved; default your home folder). `CLAUDE_CONFIG_DIR` moves the `.claude` folder it reads. It reads the `.claude` folder of the account it runs as and wakes sessions with that account's login, so **run it as the account that owns the sessions (`sudo -iu claude-N`), one account per run.**

## Steps

Run the commands from this skill's folder, or give `scripts/recovery.py` by its full path. Run them as the account that owns the sessions (`sudo -iu claude-N`), one account per run. For a second account, start again as that account.

### 1. Inventory
1. Get the list of offline sessions. Two ways:
   - **With the Claude Code Remote tools** (`list_sessions`, `mine: true`, `limit: 100`, paging with `after_id`): save each page to a file, then `python3 scripts/recovery.py inventory --sessions <page files...>`. It keeps non-archived `disconnected` sessions and joins each to its VM job (`~/.claude/jobs/*/state.json`, whose `bridgeSessionId` `cse_X` is claude.ai `session_X`).
   - **Without them:** the user names the sessions that claude.ai/code shows as offline. Run `python3 scripts/recovery.py inventory` with no `--sessions`. It lists every local job that has no live process, newest first. Match each offline session to a row by title, folder and time, and confirm each match with the user. Jobs that finished long ago also appear: wake only the ones the user names.
2. Rows with no VM job are desktop, IDE or Remote Control server sessions: list them for the user to handle by hand (see "Sessions served by the server").
3. For "why did this one go offline": `grep "bg retire <short>" ~/.claude/daemon.log`. A retire line with idle 8h is the normal case.
4. Group duplicates by item (same task, same ticket, same alert). Owner = the newest session made to carry the open items, else the most recently active.

### 2. Queue check
`python3 scripts/recovery.py queue-check`. With the Remote Control tools, a gap of about 28,800 s between claude.ai `updated_at` and the last local transcript entry is the retirement stamp, not a message. A larger gap prints `CHECK`. Without those tools there is no remote time, so every row prints `CHECK`. For a `CHECK` row, read the session's thread in claude.ai/code (or with the `list_events` tool, `kinds: ["user"]`; an empty page with `has_more` means page back with `before_id`) and skip any session with a human message after its last turn. **An agent with no Remote tools and no browser cannot read the thread.** On that path, the user must confirm for each session that nothing was typed in its thread after its last turn, before you run `resume` on it. Skip every session the user has not confirmed.

### 3. Wake and review
1. Dupes file (`{short: text}`), texts in `references/messages.md`.
2. `python3 scripts/recovery.py resume <short...> --dupes <file>`: wake only sessions that passed the queue check (or that the user confirmed). It refuses live sessions, runs from the session's own cwd with stdin closed and no other flags, and fills `references/review-prompt.md`. It does not pin. After a good wake it prints a reminder to pin any session that will wait for the user.
3. `Workspace not trusted`: the session's cwd is a worktree whose MAIN checkout has no trust key. Set `~/.claude.json` `projects["<main checkout>"].hasTrustDialogAccepted = true` (back it up, replace the file atomically), then `resume <short> --nudge` (the full prompt was already saved).
4. `python3 scripts/recovery.py read --wait 570 <short...>` and check the tool calls were read-only. The review is read-only, so any write tool call in the list is a defect: report it.
5. If a session does not answer within a minute or so, do not send again: the prompt is queued and runs on the next wake.

### 4. Report to the user
Per batch: archive-now list (links `https://claude.ai/code/<session id>`), each owner's verdict, decisions with a **Recommend:** each, anything flagged. Lead with what matters most (money at risk, a person never answered, a duplicate that would act twice).

### 5. Prepare each owner for a bare `go`
Send each owner a PREP message (`references/messages.md`): not an approval; fold in the merged plan and any data found; post the final plan ending "**Reply `go` to run this plan.**" Split the work so no two sessions do the same cleanup.

### 6. Real wraps for finished sessions
Send the WRAP message: run `session-wrap` in done mode, put the line "Session Wrap done" after the summary, or with "Reply `go` to apply." when a step needs the user's own approval. Pinning is the user's job: ask them to pin the session (Ctrl+T in the interactive `claude agents` view) before you send WRAP, so it is not retired while it wraps. Run `python3 scripts/recovery.py wrap-wait --mark "run a real session wrap" <short...>`. **Assumption, not documented:** Ctrl+T on a pinned row unpins it. Ask the user to check each DONE session's row, because a pinned idle session keeps about 200 MB. Collect captures that several wraps propose for the same files and ship ONE docs change.

## Sending to sessions
Use the `SendMessage` tool if your Claude Code has it, or ask the user to type the message in the session's thread. Names can collide (two sessions for one alert), and refs are not on disk and change on every wake. List the live agents again before sending: run `claude agents --json` as the account that owns the sessions (it prints the active sessions as a JSON array; it can delete the registry files of dead sessions while it lists, guide section 11, so use it here and not as a routine read). Send the same message to every ref with that name, and give it a section per session id ("IF YOU ARE <short> ..."; the others reply "WRONG SESSION" and do nothing).

## Gotchas
- **A signed-out claude.ai connector is signed out for every session.** Give the session the data as text instead of asking it to read the connector.
- **Sessions started by cron run in cron's cgroup, not the account's unit,** so the unit's memory limits do not cap them (guide section 9.4). Size any pin count against `MemAvailable`.
- **A CLI auto-upgrade restarts the daemon** (`self-restarting for upgrade` in `daemon.log`); it adopts the live workers and keeps the pins. **[seen]**
- **`wrap-wait` reads only the latest reply.** If the user talks to a session after its wrap, it reports RUNNING again, which is correct: the session is active. Ask the user to pin it again if they are now waiting on it. A message typed or queued after the wrap reopens it until the session answers. A background task notification also reopens it, so a long RUNNING after a clean wrap may be only that.
- **Sessions you start by hand are not pinned for you.** One that waits at a prompt for the user goes offline at about 8 h. The user pins it with Ctrl+T in the interactive `claude agents` view. To see why a session went offline: `grep "bg retire <short>" ~/.claude/daemon.log`.
- **Prove a pin with a positive control.** After the 8 h mark, there is no `bg retire <short>` line for the pinned id AND at least one unpinned session retired in the same window, with the pinned session's own last activity over 8 h ago (a typed reply resets the clock).
- **A cross-session reply can fail with `connect ECONNREFUSED .../<pid>.sock`.** The sender has ended. List the live agents again (`claude agents --json`, as above); if it is gone, send the data to the session that now owns the work and keep a copy in a doc.
- **The claude.ai status line can misread a review.** A review whose "If the user says go:" line names an action can make the status read as if the action ran, when nothing ran. Read the reply itself before you report a session's state.
- **The Claude Code Remote `send_message` tool needs per-call approval.** A session that cannot show the prompt gets "MCP tool call requires approval". Use the `SendMessage` tool instead. If your Claude Code has no `SendMessage`, the user sends the message by hand: give them the exact text and the session link `https://claude.ai/code/<session id>`, and they type it in the session's thread.
- **Plain marker lines read badly.** Give sessions the fixed Markdown shape in `references/review-prompt.md`; machine lines go in a fenced block at the end.

## Files
- `scripts/recovery.py`: `inventory`, `queue-check`, `resume`, `read`, `last-reply`, `wrap-wait`. Tests: `scripts/test_recovery.py` (`python3 -m pytest scripts`; they use fixtures only, no VM and no login).
- `references/review-prompt.md`: the RECOVERY REVIEW v1 wake prompt.
- `references/messages.md`: dupes, PREP, WRAP, review-only wrap and nudge texts.
