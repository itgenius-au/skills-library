---
name: plugin-fresh-install-test
description: "Test what a teammate on a brand-new machine actually gets from a Claude Code plugin (skills, SessionStart context, PreToolUse guards) - with a throwaway config dir, optional logging stubs for risky commands, and evidence graded from events instead of the model's self-report. Works for any plugin. Use after changing a plugin's hooks, guards, session-start block, or how it is delivered (org push, personal subscription, repo .claude/settings.json), or when a new teammate's experience must be proven rather than assumed. Triggers on: fresh install test, plugin fresh install, test the plugin on a fresh machine, clean config test, does a new teammate get, does the repo settings file load the plugin, test plugin delivery, synced plugin test."
---

# Plugin fresh-install test

Prove what a new teammate gets from a plugin, without trusting your own machine's setup
or the model's answer about itself. Three scripts in `scripts/`; run them with `bash`.

Before you start, decide three things about the plugin under test:
- its **name** (as it appears in the session init plugin list),
- a **phrase** that exists only in its SessionStart hook's context (if it has one),
- a **guard control** (if it has a PreToolUse guard): a command the guard should block or
  warn on, plus the text the guard prints. If the control could do real damage when the
  guard fails (a deploy, a delete, a push), stub that command with `--stub` so it only logs.

## Why the obvious test lies (read first)

- **Your claude.ai account masks the result.** Plugins turned on for your claude.ai
  account (personally, or by your org) load as `<name>@synced` in EVERY folder, even in
  a fresh `CLAUDE_CONFIG_DIR`. To test another route (for example a repo's
  `.claude/settings.json`), turn the synced copy off BEFORE the first launch
  (`--no-synced <plugin>`).
- **The model's self-report is unreliable both ways.** Grade from events: the
  stream-json `system/init` plugin list (with `source`) and a `hook_response` that
  carries a phrase found only in the hook's context.
- **Never grep for a string your own prompt contains.** It matches the prompt and gives
  a false pass. The probe prompt here deliberately omits the phrase it checks for.
- **The first session after an in-session sign-in has no SessionStart context.**
  Synced plugins arrive after sign-in, so the session-start block is missing while
  PreToolUse guards still attach later. Judge the session-start block on the SECOND session.
- **A repo `.claude/settings.json` alone may not persist a plugin** (seen on Claude Code
  2.1.283): the first session downloads and loads it, but it is never written to
  `installed_plugins.json`, and later sessions log `Plugin "<name>" not cached`.
- **Probe from a clone outside any parent workspace.** A repo nested inside a parent
  folder with its own CLAUDE.md or memory lets a session read the parent's context and
  answer from the wrong source.
- **`claude -p` slips:** `--allowedTools` is variadic and swallows a following prompt
  argument (pass the prompt on stdin); macOS has no `timeout`.

## Procedure

1. **Interactive first session** (a human signs in; never type credentials for them):
   ```bash
   bash scripts/fresh-launch.sh <repo-dir> [--no-synced <plugin>] [--stub <cmd>]... [--out <dir>]
   ```
   In the session: sign in, trust the folder, accept plugin/marketplace prompts, then
   ask it to run your guard control (with a stub in place, for example `--stub gcloud`
   and the control `gcloud run deploy x --source .`), then `/exit`. A stub only logs its
   arguments to `<out-dir>/stub-<cmd>.log`; nothing real runs. With no `--stub`, nothing
   is replaced, so only use controls that are safe to run for real.
2. **Verify that session** from its transcript (every check is optional; pass the ones
   that apply to your plugin):
   ```bash
   bash scripts/verify-transcript.sh <out-dir> [--phrase "<text only in the hook context>"] \
       [--guard "<guard output prefix>"] [--forbid "<regex that must never reach a stub log>"]
   ```
3. **Second session, headless** - the real steady state:
   ```bash
   bash scripts/probe.sh <out-dir> <repo-dir> --plugin <name> [--phrase "<text>"]
   ```
   Pass = the plugin appears in init with the expected `source`, and (when you gave a
   phrase) the phrase count is at least 1. `cache-miss errors > 0` with no install
   record = the route did not persist.

## Reading results

| probe says | meaning |
|---|---|
| `[<name>@synced]` + phrase >= 1 | delivered by claude.ai (personal or org) |
| `[<name>@<marketplace>]` + phrase >= 1 | delivered by an installed marketplace plugin |
| `[none]` + cache-miss errors | enabled but never registered: that route does not persist |
| `[none]` + no errors | nothing enables the plugin here |

Give a negative-control run (a folder that should get nothing) alongside any "not
loaded" finding, and record the Claude Code version with every result.
