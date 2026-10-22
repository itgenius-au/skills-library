---
name: fable-review
description: "ALIAS - renamed to review-with-claude. Forwards to `review-with-claude`. Kept so `/fable-review` and older references still resolve. Triggers on: fable review, fable-review, review with fable, ask fable, fable check, fable audit, fable opinion, isolated claude review, second claude opinion."
---

# Fable Review -> renamed to Review with Claude

This skill was renamed to **`review-with-claude`**.

**Do this now:** invoke the **`review-with-claude`** skill with the exact same request the caller gave you, and follow it end to end.

`/fable-review <args>` is equivalent to `/review-with-claude <args>`. This alias exists only for back-compatibility. New work should call `review-with-claude` directly. If you had a `~/.claude/fable-review.config.json`, copy it to `~/.claude/review-with-claude.config.json`.
