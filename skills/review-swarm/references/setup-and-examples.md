# Choosing, setup and example invocations

## How it differs from `review-debate` (pick the right one)

| | `review-swarm` (this) | `review-debate` |
|---|---|---|
| Reviewers | Codex + Gemini + GLM + **Fable** (4) | **Primary agent** + Gemini + Codex |
| Rounds | **One** (review -> synthesize) | **Three** (review -> challenge -> synthesize) |
| Primary agent | Orchestrator only | A reviewer + moderator |
| Speed / cost | Faster, ~4 parallel calls | Deeper, up to ~4 calls + debate |
| Use when | Fast high-confidence panel over a subject | The finding is disputed and needs models to argue it out |

Reach for `review-debate` when a `review-swarm` surfaces a genuine disagreement worth litigating. (It runs Gemini and Codex through the same wrappers as this skill.) Reach for a single `review-with-codex` / `review-with-gemini` / `review-with-glm` / `review-with-claude` for a quick one-model sanity check.

## When to use

- **Pre-merge / pre-ship code review** of a feature diff or branch.
- **A decision** with real downside (architecture, trust model, money, legal/tax).
- **A plan** before building against it.
- **A document** you are about to act on (contract, filing, tax position, runbook).
- The **review gate** inside `dev-quick-build` (plan review) and `dev-auto-build` (diff review).

**When NOT to use**: a small/obvious change, a style pass, or anything where one model is plenty - use a single `review-with-*` skill. Speed-critical work where one opinion suffices.

## Prerequisites (each model's own skill owns the details)

- `review-with-codex` - Codex CLI signed into the reviewer's own ChatGPT account (`codex login`). The login is per OS user: on a shared machine each user needs their own, or every Codex leg fails with HTTP 401.
- `review-with-gemini` - Gemini CLI + a `GEMINI_API_KEY` in the environment.
- `review-with-glm` - a z.ai key (`ZAI_API_KEY`) in the environment + a funded GLM Coding Plan.
- `review-with-claude` - the machine's own Claude Code login (no key). Fable runs via headless `claude -p`; you choose its model in `~/.claude/review-with-claude.config.json`.

Keys come from your own environment or secret manager. **Never** use someone else's key.

**Model pins.** Each model name lives in exactly one place: the default variable near the top of that leg's wrapper script (`codex-exec.sh`, `gemini-exec.sh`, `glm-exec.sh`), or, for Fable, your config file. Do NOT restate versions in this skill or in a leg's prose (they rot); say "the default model" and match whatever the wrapper pins. To change a model, change that one variable.

## Example invocations

```
/review-swarm code                                  # uncommitted changes
/review-swarm code src/app/billing.ts               # a specific file
/review-swarm build                                 # this branch vs main (feature diff)
/review-swarm quick build                           # same, ~10-minute panel (not for risky subjects)
/review-swarm plan docs/plans/example-plan.md        # a plan before building
/review-swarm decision "move the user store from Firestore to Postgres"
/review-swarm doc ~/Downloads/example-contract.md   # a document before acting on it
```
