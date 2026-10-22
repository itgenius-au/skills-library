# Memory cleanup - the method

The step-by-step pass the `memory` mode runs. It enforces the conventions in [memory-conventions.md](memory-conventions.md); read those first if you have not. The goal: future sessions orient quickly without re-asking what is already known, and the index stays cheap to load on every turn.

Contents:
- [Phase 1 - Take stock](#phase-1---take-stock)
- [Phase 1b - Relevance check (large stores)](#phase-1b---relevance-check-large-stores)
- [Phase 2 - Consolidate](#phase-2---consolidate)
- [Phase 3 - Verify layout](#phase-3---verify-layout)
- [Phase 4 - Tidy the index](#phase-4---tidy-the-index)
- [Phase 5 - Report](#phase-5---report)
- [Concurrent sessions](#concurrent-sessions-the-shared-store)
- [What NOT to touch](#what-not-to-touch)

## Phase 1 - Take stock

Locate the store (`ls -d ~/.claude/projects/*/memory 2>/dev/null`), then run the discovery sweep. Set `AM` to the auto-memory dir; set `REPO` to the version-controlled `memory/` dir only if you use the symlink layout.

```bash
AM=~/.claude/projects/<slug>/memory      # the auto-memory dir Claude Code loads

# Index size - the real constraint, since MEMORY.md loads every turn.
wc -c "$AM/MEMORY.md"

# Every index entry must resolve to a readable file.
grep -oE '\]\(([^)]+\.md)\)' "$AM/MEMORY.md" | sed -E 's/\]\((.*)\)/\1/' | while read -r f; do
  [[ -e "$AM/$f" ]] || echo "BROKEN INDEX LINK: $f"
done

# UNINDEXED FILE - the reverse check, for the plain (non-symlinked) layout: a topic
# file sitting in the memory dir that no index line, and no bundle sub-index line,
# points to. Starts at MEMORY.md and follows "](file.md)" links outward, one hop at
# a time, into whatever they point to - so a file reached only through a bundle
# sub-index still counts as indexed. Topic files use "[[name]]" wiki-links for their
# own cross-references (see memory-conventions.md), not "](file.md)", so this pattern
# only picks up real index and bundle entries, not ordinary topic-to-topic mentions.
# Only scans the top level of the memory dir, so anything you already moved into an
# archive/ subdir during Phase 2 is out of scope and never flagged.
{
  reached=$(mktemp); frontier=$(mktemp); next=$(mktemp)
  echo "MEMORY.md" > "$reached"; echo "MEMORY.md" > "$frontier"
  while [ -s "$frontier" ]; do
    : > "$next"
    while IFS= read -r f; do
      [ -e "$AM/$f" ] || continue
      grep -ohE '\]\([^)]+\.md\)' "$AM/$f" 2>/dev/null \
        | sed -E 's/\]\((.*)\)/\1/' | xargs -n1 basename 2>/dev/null \
        | while IFS= read -r l; do
            grep -qxF "$l" "$reached" || { echo "$l" >> "$reached"; echo "$l" >> "$next"; }
          done
    done < "$frontier"
    cp "$next" "$frontier"
  done
  find "$AM" -maxdepth 1 -type f -name '*.md' ! -name MEMORY.md | while IFS= read -r f; do
    n=$(basename "$f")
    grep -qxF "$n" "$reached" || echo "UNINDEXED FILE: $n"
  done
  rm -f "$reached" "$frontier" "$next"
}
```

For each `UNINDEXED FILE` hit, decide in Phase 2: add a one-line index or bundle entry if the fact is still current and worth recalling, merge its content into a file that is already indexed, or retire it (propose the retirement in the report first, same as any other retirement - never drop it silently just because it was unreachable).

If you use the **version-controlled + symlink layout**, also run both orphan checks (set `REPO` to the repo `memory/` dir):

```bash
# REVERSE orphan - a real file (not a symlink) in the auto-memory dir. Won't sync between machines.
find "$AM" -maxdepth 1 -type f -name '*.md' ! -name MEMORY.md

# FORWARD orphan - a real file in the repo with NO symlink (or a wrong-target one) in the auto-memory
# dir. These silently fail to load in new sessions - the easiest rot to miss, because nothing errors.
for f in "$REPO"/*.md; do
  [[ -e "$f" ]] || continue; n=$(basename "$f"); [[ "$n" == MEMORY.md ]] && continue
  if [[ ! -L "$AM/$n" ]]; then echo "NO SYMLINK: $n"
  elif [[ "$(readlink "$AM/$n")" != "$f" ]]; then echo "WRONG TARGET: $n -> $(readlink "$AM/$n")"; fi
done
```

Then read `MEMORY.md` and skim each topic file. Note overlaps, stale dates, thin entries, and any `feedback_`/`project_` file missing its `**Why:**` / `**How to apply:**` structure.

**Flag buried decision-rules.** If an on-demand reference doc contains a *behavioral rule* ("use tool X, not Y", "always/never do Z") that a session needs at decision time, it must have a short **always-loaded trigger line in the index** - the full how-to can stay in the reference doc, but the *rule* cannot only live behind an on-demand file, or a session will act before it ever reads it. This is a whole class of silent failure: the knowledge exists, but never reaches the moment it is needed.

## Phase 1b - Relevance check (large stores)

Phase 1 finds structural rot; this finds *stale* entries. For a big store (~100+ entries), or when the user asks "which of these are still useful", go entry by entry instead of skimming. For each one, classify it (durable guardrail, dated project, reference, user profile), then check the claim it makes against the live source: does the file, flag, service, or deadline it names still exist? Sort the results into KEEP / TRIM / RETIRE-CANDIDATE and feed them into Phase 2 and Phase 4. If you have a searchable log of past sessions you may also count recent mentions of an entry's distinctive keywords, but treat the count as a hint only.

The core principle: **low recent relevance is not a reason to retire.** Rarely-fired guardrails (security rules, never-delete rules, "don't fabricate" rules) are load-bearing precisely *because* they fire rarely - zero hits, still a KEEP. Retirement needs low relevance PAIRED WITH staleness or supersession, and it targets dated project logs and duplicates, not quiet safety nets. A "superseded by X" verdict is a hypothesis: read both files before acting, because a real fraction turn out to be an update or a merge, not a delete. And before retiring a dated entry, confirm its premise is actually closed: a warning that says "do not trust X until bug Y is fixed" stays until you have checked that Y is fixed.

## Phase 2 - Consolidate

**Separate the durable from the dated.** Working style, relationships, recurring conventions, and operational guardrails are durable - keep and sharpen. Specific projects, deadlines, and one-off incidents are dated - once the date has passed or the work is done, retire the file or fold the lasting takeaway into a durable one (an incident becomes a `feedback_` rule).

**Merge overlaps.** Two files describing the same project or preference become one. Fold the unique nuance from the weaker file into the survivor (keep the richer file's path), retire the weaker one, and **update the survivor's index hook so it carries the merged concept** - otherwise the merged-away entry's trigger is silently lost.

**Compress in place** when a file is mostly stale but holds one live item. A long reference (say, a paused project's full inventory) that still carries a standing action (a key to rotate, an open todo) does not have to go: rewrite it down to the live items plus a one-line "full detail in git history", and keep the now-short file.

**Relocate project- or person-specific knowledge to where it belongs.** If a memory is really one project's operational knowledge (architecture, infra, a project gotcha) or anything personal and sensitive (finances, legal, private entities), move it OUT of a shared/general store: write the content to that project's own docs (or a private store), leave a pointer, then drop the index line and the file. For content that is mostly project-specific but carries a few genuinely cross-cutting facts (an account id, an auth pattern), leave a **slim stub** with just those plus a pointer.

**Retire means archive or relocate, never silent-delete.** A retired entry has two homes: (a) relocate it to the project's docs when that project's future sessions need the knowledge; (b) archive it (e.g. move it to an `archive/` dir under version control) for completed project logs and superseded duplicates whose only value is the record. Either way the mechanics are the same: move the file (do not `rm` it), remove its auto-memory symlink if any, and drop its index line. Git history is the backup, so archiving inside one repo in one commit beats scattering deletes.

**Fix time references.** Convert "next week" / "this quarter" / "by Friday" to absolute dates. Anchor on today's date from the system prompt.

**Drop what is easy to re-find.** If a memory restates something derivable from the codebase, `git log`, a secret manager, an API, or an active CLAUDE.md, cut it. Keep what is hard to re-derive: stated preferences, the *why* behind a decision, who to go to, gotchas earned the hard way.

**Enforce body structure on `feedback_` and `project_` files.** They lead with the rule/fact, then a `**Why:**` line and a `**How to apply:**` line. Add the structure where missing - knowing the *why* lets future sessions judge edge cases instead of following blindly. Re-list any stragglers:

```bash
for f in "$REPO"/{feedback,project}_*.md; do grep -LE '^\*\*Why(:\*\*|\*\*:)' "$f"; done
```

**Verify before deletion.** Before removing any memory that names a specific file, function, flag, or secret, confirm the named thing still exists (or does not). A memory that says "X exists" is a claim, not ground truth.

**Verify before you enshrine, not just before you delete.** When consolidating or writing new content (especially anything a subagent generated), spot-check the named ids, secrets, and files against source before committing. A consolidated doc full of plausible-looking ids is worthless if one is invented.

## Phase 3 - Verify layout

For every entry in `MEMORY.md`, confirm the file it points to exists and is readable (the broken-link check in Phase 1).

If you use the **version-controlled + symlink layout**, verify both directions:

1. The auto-memory path is a symlink.
2. Its target exists in the repo `memory/` dir.
3. The real file is tracked in git (`git ls-files`).
4. Every real file in the repo has a correct symlink in the auto-memory dir (the forward-orphan sweep from Phase 1).

Common fixes: a symlink pointing at a moved file, relink it (to an **absolute** target); a real file deleted but symlink + index line remain, drop both; a reverse orphan, move it into the repo then relink. If you keep a relink script that rebuilds every symlink to its absolute target, running it is the one-shot fix for almost all of these.

## Phase 4 - Tidy the index

Keep `MEMORY.md` under its size budget (tens of KB; `wc -c` it). Past the harness limit it **truncates** and tail entries silently stop loading, so the constraint is **200 lines OR the byte budget (tens of KB), whichever comes first** - watch both. The usual cause of going over is not too many entries but **fat entries** that grew into mini-essays duplicating the topic file. One line per entry: `- [Title](file.md) - one-line hook`.

**The budget lever is the index lines, not the topic files.** The index loads every turn; topic files load on demand. Trimming a fat *topic file* helps recall quality but frees no index budget - only shortening or removing *index lines* does.

- **Trim fat index lines to one-line hooks. This is the primary, non-destructive lever** - the detail already lives in the topic file. Reach for it before retiring real memories.
- **If the store has outgrown a flat index, tier it** rather than only trimming (see [memory-conventions.md](memory-conventions.md) "tiering"): move domain facts into per-domain bundle sub-indexes reached by a "scan before X" pointer, so the index stops scaling with the store. New domain facts then go to the bundle, not the index. Don't "fix" a tiered store back to a flat one.
- Remove pointers to retired memories.
- Add anything newly important.
- Keep semantic (topical) order, not chronological.

## Phase 5 - Report

Finish with a short summary:

```
Files touched: N
- Merged: A -> B (reason)
- Retired: X (archived/relocated, reason)
- Rehomed orphan: Y
- Unindexed: F (indexed / merged into B / retired, reason)
- Restructured: Z (added Why / How-to-apply)
- Index: was N lines / NK chars -> now M lines / MK chars
```

Then, if the store is version-controlled, offer to commit and push so the cleanup is durable.

## Concurrent sessions (the shared store)

If other sessions share this store and write to it (auto-memory writes, plus any auto-commit hook), a cleanup pass is the classic collision case. Guard against clobbering their in-flight writes:

- **Edit the index with a pass-through script, not a full rewrite.** Read the file, transform only the lines whose `](filename.md)` token matches a key you intend to change or drop, and emit every other line verbatim. A concurrent session's newly-added line - one you never saw - passes straight through. A full-file rewrite silently clobbers it.
- **Sanity-check the entry count after an index edit.** If you removed 6 and the count dropped by only 5, a concurrent session probably added one and your pass-through correctly kept it. Confirm (grep for the new line) before worrying.
- **When committing on a shared branch, squash only your own commits.** Other sessions' real commits can land between yours; never sweep a foreign commit into your squash. Reset back only to the first commit that is yours.
- **On a push reject, check overlap against the common base, not `HEAD..origin`.** `git diff --name-only HEAD..origin/main` lists your own files as false overlap. The real question is what the *remote* commit touched: `git diff --name-only $(git merge-base HEAD origin/main) origin/main`. If it does not touch your files, a rebase is clean.
- **Never `git reset --hard` while another session has uncommitted work in a shared tree** - it destroys their in-flight writes. Check `git status` and liveness first.
- Heavy cleanups go smoothest when no other session is writing. If collisions keep happening, say so and offer to pause until the other session wraps.

## What NOT to touch

- Code patterns, file paths, architecture facts - those belong in CLAUDE.md or the code, not memory.
- Anything already in an active CLAUDE.md - duplication wastes context budget.
- Memories that look stale but cite an active project - verify status before retiring.
- A rarely-fired guardrail - low use is not staleness (see Phase 1b).
