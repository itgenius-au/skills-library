---
name: triple-review
description: "Compatibility alias - the house review is now the four-model quad review (Codex + Gemini + GLM + a deep-reasoning Claude pass). This skill forwards to `quad-review` so older invocations still resolve. Triggers on: triple review, triple-review, triple check, triple-check this, three-model review, 3-model review, review with all three, Codex Gemini GLM, panel review."
argument-hint: "[mode: code|decision|plan|doc|build] [target: file path, branch, dir, or description]"
---

# Triple Review -> Quad Review (alias)

The house panel review gained a fourth leg and was renamed from **triple review** to **quad review**.
The panel is now:

- **Codex** (OpenAI, external)
- **Gemini** (Google, external)
- **GLM** (z.ai, external)
- **Fable** (a deep-reasoning Claude pass, run isolated and read-only)

This skill exists only so `/triple-review` and any older references to "triple review" keep working.
It is a thin forwarding alias, not a separate implementation.

## What to do

Invoke the **`quad-review`** skill with the exact same mode and target the caller gave you, and follow
it end to end. Do not run a three-model review here yourself - hand off so the Fable leg is included
too.

- Same modes (`code` / `build` / `plan` / `decision` / `doc`), same synthesis, same gate behaviour.
- `/triple-review <args>` is equivalent to `/quad-review <args>`.

## Example

```
/triple-review code src/app/billing.ts
```

is equivalent to:

```
/quad-review code src/app/billing.ts
```

New work should call `quad-review` directly. This alias is kept only for back-compatibility with older
invocations and documentation that still says "triple review."
