---
name: ai-debate
description: "ALIAS - renamed to review-debate. Forwards to `review-debate`. Kept so `/ai-debate` and older references still resolve. Triggers on: ai debate, debate this, three-model review, consensus review, multi-model debate, 3-way review."
---

# AI Debate -> renamed to Review Debate

This skill was renamed to **`review-debate`**.

**Do this now:** invoke the **`review-debate`** skill with the exact same request the caller gave you, and follow it end to end.

`/ai-debate <args>` is equivalent to `/review-debate <args>`. This alias exists only for back-compatibility. New work should call `review-debate` directly.
