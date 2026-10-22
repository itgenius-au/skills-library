---
name: repo-context-cleanup
description: "Audit and clean up the standing context Claude Code carries into every session - CLAUDE.md files and the auto-memory store - so a fresh session orients fast and the always-loaded context stays lean and accurate. Three modes: `claude-md` scores CLAUDE.md files against a quality rubric and applies targeted fixes; `memory` merges duplicates, fixes stale facts, enforces conventions, and prunes the MEMORY.md index; `full` runs both. Use it proactively before a machine move or after a long stretch of work. Standing context only; for git branches and worktrees use repo-cleanup. Triggers on: repo context cleanup, claude cleanup, clean up CLAUDE.md, audit CLAUDE.md, is CLAUDE.md still accurate, improve project memory, cleanup memory, consolidate memory, tidy memory, memory hygiene, memory orphan check, MEMORY.md is bloated."
argument-hint: "[mode: claude-md | memory | full]"
---

# Repo Context Cleanup - CLAUDE.md + auto-memory hygiene

> **Credit.** The `claude-md` mode is adapted from the **`claude-md-improver`** skill
> in Anthropic's **claude-md-management** plugin
> (https://github.com/anthropics/claude-plugins-official/tree/main/plugins/claude-md-management),
> which is licensed under Apache-2.0. The three `references/claude-md-*.md` files are
> copied from that plugin. See [`../../THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md)
> for the full license text and a statement of changes. The `memory` mode and the
> `full` mode are original to this repository.

Claude Code carries two kinds of standing project context into every session:

1. **CLAUDE.md files** - checked into the repo, shared with the team, loaded when a session starts in (or under) that directory.
2. **The auto-memory store** - a `MEMORY.md` index plus one file per fact under `~/.claude/projects/<slug>/memory/`. The index loads on **every turn**; the topic files load on demand.

Both degrade quietly. Commands go stale, architecture notes drift from the code, memory entries pile up and duplicate, and the always-loaded index grows until the harness truncates it and the tail entries silently stop loading. A session then wastes turns rediscovering what it once knew, or worse, acts on a fact that is no longer true.

This skill is the periodic pass that keeps both healthy. It is deliberately conservative: **nothing is deleted without first proving no knowledge is lost.**

## Modes

Pick the mode from the user's request. If they did not name one, ask, or infer it: a request about CLAUDE.md files chooses `claude-md`, a request about memory chooses `memory`, "clean up my project context" or a pre-machine-move sweep chooses `full`.

| Mode | What it does | Read next |
|---|---|---|
| `claude-md` | Find every CLAUDE.md, score it against a rubric, report grades, then apply targeted, approved improvements. | [references/claude-md-quality-criteria.md](references/claude-md-quality-criteria.md), [references/claude-md-templates.md](references/claude-md-templates.md), [references/claude-md-update-guidelines.md](references/claude-md-update-guidelines.md) |
| `memory` | Reflective pass over the auto-memory store: merge duplicates, retire the dated, fix stale facts, enforce conventions, verify layout, prune the index. | [references/memory-cleanup.md](references/memory-cleanup.md), [references/memory-conventions.md](references/memory-conventions.md) |
| `full` | Run `claude-md`, then `memory`, and close with one combined report. | both sets above |

## Mode: claude-md

Audit and improve CLAUDE.md files so Claude has accurate, concise project context. Five phases:

1. **Discovery.** Find every CLAUDE.md in the repo:
   ```bash
   find . -name "CLAUDE.md" -o -name ".claude.md" -o -name ".claude.local.md" 2>/dev/null | head -50
   ```
   Note the type of each: project root, package/module, subdirectory, local override (`.claude.local.md`, gitignored), or the user-global `~/.claude/CLAUDE.md`.

2. **Assessment.** Score each file against the six-criterion rubric in [references/claude-md-quality-criteria.md](references/claude-md-quality-criteria.md) (commands, architecture, non-obvious patterns, conciseness, currency, actionability). Cross-reference claims against the real codebase: run or read the documented commands, check referenced files exist, confirm the architecture description matches the tree.

3. **Report.** **Always output the quality report before changing anything.** Per file: the score, the grade, the specific issues, and the recommended additions. This is the checkpoint where the user sees what you found.

4. **Targeted updates.** Propose additions only, and only ones that earn their place: commands or gotchas discovered during analysis, package relationships that were not obvious, config quirks. Show each change as a diff with a one-line "why this helps future sessions". Do not restate what the code already says, do not add generic best practice, do not log one-off fixes. See [references/claude-md-update-guidelines.md](references/claude-md-update-guidelines.md).

5. **Apply.** After approval, apply with the Edit tool, preserving existing structure.

Templates by project type (root minimal/comprehensive, package, monorepo) are in [references/claude-md-templates.md](references/claude-md-templates.md). Use only the sections a given project actually needs.

## Mode: memory

A reflective pass over the auto-memory store so future sessions orient quickly and the index stays cheap to load. The full method is in [references/memory-cleanup.md](references/memory-cleanup.md); the conventions it enforces are in [references/memory-conventions.md](references/memory-conventions.md). In outline:

1. **Take stock.** Locate the store, read `MEMORY.md`, skim each topic file. Check index size, layout integrity, and any entries missing the recommended structure. (Commands in `memory-cleanup.md`, Phase 1.)

2. **Relevance check (large stores).** For ~100+ entries, or when the user asks "which of these are still worth keeping", judge each entry by whether the thing it describes still exists and still matters, not by eyeballing. The one guardrail that matters: low recent use is **not** a reason to retire a rarely-fired safety rule. Method in [references/memory-cleanup.md](references/memory-cleanup.md), Phase 1b.

3. **Consolidate.** Separate durable from dated. Merge overlaps into one survivor (and update its index hook). Compress a mostly-stale file down to its one live item. Relocate project- or person-specific knowledge to where it belongs. Fix relative dates to absolute. Drop what is trivially re-findable from the code, git, or an API.

4. **Verify layout.** Confirm every index entry resolves to a real, readable file, and (if you use the version-controlled symlink layout) that the links point the right way and the real files are tracked in git.

5. **Tidy the index.** Keep `MEMORY.md` under its size budget - the index loads every turn, and past the harness limit it truncates and tail entries stop loading. Trim fat index lines to one-line hooks first (non-destructive); remove pointers to retired entries; keep topical order.

6. **Report**, then offer to commit if the store is version-controlled.

The keep-everything rule holds throughout: **retire means archive or relocate, never silent-delete.**

## Mode: full

Run `claude-md` end to end, then `memory` end to end. Present one combined report so the user sees both passes together. This is the right choice before a machine move or a long handoff, when you want the whole standing context clean at once.

## Shared rules (both modes)

- **Report before you change.** Both modes checkpoint with a report the user approves before edits land. Context files are load-bearing; a bad edit misinforms every future session.
- **Verify before you delete or enshrine.** A memory or a CLAUDE.md line that names a file, flag, secret, or command is a *claim*. Confirm the named thing still exists (grep the code, check your secret manager, hit the API) before you delete the note that describes it - and before you write a new note asserting it. This matters most for anything a subagent generated: a consolidated doc full of plausible-looking ids is worthless if one is invented.
- **Keep it concise and specific.** Every line in a context file spends context budget on every future turn. Prefer the project-specific fact that is hard to re-derive over the generic advice that is not.

## Report format

Close with a short summary. For `claude-md`:

```
CLAUDE.md files: N found, M updated
- ./CLAUDE.md: C -> B (added Commands + 2 gotchas)
- ./packages/api/CLAUDE.md: A (no change needed)
```

For `memory`:

```
Files touched: N
- Merged: A -> B (reason)
- Retired: X (archived/relocated, reason)
- Restructured: Z (added Why / How-to-apply)
- Index: was N lines / NK chars -> now M lines / MK chars
```
