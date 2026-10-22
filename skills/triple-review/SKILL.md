---
name: triple-review
description: "ALIAS - retired; forwards to review-swarm. Kept so `/triple-review` and older references still resolve. Triggers on: triple review, triple-review, triple check, triple-check this, three-model review, 3-model review, review with all three, Codex Gemini GLM, panel review."
---

# Triple Review -> retired, use Review Swarm

The triple review was retired. The panel review is now **`review-swarm`** (Codex + Gemini + GLM + a deep-reasoning Claude pass).

**Do this now:** invoke the **`review-swarm`** skill with the exact same request the caller gave you (same mode and target), and follow it end to end.

`/triple-review <args>` is equivalent to `/review-swarm <args>`. This alias exists only for back-compatibility. New work should call `review-swarm` directly.
