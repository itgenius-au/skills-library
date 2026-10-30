# skills-library

Public [Claude Code](https://docs.claude.com/en/docs/claude-code) skills from
**[itGenius](https://itgenius.com)**.

One plugin, one `skills/` directory. It bundles the skills we use every day: the
full development process from idea to shipped change, a second opinion from other
frontier models, safe build and deploy gates, git hygiene, a clean session wrap,
executive summaries, checked PDFs, and a pass that strips the AI tells out of your writing.

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
| `dev-deploy-safely` | Production deploy gates: build-then-deploy-by-digest, served-image integrity, ancestor gate, full traffic on the new revision, rollback pointer, deploy record. |

The method behind these skills is written up in
[docs/build-and-ship-playbook.md](./docs/build-and-ship-playbook.md).

### Multi-model review

A different model catches blind spots yours misses.

| Skill | What it does |
|---|---|
| `review-swarm` | Run four independent models over one subject in a single pass (Codex, Gemini, GLM, and an isolated deep-reasoning Claude pass), then reconcile into one severity-ranked, consensus-tagged report. Has a quick mode. The review gate inside the build skills. |
| `review-with-codex` | Run OpenAI's Codex CLI, read-only, as a second reviewer for code, plans, decisions, or a build. |
| `review-with-gemini` | Run Google's Gemini CLI as a second reviewer under a read-only tool policy. |
| `review-with-glm` | Call z.ai's GLM models over HTTP as a reviewer, or offload a coding task to GLM. |
| `review-with-claude` | Run a deep-reasoning Claude model headless and read-only via `claude -p`, isolated from your session, as an independent reviewer. |
| `review-debate` | Run a 3-round debate between Claude, Gemini, and Codex: independent review, challenge disputes, then synthesize to consensus. |

### Session and repo hygiene

Keep the repo, the machine, and the session clean.

| Skill | What it does |
|---|---|
| `session-wrap` | End or checkpoint a session with one of four intents (done, pause, pick up, skill sweep): summarize, capture docs, handle git state behind a clean-tree gate, leave a self-sufficient resume prompt. |
| `session-dsp` | Squash the session's per-turn `wip` commits into one clean commit and push. Ships the wip-commit hook it pairs with. |
| `session-status-sweep` | Read-only report on every other live Claude Code session: the ask, branch, what is done, what waits on you, what is stuck. |
| `repo-cleanup` | Audit and safely clean up branches, worktrees, wip commits, and diverged main, plus a stale-work archive mode. Nothing is destroyed without proof no work is lost. |
| `repo-health-sweep` | Run every repo's own gates, produce one health map, and optionally auto-fix the fixable into push-ready branches. |
| `repo-context-cleanup` | Audit and trim the context Claude Code loads every session: CLAUDE.md files and the auto-memory store. |
| `machine-move` | Sync every repo before you switch machines (no uncommitted or unpushed work left behind), then set up the new machine. |
| `dev-update-env` | Audit and update CLI tools, MCP servers, and system packages on macOS or Linux, with one summary table and confirmation before any update. |
| `plugin-fresh-install-test` | Test what a brand-new machine actually gets from a Claude Code plugin (skills, SessionStart context, guards), graded from events, not the model's self-report. |

### Writing and daily

| Skill | What it does |
|---|---|
| `exec-summary` | Turn complex content into a short plain-language executive summary: key points, numbered decisions with recommendations, next steps, bottom line. |
| `copy-humanizer` | Strip AI fingerprints from copy, blog posts, and email so it reads like a person wrote it. |
| `document-pdf` | Make a checked PDF from one Markdown source (reports, letters, agreements, evidence bundles), with a verify gate before you send anything. |
| `morning-brief` | Build a daily brief HUD from your own sources. |

### Guides

| Guide | What it covers |
|---|---|
| [Claude Code on a VM](./docs/claude-code-vm-setup-spec.md) | Run Claude Code on an always-on Linux VM and drive it from your phone. A full setup spec: sizing, systemd units, sign-in, updates, multiple accounts, security, and troubleshooting. Not tied to one cloud provider. |

### Renamed skills

Version 1.2.0 renamed several skills to match the names we use in-house. The old
names still work: each one is a small alias that forwards to the new skill.

| Old name | New name |
|---|---|
| `quad-review`, `triple-review` | `review-swarm` |
| `codex-review` | `review-with-codex` |
| `gemini-review` | `review-with-gemini` |
| `zai-review` | `review-with-glm` |
| `fable-review` | `review-with-claude` |
| `ai-debate` | `review-debate` |
| `deploy-safely` | `dev-deploy-safely` |
| `cleanup-git` | `repo-cleanup` |

## Prerequisites

You only need the tools for the skills you use.

- **`review-with-codex`, `review-debate`**: the Codex CLI (`npm install -g @openai/codex`)
  signed in with `codex login`.
- **`review-with-gemini`, `review-debate`**: the Gemini CLI
  (`npm install -g @google/gemini-cli`) plus a Gemini API key from
  [Google AI Studio](https://aistudio.google.com/apikey) as `GEMINI_API_KEY`.
- **`review-with-glm`**: a z.ai API key (GLM Coding Plan or pay-as-you-go) as
  `ZAI_API_KEY`. See [z.ai/subscribe](https://z.ai/subscribe).
- **`review-with-claude`**: the Claude Code CLI itself (`claude`), which the skill runs
  in an isolated read-only process. Model choice is yours to configure.
- **`review-swarm`**: orchestrates the four review skills above, so it needs
  whatever subset of those tools you have. It degrades if a leg is missing.
- **`document-pdf`**: Python 3 plus WeasyPrint, or a headless Chrome or Chromium,
  to build. A Markdown converter: `pandoc`, or the `markdown` Python package. The
  verify gate needs poppler (`pdfinfo`, `pdftotext`, `pdftoppm`).
- **`repo-cleanup`** archive mode: the `gh` and `gcloud` CLIs and a private
  cloud-storage bucket. The rest of the skill needs only git. The stale-work
  inventory uses `gh` and `jq` for open-PR data and degrades to branches only
  without them. The tag-trigger check needs Python 3 with PyYAML (`pip install pyyaml`).
- **`dev-brainstorming`** visual companion: Node.js. The rest of the skill needs nothing.
- **`plugin-fresh-install-test`**: the `claude` CLI and `jq`.
- **`review-swarm`** post-panel check (`postpanel.sh`): the `gh` CLI.
- **`session-status-sweep`, `repo-health-sweep`**: Python 3.
- **Build and deploy skills**: adapt the deploy examples (containers, static,
  file hosts) to your own stack. They call the review skills above for their
  review gates.

Keys come from your own env or secret manager. Nothing here hard-codes a key.

## A note on the build and deploy skills

`dev-quick-build`, `dev-auto-build`, and `dev-deploy-safely` encode a specific, opinionated method. The gate concepts are general: TDD, multi-model review,
build-by-digest, served-image integrity, an ancestor gate, a rollback pointer, a
deploy record. The deploy commands use one stack as the worked example. Treat
them as a template to adapt, not a turnkey pipeline for every environment.

## Credits

Several skills in the dev process are adapted from the **Superpowers** Claude Code
plugin by **Jesse Vincent** (https://github.com/obra/superpowers), which is MIT
licensed: `dev-brainstorming`, `dev-writing-plans`, `dev-qa-verify`, and
`dev-debugging`. The `repo-context-cleanup` skill's `claude-md` mode is adapted from
Anthropic's **claude-md-management** plugin
(https://github.com/anthropics/claude-plugins-official/tree/main/plugins/claude-md-management),
which is Apache-2.0 licensed, and bundles three reference files from it. Full
attribution and both license texts are in
[THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).

## Contributing

Issues and pull requests welcome. Keep skills provider-accurate, avoid
hard-coding model versions or secrets, and match the existing SKILL.md style.

## License

[MIT](./LICENSE) © itGenius, except the third-party material noted in
[THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md): Superpowers (MIT, Jesse Vincent)
and Anthropic's claude-md-management (Apache-2.0).
