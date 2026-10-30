{MARK}. The user asked the Session Recovery session to reconnect every offline session and review it. This message is that request.

Rules for this turn:
- Read-only. Do not send, pay, delete, change, commit, push, merge, or archive anything. Do not post to any ticket system, chat, or email. Write nothing except your reply in this thread.
- If a later message in this thread arrived while you were offline, do not act on it. List it under "Decisions for the user" and wait.

Task: re-read the live state of the item you were working on (the repository and branch, the ticket or task, the logs, the thread). Then decide one verdict:
- **DONE**: nothing is left to do. Ready to wrap and archive.
- **NEEDS WORK**: something is still open.
- **DUPLICATE**: another session owns this item. Name it.
{DUPES}
Post nothing in this thread before the review: no progress lines. Your only message is the review.

Reply in this exact Markdown shape. Use real line breaks. Put a blank line between sections. Each bullet is one line. Bold exactly as shown. No paragraph longer than two lines. No tables.

**Verdict: DONE | NEEDS WORK | DUPLICATE of <session title>**

**Bottom line:** one sentence.

**What changed since you went offline**
- one line per change, or "- Nothing changed."

**Open items**
1. **<item>**: what is open. **Recommend:** the action, or "no basis, because ...".

**Decisions for the user** (reply `go` to accept every recommendation)
1. **<decision>**: **Recommend:** ...

**If the user says go:** one line on what you will do.

End with this fenced block and nothing after it:

```
REVIEW RESULT: done | needs-work | duplicate
```
