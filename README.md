# itgenius-skills

Public [Claude Code](https://docs.claude.com/en/docs/claude-code) skills from
**[itGenius](https://itgenius.com)**.

This marketplace starts with one plugin, **`review-tools`**: get a second
opinion on your code, plans, and decisions from a *different* frontier model.
Claude is good, but a fundamentally different model catches blind spots Claude
misses. These skills run Codex, Gemini, and z.ai (GLM) headlessly, then let
Claude synthesize the findings, so disagreements between models become your
strongest signal.

## Install

```
/plugin marketplace add itgenius-au/itgenius-skills
/plugin install review-tools@itgenius-skills
```

Restart Claude Code (or start a new session) so the skills load.

## What's inside: `review-tools`

| Skill | What it does |
|---|---|
| **codex-review** | Runs OpenAI's Codex CLI as a second reviewer for code, plans, decisions, or a build. |
| **gemini-review** | Runs Google's Gemini CLI as a second reviewer, with live Google Search grounding. |
| **zai-review** | Calls z.ai's GLM models over HTTP as a third reviewer, or offloads a coding task to GLM. |
| **ai-debate** | Orchestrates a 3-round debate between Claude, Gemini, and Codex: independent review, challenge disputes, then synthesize to consensus. |

Each review skill runs in five modes: `code`, `decision`, `plan`, `build`, and
`codebase`.

## Prerequisites

You only need the tools for the skills you use.

- **codex-review**: the Codex CLI (`npm install -g @openai/codex`) signed in to a
  ChatGPT account (`codex login`).
- **gemini-review** and **ai-debate**: the Gemini CLI
  (`npm install -g @google/gemini-cli`) plus a Gemini API key from
  [Google AI Studio](https://aistudio.google.com/apikey), provided as the
  `GEMINI_API_KEY` env var.
- **zai-review**: a z.ai API key (a GLM Coding Plan or pay-as-you-go balance),
  provided as the `ZAI_API_KEY` env var. See [z.ai/subscribe](https://z.ai/subscribe).

Keys come from your own env or secret manager. Nothing here hard-codes a key.

## Use it

Trigger a skill by asking in plain language, or call it directly:

```
/codex-review code                       # review uncommitted changes
/gemini-review plan docs/my-plan.md      # critique a plan
/zai-review decision "Postgres vs Firestore?"
/ai-debate build                         # 3-model audit of a branch vs main
```

Claude picks the skill automatically when you say things like "get a second
opinion on this", "have Codex review my changes", or "run an AI debate on this
decision".

## Why multiple models

One model reviewing its own kind of work has consistent blind spots. A different
architecture, trained differently, flags different issues. Where two models
agree, you can trust it. Where they disagree, that is exactly where a human
should look. `ai-debate` formalizes this: it preserves minority opinions instead
of averaging them away.

## Contributing

Issues and pull requests are welcome. Keep skills provider-accurate, avoid
hard-coding model versions or secrets, and match the existing SKILL.md style.

## License

[MIT](./LICENSE) © itGenius
