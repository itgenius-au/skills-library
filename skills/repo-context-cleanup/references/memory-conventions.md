# Memory store conventions

The conventions the `memory` cleanup pass enforces, and the ones to follow when you *write* memory in the first place. They are a documented default: sensible for any Claude Code auto-memory store, not tied to one person's setup. Adopt them as-is, or adapt the naming to a house standard as long as you stay consistent.

## The store

Claude Code keeps per-project auto-memory at `~/.claude/projects/<slug>/memory/`, where `<slug>` is the project's working directory with every `/` turned into `-` (so `/Users/you/code/app` becomes `-Users-you-code-app`). Find yours:

```bash
ls -d ~/.claude/projects/*/memory 2>/dev/null
```

Inside are two things:

- **`MEMORY.md`** - the index. It loads on **every turn**, so its size is a running tax on the context window.
- **One file per fact** - the topic files. Only `MEMORY.md` auto-loads; a topic file is **never auto-recalled** - Claude reads it explicitly with its file tools when the index hook (or a CLAUDE.md pointer) makes it look relevant. There is no background relevance engine, so a fact with no index line / pointer is effectively unreachable.

That split is the whole reason for the conventions below: the index has to stay tiny and high-signal, while the topic files can hold the detail.

## One fact per file

Each topic file holds a single fact with frontmatter:

```markdown
---
name: <short-slug>
description: <one line, human-facing summary; NOT an auto-recall trigger - see above>
metadata:
  type: user | feedback | project | reference
---

<the fact>
```

The four types:

- **`user`** - who the user is: role, expertise, stable preferences.
- **`feedback`** - how you should work: a correction or a confirmed approach.
- **`project`** - ongoing work, goals, or constraints not derivable from the code or git.
- **`reference`** - a pointer to an external resource (a URL, a dashboard, a ticket).

**`feedback` and `project` files lead with the rule or fact, then carry a `**Why:**` line and a `**How to apply:**` line.** The why is not decoration: it lets a future session judge an edge case instead of following the rule blindly or discarding it when it half-fits. A rule with no rationale is brittle.

Link related facts with `[[name]]` (the other file's `name` slug). Link liberally - a `[[name]]` with no file yet marks something worth writing later.

## Naming (recommended)

Give each file a **typed prefix**: `user_`, `feedback_`, `project_`, or `reference_`, then a snake_case topic (`feedback_no_force_push.md`). The payoff: the type is visible in a plain directory listing and in the index, so you can scan for every guardrail at once, and a mis-typed entry stands out. (Plain Claude Code uses a kebab-case slug with the type only in frontmatter; either works. Pick one and hold to it - a mixed store is hard to audit.)

## The index (`MEMORY.md`)

One line per entry, newest concern grouped with its topic, not by date:

```
- [Title](file.md) - one-line hook
```

The **hook says only WHEN to recall** the entry. All detail lives in the topic file. A fat index line that restates the whole fact is the single most common cause of index bloat.

**Watch the byte budget.** Because the index loads every turn, keep it small - on the order of tens of KB, and check it before adding:

```bash
wc -c ~/.claude/projects/<slug>/memory/MEMORY.md
```

Past the harness's limit the index is **truncated**, and the tail entries silently stop loading - so a bloated index does not just cost budget, it drops your oldest memories without warning. The lever for the budget is the **index lines**, not the topic files: trimming a fat topic file helps recall quality but frees no index budget; only shortening or removing index lines does.

## Durable vs dated

- **Durable** - preferences, key relationships, recurring conventions, operational guardrails. Keep and sharpen.
- **Dated** - a specific project, a deadline, a one-off incident. Once the date passes or the work ships, retire the file, or fold its lasting takeaway into a durable one (an incident becomes a `feedback_` rule).

## What belongs in memory, and what does not

Keep what is **hard to re-derive**: stated preferences, the *why* behind a decision, who to go to for what, a gotcha earned the hard way.

Do **not** put in memory:

- Code patterns, file paths, architecture facts - those belong in CLAUDE.md or the code itself.
- Anything already in a CLAUDE.md - duplication just spends the budget twice.
- Anything trivially re-findable from `git log`, an API, a secret manager, or an active config.

## Optional: version-controlled + symlink layout

If you want your memory to travel between machines and keep an audit trail, keep the **real files in a repo** (a `memory/` dir under version control) and **symlink them into the auto-memory dir** so Claude Code still auto-loads them. Git versions the real files; the symlinks make them live.

Two failure modes this layout introduces, both of which the cleanup pass checks:

- **Reverse orphan** - a real file (not a symlink) sitting in the auto-memory dir. It will not sync between machines. Rehome it: move it into the repo, then symlink it back.
- **Forward orphan** - a real file in the repo with **no** symlink (or a wrong-target symlink) in the auto-memory dir. It silently fails to load in new sessions. Relink it.

A small script that rebuilds every symlink to an **absolute** target is the one-shot fix for almost all breakage here, and is worth keeping next to the store if you adopt this layout. This layout is optional; a plain store with files directly in the auto-memory dir needs none of it.

## Optional: tiering when the index outgrows a flat model

One line per fact works until the index nears the harness cap (**200 lines OR ~25 KB, whichever comes first**). Because only `MEMORY.md` auto-loads and topic files are never auto-recalled (above), you cannot fix a bloated index just by moving facts to more files - a fact with no index line is unreachable. Instead, TIER the index:

- **Always-core** stays as individual index lines: identity, writing bans, and the *silent-failure* guardrails a session needs before it knows the task type (the "buried decision-rule" class - a rule that, if not already in context, is violated before any file is read). Universal working-method rules can also move up into a `CLAUDE.md` that loads alongside the index (off the index's byte budget).
- **Domain facts** (only relevant once you know you are doing deploy / database / browser work) move OUT of the index into a per-domain **bundle sub-index** file - one file per domain, holding those facts' hook lines, each still linking its topic file. The index keeps ONE "scan before X" pointer per bundle ("doing deploy work? read the deploy bundle first"). That pointer is the always-loaded trigger; the bundle is read on demand when the domain comes up.

This swaps N per-fact index lines for one per-domain pointer, so the always-loaded index stops scaling with the store's size; a new domain fact then goes into its bundle, NOT the index. The cost: one extra Read when a domain first comes up, and the pointer must be phrased so you recognise when to follow it - so keep genuinely always-on rules inline, never behind a pointer.
