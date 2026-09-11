---
name: machine-move
description: "Pre-flight check OR new-machine setup. Audits git sync, local state, and portability across all repos. Triggers on: machine move, move computer, switch machine, pre-flight check, sync check, portability check, new computer, setup machine, receiving machine"
---

# Machine Move

Two modes:

1. **Sending** (pre-flight audit) - run on the OLD machine before moving. Checks for uncommitted/unpushed work and local-only state.
2. **Receiving** (new machine setup) - run on the NEW machine after cloning the repo. Runs setup scripts, pulls all repos, verifies environment.

## Mode Detection

Ask the user which mode if ambiguous. Otherwise infer:
- "pre-flight", "before move", "check sync" -> **Sending**
- "new computer", "just set up", "receiving", "just opened here" -> **Receiving**
- "machine move" with no qualifier -> Ask

---

# SENDING MODE - Pre-Flight Audit

Run this before switching to a new machine to ensure nothing is left behind. Checks all repos for uncommitted/unpushed work, then audits local-only state.

## Phase 1: Git Sync Audit

Check every repo for uncommitted work, stashes, local branches, and unpushed commits.

### Repos to check

Parent + all child directories. Adapt this list to your `setup-subprojects.sh`:

```
# CONFIGURE: List your child project directories
REPOS="child-project-1 child-project-2 child-project-3"
```

### For each repo, run these checks

From the parent directory:

```bash
PARENT_DIR="$(pwd)"

# Parent repo
echo "=== $(basename "$PARENT_DIR") (parent) ==="
git fetch --quiet 2>&1
git status -s                                    # Uncommitted changes
git stash list                                   # Stashed work
(git branch -vv | grep -v '\[origin/' || true)   # Local-only branches
git log --all --not --remotes --oneline          # Unpushed commits on ANY branch

# Each child repo
for dir in $REPOS; do
  if [ -d "$dir/.git" ]; then
    echo "=== $dir ==="
    cd "$dir"
    git fetch --quiet 2>&1
    git status -s
    git stash list
    (git branch -vv | grep -v '\[origin/' || true)
    git log --all --not --remotes --oneline
    cd "$PARENT_DIR"
  else
    echo "=== $dir === MISSING (not cloned)"
  fi
done
```

### Output format

Present results as a summary table:

| Repo | Uncommitted | Stashes | Local Branches | Unpushed |
|---|---|---|---|---|
| parent | clean | 0 | none | 0 |
| child-1 | clean | 0 | none | 0 |
| ... | ... | ... | ... | ... |

Flag any non-clean rows clearly.

## Phase 2: Local State & Portability Audit

Check for local-only files and config that wouldn't survive a machine move.

### 2a. Memory symlinks and topic file portability

Verify ALL files in the Claude Code auto-memory directory are symlinks pointing to git-tracked repo files. Plain files in the auto-memory directory are NOT portable - they'll be lost on machine move.

```bash
# Find your auto-memory directory
# Cache key = absolute repo path with / replaced by - and prefixed with -
REPO_PATH="$(pwd)"
CACHE_KEY="-$(echo "$REPO_PATH" | sed 's|^/||; s|/|-|g')"
AUTOMEM="$HOME/.claude/projects/$CACHE_KEY/memory"

echo "=== Auto-memory directory ==="
ls -la "$AUTOMEM/"

echo ""
echo "=== Checking each file ==="
for f in "$AUTOMEM"/*; do
  name=$(basename "$f")
  [[ "$name" == ".DS_Store" ]] && continue
  if [ -L "$f" ]; then
    target=$(readlink "$f")
    if [ -f "$target" ]; then
      echo "OK: $name -> $target"
    else
      echo "BROKEN: $name -> $target (dangling symlink)"
    fi
  elif [ -f "$f" ]; then
    echo "LOOSE: $name (plain file - NOT portable! Move to repo memory/ and symlink)"
  fi
done
```

**Fix for loose files**: Move the file into the repo's `memory/` directory, replace with symlink:
```bash
mv "$AUTOMEM/loose-file.md" "$(pwd)/memory/"
ln -s "$(pwd)/memory/loose-file.md" "$AUTOMEM/loose-file.md"
git add memory/loose-file.md
```

### Memory Maintenance Philosophy

The auto-memory system loads `MEMORY.md` into every conversation. To keep context budgets lean:

1. **MEMORY.md = guardrails + pointers** (~80 lines max). Only keep: identity, preferences, critical guardrails that prevent mistakes, and 1-line pointers to topic files. No lookup data.
2. **Topic files = reference data** (in repo `memory/`). Account IDs, API patterns, credential locations, project-specific conventions. Read on-demand when relevant.
3. **Child project memory** (in `{child}/memory/`). ALL project-specific knowledge lives in the child. Parent MEMORY.md should never duplicate child memory.
4. **Auto-memory dir = symlinks only**. Every file must symlink to a git-tracked file. No plain files, no backups, no loose state.
5. **Periodic audit**: Run `ls -la` on the auto-memory dir after any session that creates new topic files. Check for plain files that need symlinking.

### When to Store Inline vs. Link to Reference

**Store inline in MEMORY.md** (loaded every conversation):
- Identity, personality, communication preferences - used in every interaction
- Critical guardrails that prevent mistakes
- The single most-used ID per service if frequently referenced
- 1-line pointers to topic files with the keyword that triggers reading them

**Store in topic files** (read on-demand via pointer):
- Full account ID lists, credential inventories, secret names
- API patterns, curl examples, endpoint tables
- Project-specific conventions, gotchas, and lessons learned
- Anything only relevant when actively working in that domain

**Store in child project memory** (only loaded when working in that directory):
- ALL project-specific knowledge: architecture, deployment, infra details
- Project-specific credentials and API access
- Lessons learned from working in that project

**The test**: Before adding something to MEMORY.md, ask: "Will this prevent a mistake or save a tool call in >50% of conversations?" If no, it belongs in a topic file or child project memory.

**Duplication rule**: Information should exist in exactly one canonical location. MEMORY.md can contain a guardrail summary + pointer, but never a full copy of what's in a topic or child file.

### 2b. Claude credentials

```bash
[ -f ~/.claude/.credentials.json ] && echo "Claude credentials: OK" || echo "Claude credentials: MISSING (will re-auth on launch)"
```

### 2c. Cloud provider authentication

```bash
# Example for gcloud - adapt to your provider
gcloud auth list 2>/dev/null

# Check Application Default Credentials
[ -f ~/.config/gcloud/application_default_credentials.json ] && echo "ADC: OK" || echo "ADC: MISSING"
```

### 2d. MCP wrapper scripts

Check all wrapper scripts created by your `setup-mcp.sh`:

```bash
# CONFIGURE: List your wrapper scripts
WRAPPERS="gsm-env"
for w in $WRAPPERS; do
  [ -x ~/.local/bin/$w ] && echo "OK: $w" || echo "MISSING: $w"
done
```

Fix: `./scripts/setup-mcp.sh`

### 2e. Claude Code settings

```bash
[ -f ~/.claude/settings.json ] && echo "settings.json: OK" || echo "settings.json: MISSING"
```

This file may contain absolute paths (MCP registrations). Check for hardcoded paths:

```bash
grep -c "$HOME" ~/.claude/settings.json 2>/dev/null && echo "(paths reference current home dir)"
```

## Phase 3: Summary & Actions

### If everything is clean

Report: "All repos synced. Local state is portable. Safe to move."

Print the new machine setup commands:
```
# On new machine, after cloning the repo:
./scripts/setup-memory.sh         # Create memory symlinks
./scripts/setup-mcp.sh            # Install MCP servers + wrappers
cp config-backup/global/settings.json ~/.claude/settings.json
```

### If issues found

List each issue with:
1. What's wrong (e.g., "child-project-2 has 2 uncommitted files")
2. The fix action (e.g., "commit and push")

**Offer to fix git issues** (commit + push dirty repos) but always ask for approval first - these are irreversible actions.

---

# RECEIVING MODE - New Machine Setup

Run this on the NEW machine after cloning the repo. Runs setup scripts, pulls everything to latest, verifies the environment is fully functional.

## Step 1: Check Prerequisites

Verify required tools are installed:

```bash
echo "=== Prerequisites ==="
for cmd in node npm npx python3 gcloud claude git gh; do
  if command -v "$cmd" &>/dev/null; then
    echo "OK: $cmd ($(command -v $cmd))"
  else
    echo "MISSING: $cmd"
  fi
done
```

If critical tools are missing:
```bash
# macOS (Homebrew):
brew install node python pipx uv gh
brew install --cask google-cloud-sdk
npm install -g @anthropic-ai/claude-code
```

Do NOT proceed with setup scripts until prerequisites are met.

## Step 2: Cloud Provider Authentication

Check auth state and guide through login if needed:

```bash
# CONFIGURE: Your cloud auth commands
gcloud auth list 2>/dev/null
```

## Step 3: Run Setup Scripts

Run your setup scripts in order. Each is idempotent.

```bash
./scripts/setup-subprojects.sh    # Clone/pull child repos (if applicable)
./scripts/setup-memory.sh         # Create MEMORY.md symlinks
./scripts/setup-mcp.sh            # Install MCP + register servers
```

## Step 4: Restore Global Settings

```bash
cp config-backup/global/settings.json ~/.claude/settings.json
```

## Step 5: Verify Environment

Run the same Phase 2 checks from Sending mode to confirm everything works.

Present as a checklist:

| Check | Status | Action Needed |
|---|---|---|
| Memory symlinks | OK / MISSING | `./scripts/setup-memory.sh` |
| Claude credentials | OK / MISSING | Will auth on first launch |
| Cloud auth | OK / MISSING | Provider login command |
| MCP wrappers | OK / N MISSING | `./scripts/setup-mcp.sh` |
| settings.json | OK / MISSING | `cp config-backup/global/settings.json ~/.claude/` |

## Step 6: Summary

### If everything passed

Report: "New machine fully set up. All repos cloned and up to date. MCP servers registered. Restart Claude Code to load MCP servers."

Remind about first-use OAuth flows:
```
# These will trigger OAuth in browser on first use:
# - google-drive, google-workspace, wordpress, etc.
# - Any MCP server that uses browser-based OAuth
```

### If issues remain

List each with the fix action. Offer to re-run specific setup scripts if needed.
