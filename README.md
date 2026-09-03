# skills-library

Public [Claude Code](https://docs.claude.com/en/docs/claude-code) skills from
**[itGenius](https://itgenius.com)**.

One plugin, one `skills/` directory. It bundles the skills we use every day: get
a second opinion from other frontier models, build and ship behind real safety
gates, keep git tidy, wrap a session cleanly, and strip the AI tells out of your
writing.

## Install

```text
/plugin marketplace add itgenius-au/skills-library
/plugin install skills-library@skills-library
```

Restart Claude Code (or start a new session) so the skills load.

## What's inside

**Multi-model review** - a different model catches blind spots yours misses.

| Skill | What it does |
|---|---|
| `codex-review` | Runs OpenAI's Codex CLI as a second reviewer for code, plans, decisions, or a build. |
| `gemini-review` | Runs Google's Gemini CLI as a second reviewer, with live Google Search grounding. |
| `zai-review` | Calls z.ai's GLM models over HTTP as a third reviewer, or offloads a coding task to GLM. |
| `ai-debate` | Runs a 3-round debate between Claude, Gemini, and Codex: independent review, challenge disputes, then synthesize to consensus. |

**Build and ship** - a rigorous method with real gates.

| Skill | What it does |
|---|---|
| `quick-build` | Build and ship ONE small feature end to end in a session: worktree, TDD, multi-model review, safe deploy, browser verification. |
| `auto-build` | Drive a plan to a push-ready branch, unattended: build per phase, verify, triple-review to clean, stop at the human gate. |
| `deploy-safely` | Production deploy gates: build-then-deploy-by-digest, served-image integrity, ancestor gate, rollback pointer, deploy record. |

**Git and workflow** - keep the repo and the session clean.

| Skill | What it does |
|---|---|
| `cleanup-git` | Audit and safely clean up branches, worktrees, wip commits, and diverged main. Nothing is destroyed without proof no work is lost. |
| `finish-branch` | Decide how to integrate finished work (merge, PR, or cleanup), with a clean-tree gate first. |
| `repo-health-sweep` | Run every repo's own gates, produce one health map, and optionally auto-fix the fixable into push-ready branches. |
| `session-wrap` | End or pause a working session: summarize, capture docs, handle git state, leave clear pickup instructions. |

**Writing**

| Skill | What it does |
|---|---|
| `copy-humanizer` | Strip AI fingerprints from copy, blog posts, and email so it reads like a person wrote it. |

## Prerequisites

You only need the tools for the skills you use.

- **Review skills** (`codex-review`, `ai-debate`): the Codex CLI
  (`npm install -g @openai/codex`) signed in with `codex login`.
- **`gemini-review`, `ai-debate`**: the Gemini CLI
  (`npm install -g @google/gemini-cli`) plus a Gemini API key from
  [Google AI Studio](https://aistudio.google.com/apikey) as `GEMINI_API_KEY`.
- **`zai-review`**: a z.ai API key (GLM Coding Plan or pay-as-you-go) as
  `ZAI_API_KEY`. See [z.ai/subscribe](https://z.ai/subscribe).
- **Build/deploy skills**: adapt the deploy examples (Cloud Run, static, file
  hosts) to your own stack. They call the review skills above for their review
  gates.

Keys come from your own env or secret manager. Nothing here hard-codes a key.

## A note on the build and deploy skills

`quick-build`, `auto-build`, and `deploy-safely` encode a specific, opinionated
method. The gate concepts are general - TDD, multi-model review, build-by-digest,
served-image integrity, an ancestor gate, a rollback pointer, a deploy record -
but the deploy commands use one stack as the worked example. Treat them as a
template to adapt, not a turnkey pipeline for every environment.

## Contributing

Issues and pull requests welcome. Keep skills provider-accurate, avoid
hard-coding model versions or secrets, and match the existing SKILL.md style.

## License

[MIT](./LICENSE) © itGenius
