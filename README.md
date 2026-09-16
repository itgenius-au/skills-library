# skills-library

Public [Claude Code](https://docs.claude.com/en/docs/claude-code) skills from
**[itGenius](https://itgenius.com)**.

One plugin, one `skills/` directory. It bundles the skills we use every day: the
full development process from idea to shipped change, a second opinion from other
frontier models, safe build and deploy gates, git hygiene, a clean session wrap,
and a pass that strips the AI tells out of your writing.

## Install

```text
/plugin marketplace add itgenius-au/skills-library
/plugin install skills-library@skills-library
```

Restart Claude Code (or start a new session) so the skills load.

## What's inside

### The dev process

An idea becomes an approved design, a design becomes a plan, a plan gets built
and verified behind real gates. Each skill hands off to the next.

| Skill | What it does |
|---|---|
| `dev-brainstorming` | Turn a vague idea into a concrete, approved design or spec through dialogue. Holds a hard "no build before approval" gate; can open a visual companion in a browser. |
| `dev-writing-plans` | Turn an approved spec into a granular, dependency-ordered implementation plan, hardened by a review-until-consensus loop before any build. |
| `dev-quick-build` | Build and ship ONE small feature end to end in a session: worktree, TDD, multi-model review, safe deploy, browser verification. |
| `dev-auto-build` | Drive a plan to a push-ready branch, unattended: build per phase, verify, review to clean, stop at the human gate. |
| `dev-qa-verify` | The verification-before-completion gate: an interactive browser or persona pass that proves a change works on the real surface, then triages defects by severity. |
| `dev-debugging` | Reproduce on demand, form one hypothesis, isolate the cause with evidence, fix the root cause, then lock it with a regression test. |

The method behind these skills is written up in
[docs/build-and-ship-playbook.md](./docs/build-and-ship-playbook.md).

### Multi-model review

A different model catches blind spots yours misses.

| Skill | What it does |
|---|---|
| `quad-review` | Run four independent models over one subject in a single pass (Codex, Gemini, GLM, and an isolated deep-reasoning Claude pass), then reconcile into one severity-ranked, consensus-tagged report. The review gate inside the build skills. |
| `codex-review` | Run OpenAI's Codex CLI as a second reviewer for code, plans, decisions, or a build. |
| `gemini-review` | Run Google's Gemini CLI as a second reviewer, with live Google Search grounding. |
| `zai-review` | Call z.ai's GLM models over HTTP as a reviewer, or offload a coding task to GLM. |
| `fable-review` | Run a deep-reasoning Claude model headless and read-only via `claude -p`, isolated from your session, as an independent reviewer. |
| `ai-debate` | Run a 3-round debate between Claude, Gemini, and Codex: independent review, challenge disputes, then synthesize to consensus. |
| `triple-review` | Run Codex, Gemini, and GLM over one focused diff at once, then reconcile into a single report. Degrades gracefully if a model is unavailable. |

### Deploy and workflow

Keep the repo, the deploy, and the session clean.

| Skill | What it does |
|---|---|
| `deploy-safely` | Production deploy gates: build-then-deploy-by-digest, served-image integrity, ancestor gate, rollback pointer, deploy record. |
| `session-wrap` | End or pause a working session: summarize, capture docs, handle git state (merge, PR, or cleanup, behind a clean-tree gate), leave clear pickup instructions. |
| `cleanup-git` | Audit and safely clean up branches, worktrees, wip commits, and diverged main. Nothing is destroyed without proof no work is lost. |
| `repo-health-sweep` | Run every repo's own gates, produce one health map, and optionally auto-fix the fixable into push-ready branches. |
| `machine-move` | Pre-flight audit before switching machines (find uncommitted or unpushed work and local-only state), then set up the new machine after cloning. |

### Writing and daily

| Skill | What it does |
|---|---|
| `copy-humanizer` | Strip AI fingerprints from copy, blog posts, and email so it reads like a person wrote it. |
| `morning-brief` | Build a daily brief HUD from your own sources. |

## Prerequisites

You only need the tools for the skills you use.

- **`codex-review`, `ai-debate`**: the Codex CLI (`npm install -g @openai/codex`)
  signed in with `codex login`.
- **`gemini-review`, `ai-debate`**: the Gemini CLI
  (`npm install -g @google/gemini-cli`) plus a Gemini API key from
  [Google AI Studio](https://aistudio.google.com/apikey) as `GEMINI_API_KEY`.
- **`zai-review`**: a z.ai API key (GLM Coding Plan or pay-as-you-go) as
  `ZAI_API_KEY`. See [z.ai/subscribe](https://z.ai/subscribe).
- **`fable-review`**: the Claude Code CLI itself (`claude`), which the skill runs
  in an isolated read-only process. Model choice is yours to configure.
- **`quad-review`**: orchestrates the four review skills above, so it needs
  whatever subset of those tools you have. It degrades if a leg is missing.
- **Build and deploy skills**: adapt the deploy examples (containers, static,
  file hosts) to your own stack. They call the review skills above for their
  review gates.

Keys come from your own env or secret manager. Nothing here hard-codes a key.

## A note on the build and deploy skills

`dev-quick-build`, `dev-auto-build`, and `deploy-safely` encode a specific,
opinionated method. The gate concepts are general: TDD, multi-model review,
build-by-digest, served-image integrity, an ancestor gate, a rollback pointer, a
deploy record. The deploy commands use one stack as the worked example. Treat
them as a template to adapt, not a turnkey pipeline for every environment.

## Credits

Several skills in the dev process are adapted from the **Superpowers** Claude Code
plugin by **Jesse Vincent** (https://github.com/obra/superpowers), which is MIT
licensed: `dev-brainstorming`, `dev-writing-plans`, `dev-qa-verify`, and
`dev-debugging`. Full attribution and the license text are in
[THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).

## Contributing

Issues and pull requests welcome. Keep skills provider-accurate, avoid
hard-coding model versions or secrets, and match the existing SKILL.md style.

## License

[MIT](./LICENSE) © itGenius. Third-party attributions in
[THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).
