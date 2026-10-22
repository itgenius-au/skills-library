---
name: dev-update-env
description: "Audit and update the CLI tools, MCP servers, and system packages on a macOS or Linux dev machine. Detects what is installed (npm, uv, pipx, Homebrew, apt, dnf), compares installed vs latest versions, presents one summary table, and runs updates only after confirmation. Triggers on: update environment, update env, check updates, update tools, update mcps, update servers, upgrade everything, env audit, tool audit, version check."
argument-hint: "[optional: specific tool name to check/update]"
---

# Update Environment - CLI Tools, MCP Servers & Package Audit

Full environment audit and update workflow. It detects which tools and package managers exist on this machine, checks each for a newer version, presents one report, and runs updates after the user confirms. Works on macOS and Linux. Nothing is assumed to be installed: a missing tool is skipped, not treated as an error.

If an argument names one tool, audit and update only that tool.

## Phase 0: Detect the platform

Run this first. Every later phase branches on the result.

```bash
uname -s                                  # Darwin = macOS, Linux = Linux
for c in brew apt-get dnf pacman npm pnpm yarn uv pipx pip3 pyenv nvm; do
  command -v "$c" >/dev/null 2>&1 && echo "have: $c"
done
```

- **System package manager**: `brew` (macOS, and Linuxbrew), else `apt-get` (Debian/Ubuntu), else `dnf` (Fedora/RHEL), else `pacman` (Arch). Use the first one found. If none is found, skip the system-package section and say so in the report.
- **Language-level managers**: `npm` for global Node CLIs, `uv` or `pipx` for Python CLIs. Skip any that are missing.
- Do not install a missing package manager. Report it as "not installed" and move on.

## Phase 1: Audit (read-only, run the checks in parallel)

Every command in this phase only reads state. Capture each result for the report. Redirect stderr to `/dev/null` so a missing tool produces no noise, and treat empty output as "not installed".

### Core CLI tools

For each tool below, run its version command only if the tool is on `PATH` (`command -v <tool>`). Then look up the latest version where a registry makes that possible.

| Tool | Installed version | Latest version |
|---|---|---|
| Claude Code | `claude --version` | `npm view @anthropic-ai/claude-code version` |
| Node.js | `node --version` | informational (managed by a version manager or the system package manager) |
| npm | `npm --version` | informational |
| Python 3 | `python3 --version` | informational |
| uv | `uv --version` | informational (`uv self update` updates it if it was installed by its own installer) |
| pipx | `pipx --version` | informational |
| Google Cloud CLI | `gcloud --version \| head -1` | informational |
| GitHub CLI | `gh --version \| head -1` | `gh release list -R cli/cli -L 1` |
| jq | `jq --version` | informational |
| OpenAI Codex CLI | `codex --version` | `npm view @openai/codex version` |
| Google Gemini CLI | `gemini --version` | `npm view @google/gemini-cli version` |

Add any other CLI the user names (the same pattern works: version command, plus a registry lookup if one exists). A tool that the user installed by hand and that has no registry entry is reported as "Unknown".

### Globally installed packages

```bash
npm ls -g --depth=0 2>/dev/null          # global npm packages
npm outdated -g 2>/dev/null              # which of them have a newer version
uv tool list 2>/dev/null                 # uv-managed Python tools
pipx list --short 2>/dev/null            # pipx-managed Python tools
```

For a uv or pipx tool, find the latest version with `pip index versions <pkg> 2>/dev/null` (or `uv pip index versions <pkg>`).

### MCP servers

Read the MCP server configuration to list every configured server. Look in these files, and skip any that do not exist:

- `~/.claude.json` (user and project scope)
- `~/.claude/settings.json`
- `.mcp.json` in the current project

You can also run `claude mcp list` to see the configured servers.

Categorize each server by how it is launched:

- **npx-based** (`command: npx`): "Auto-latest". It fetches the newest version on each run, so no action is needed. A pinned version (`pkg@1.2.3`) is the exception: report the pin and the latest version.
- **uv or uvx-based**: if installed with `uv tool`, compare against the latest like any uv tool. `uvx` runs fetch on demand.
- **pipx-based**: compare installed vs latest.
- **HTTP or SSE remote** (`url:` instead of `command:`): "Remote". The version lives on the server, so no local update is possible.
- **Local binary or script** at a fixed path: report "Unknown" unless you can read a version from it.

### System packages

Run only the one that matches the manager found in Phase 0:

```bash
brew outdated                                   # Homebrew (macOS or Linuxbrew)
apt list --upgradable 2>/dev/null               # Debian/Ubuntu (does not need sudo)
dnf check-update 2>/dev/null                    # Fedora/RHEL (exit code 100 means updates exist)
pacman -Qu 2>/dev/null                          # Arch
```

On Debian/Ubuntu, `apt list --upgradable` shows what a previous `apt-get update` already fetched. Refreshing the package index needs `sudo`, so offer it in Phase 3 instead of running it silently.

### Claude Code special note

Updating Claude Code replaces the program that is running this session. Flag it in the report, but never auto-update it. Handle it separately, with explicit confirmation.

## Phase 2: Report

Present a clean summary table:

| Tool | Installed | Latest | Status |
|------|-----------|--------|--------|

Status values:

- **Current**: installed matches latest.
- **OUTDATED**: an update is available (bold it).
- **Unknown**: the latest version cannot be determined.
- **Auto-latest**: npx-based, always fetches the latest.
- **Remote**: server-side, no local update.
- **Not installed**: not on this machine (list these at the end in one line, not as rows).

Group the results into three sections:

1. **Updates available (actionable)**: installed is older than latest. These are updated if the user confirms.
2. **Current (no action needed)**.
3. **Unknown / Remote / Auto-latest (informational)**.

Before the table, state the platform and which package managers you found, so the user can see what was and was not checked.

## Phase 3: Update (only after confirmation)

After the report, ask:

> "X items have updates available. Run all updates? (Claude Code updates need a session restart and are handled separately.)"

If the user confirms, run the updates grouped by package manager. Parallelize where it is safe.

```bash
# npm globals (batch into one command)
npm update -g <package1> <package2>

# uv tools (one per tool)
uv tool upgrade <pkg>

# pipx (one per tool)
pipx upgrade <pkg>

# Homebrew (batch)
brew upgrade <formula1> <formula2>

# Debian/Ubuntu (needs sudo: show the command and let the user run it, or confirm first)
sudo apt-get update && sudo apt-get install --only-upgrade <pkg1> <pkg2>

# Fedora/RHEL
sudo dnf upgrade <pkg1> <pkg2>

# Arch
sudo pacman -S <pkg1> <pkg2>
```

Rules for this phase:

- **Name the packages.** Upgrade only the packages in the confirmed list. Do not run a blanket `brew upgrade`, `apt-get upgrade`, or `dnf upgrade` with no package names unless the user asks for a full system upgrade.
- **`sudo` is the user's call.** If a command needs `sudo` and you cannot run it non-interactively, print the exact command for the user to run. Never try to work around a password prompt.
- **A global `npm` failure with `EACCES`** means npm's prefix is a system directory. Suggest a user-level prefix (`npm config set prefix ~/.npm-global`) instead of using `sudo npm`.
- **Claude Code** goes last and alone:
  > "Claude Code update available (X.X.X -> Y.Y.Y). This needs a session restart. Update now with `npm update -g @anthropic-ai/claude-code`?"
  If Claude Code was installed another way (its native installer, or a package manager), use that method's update command. Check how it was installed first (`command -v claude`, then look at the path).
- **After the updates**, re-check each updated tool's version, then show a short results table of what changed and what failed.

## Phase 4: Update recorded versions (optional)

After a successful update, check whether the project keeps a notes file or a doc that records tool versions (for example "requires Codex CLI v0.111+"). If it does, offer to update any stale version numbers to match what is now installed. Skip this phase if there is no such file. Never invent a file to hold versions.

## Important notes

- **Never update without showing the audit first.** Always present the full report and get confirmation.
- **Claude Code updates need a restart.** Flag them separately; the current session ends.
- **System package upgrades can be slow.** Offer to run them in the background if the user has other work.
- **Private or scoped packages** (a company MCP server, a private connector) may not be version-checkable on the public npm registry. Mark them "Unknown".
- **npx-based MCP servers** need no update. **Remote MCP servers** cannot be updated locally.
- **A stale MCP process holding a port**: find it with `lsof -ti:<port>` and show the process (`ps -p <pid> -o pid,command`) before offering to stop it. Stop it only after the user confirms.
- **After MCP server updates**, suggest restarting Claude Code so it picks up the new versions.
- **gcloud**: if outdated, `gcloud components update` may need `sudo`, and it does not work when gcloud came from a system package manager. In that case update it with that manager. Flag it; do not auto-run.
- **Node and Python**: these usually come from a version manager (nvm, fnm, pyenv, asdf) or the system package manager. Report the version, and do not update them directly. Say which manager owns them if you can tell.
- **Scope**: this skill reads package-manager state and runs upgrades the user confirmed. It does not edit shell profiles, change PATH, or install new tools.
