# Gate lines

Declare a repository's gates on one line in `.claude/CLAUDE.md`:

``Test: `uv run pytest` | Lint: `uv run ruff check .` | Typecheck: `uv run mypy .` ``

To check the format in a scratch repository, use this harmless line (in a real repository it would hide the real gates, because the first matching line wins):

``Test: `true` | Lint: `true` | Typecheck: `true` ``

Put the gate line before any `Run:`, `Build:`, `Deploy:`, or `Format:` line. The first matching line wins. Those labels are not gates, and a `Run:` line above the gate line hides the gates from discovery.

Opt a repository out by putting this at the start of a line:

`Health sweep: skip - <reason>`

Do not add a bullet or bold formatting to the opt-out line.

Choose the discovery root in this order:

1. Pass `--root <dir>`.
2. Set `root` (an absolute path; `~` is not expanded) in `~/.claude/repo-health-sweep.config.json`. Copy `templates/repo-health-sweep.config.example.json` there and edit it. Set `REPO_HEALTH_SWEEP_CONFIG_DIR` to read the config from a different folder.
3. If neither provides a root, the script exits 2 and says so.

Keep repositories at depth 1 or 2 below the root. Skip dot-directories and `node_modules`. Accept `.git` as either a directory or a gitfile.
