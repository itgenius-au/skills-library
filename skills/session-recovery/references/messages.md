# Message texts

Send these to live sessions: with the `SendMessage` tool if your Claude Code has it, or ask the user to type them in the session's thread. The first line names the purpose. Add "If you are not <short>, reply "WRONG SESSION" and do nothing." when a name is shared.

## Dupes file entries (for `recovery.py resume --dupes`)

Owner:
> You are the PROPOSED OWNER for <item>. <N> older sessions handle the same item and will defer to you: <short> (<title>), ... Read their latest messages so your review covers every open <item> task, and list any you take over.

Member:
> Duplicate check for <item>. PROPOSED OWNER: session <short> ('<title>'). If <short> covers your open items, your verdict is DUPLICATE of <short>. Under Open items, list only what <short> does not hold yet.

## PREP (owner, or a duplicate with its own cleanup)

> The user's request via the Session Recovery session: prepare session <short> for a bare `go`.
>
> This message is NOT an approval. Do not run any of the plan now. Your only action: post your final plan in this thread, in the review format (bold headings, numbered steps, one line each), so the plan the user reads is exactly what their `go` approves. End with the line: **Reply `go` to run this plan.**
>
> Fold in: <merged steps, data found, steps dropped because another session owns them>.

If a step reaches another person (an email, a customer message, a public post), say in the plan that the send still needs the user's separate "send" after they see the draft.

## WRAP (finished session): a real wrap ending "Session Wrap done"

> The user's instruction, relayed by the Session Recovery session: run a real session wrap for this session (<short>) now.
>
> Load and run the `session-wrap` skill in DONE mode (the "done" intent: summarise, capture durable docs and learnings, integrate, handle git and worktree state).
>
> - Send nothing to anyone outside this machine.
> - If any wrap step needs the user's own approval under your rules (for example a branch delete, or a merge that ships), do every other step, then list the held steps and end with "Reply `go` to apply."
> - When the wrap is complete with nothing held, put the line "Session Wrap done" after your summary; the `session-wrap` skill's own closing line follows it.

"Session Wrap done" is the marker the user archives on. It always follows a real `session-wrap` run, never on its own.

## REVIEW-ONLY WRAP (when the user wants to see the wrap before anything is applied)

> Run `session-wrap` with the done intent, but apply nothing now: do not commit, push, merge, delete, archive or send anything. Show **Summary**, **Captures I propose**, **Cleanup I propose**, **Open items** (each with a **Recommend:**). End with **Reply `go` to apply this wrap.**

## Nudge (after a refused resume saved the prompt)

> RECOVERY REVIEW v1 follow-up: the review request was saved for you and should arrive with this wake. Run it once. If you did not receive a message starting 'RECOVERY REVIEW v1. The user asked the Session Recovery session', reply only 'MISSING REVIEW PROMPT' and stop, without running tools.
