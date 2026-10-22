# Status sweep: per-environment behaviour

Items marked **not verified** come from tool descriptions only. Verify them the first time you sweep in that environment, and update this file.

## What is the same everywhere

| Item | Behaviour |
|---|---|
| Session list | `ListAgents`: `name [ref] · kind · status · started Xh ago`. It is the source of truth for which sessions exist. |
| Transcripts | `~/.claude/projects/<cwd with every non-alphanumeric char as ->/<sessionId>.jsonl`, in the folder of the cwd the session STARTED in. |
| Title records | `custom-title` (`customTitle`) and `agent-name` (`agentName`), repeated through the file. `summary` records appear in older transcripts. A session renamed later shows the new name in ListAgents, so a name can change between two sweeps. |
| Other useful records | `last-prompt`, `worktree-state` (`worktreeSession.worktreePath`), `pr-link`, `relocated`. |
| Human prompts | `type: user` with `origin.kind = human`. `origin.kind = task-notification` is an injected turn, not the user. |
| Cross-session messages | Socket based (`uds:/tmp/cc-socks-<uid>/<pid>.sock`). Delivered text arrives wrapped as a cross-session message with `from-name` and `from-mode`. See "Message caveats" below. |

## A. Local Mac

- **Transcripts:** `/Users/<you>/.claude/projects/...`.
- **Registry:** `~/.claude/sessions/<pid>.json` is written by the same CLI. **Not verified on a Mac yet**: run `ls ~/.claude/sessions` first. If it is missing, fall back to title records and transcript mtimes (`ls -t ~/.claude/projects/*/*.jsonl | head`).
- **ListAgents:** lists local sessions on this Mac, plus Remote Control sessions on other machines when Remote Control is connected. A session running on another host (for example a second Mac, or a remote server) can appear in the same list; its transcript is on THAT host, so it is unreadable from here. Its name pattern (a host or machine prefix) is the clue.
- **Desktop app sessions:** the desktop app's Bash tool keeps a `cd` between calls. Run the helper with absolute paths, or in a subshell, so the sweep does not move your own session out of its worktree.

## B. Shared Linux host (several Unix users)

- **One Unix user per operator seat** (for example `user-a` and `user-b`). Each has its own `~/.claude`. Home folders are mode `drwxr-x---`, so **user A cannot read user B's transcripts or registry** (`ls /home/<other>/.claude` gives "Permission denied"). Messaging sockets are per user too (`/tmp/cc-socks-<uid>/`, mode `drwx------`).
- **ListAgents shows only your own Unix user's sessions**, plus Remote Control rows. Report other users' sessions as out of scope, not as missing.
- **Remote Control sessions started on this host:** they run locally, so their transcripts ARE readable (kind shows `interactive`), even though the name may carry a bridge-style prefix.
- **`Remote Control · offline` rows:** sessions whose host is not connected (another machine, or a host that is asleep). All sessions on one host go offline together when that host sleeps; this is not data loss. Their transcripts are not on this host: report them as unreadable.
- **Registry gaps:** a live, idle session (listed by ListAgents) can have a local transcript but no registry file. Fall back to the title records. Always reconcile the ListAgents set against the registry.
- **Stale registry files:** the registry keeps files for dead pids, so it can hold many more files than there are live sessions. The helper checks each pid; do not count a dead entry as a session.
- **Bash cwd:** on a shared host a `cd` into another worktree of the same repo is kept and becomes your session's working directory. Use absolute paths or a subshell.

## C. Claude cloud (claude.ai/code web sessions)

- **The container is isolated and fresh.** It holds only this session's own transcript. Other cloud sessions and your local sessions are not on its disk, so the helper finds nothing to resolve beyond itself.
- **`get_session`** (on the Claude Code remote-sessions MCP server, when present) describes THIS session only, with `session_id` omitted. It is not a way to read other sessions. **Not verified:** whether that server offers a `list_sessions` tool; it depends on your setup. If your tool list shows it, use it for status only.
- **ListAgents** (from the tool description, **not verified in a live cloud sweep**): with cloud access, it can list your account's other sessions, Remote Control sessions on other machines and cloud sessions, each row labeled by kind. You get name, kind, and status, but no transcript. Report the status from the row, and mark the rest unreadable.
- A cloud session can send a message but cannot receive a reply from another session yet. Do not ask a peer to answer.
- Most useful move from the cloud: report the ListAgents rows, then tell the user which host to run the full sweep on.

## Message caveats (all environments)

A successful `SendMessage` means the message reached the session, not that its Claude read it.
- A session in a different permission mode holds the message for its user's approval. The notice reads: `[Cross-session delivery notice] Your message to another session was held for the recipient user's approval ... Not delivered to that session's Claude yet; its user must approve first. Do not wait for a reply; continue, or choose another approach.`
- A held message can expire unapproved (the sender has usually moved on by then, which is the right call).
- Remote Control, cloud, and desktop sessions give no delivery report at all.
- So: the sweep never depends on a reply. Read the other session's state instead.
