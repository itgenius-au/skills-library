# Phase 6: running the panel with the Agent tool

**A fresh `isolation: "worktree"` branches from `origin/<default-branch>` by default** - it does NOT
contain your feature branch's committed changes, so an agent given that isolation would silently
review main instead of your diff. So the DEFAULT is: checkpoint-commit, then run each agent in its
own detached snapshot of that commit (`git worktree add --detach .claude/worktrees/review-<slug>-<agent>
<checkpoint>`), with its FIRST action `EnterWorktree(path=<its snapshot>)`, never in the build
worktree. A subagent starts in your working directory, and a prose "read-only" does not stop an
agent that has a shell: read-only agents have been seen to check out another branch in the
build worktree, or to commit, push and open a PR (full rule: `review-swarm`, "Give the legs a
snapshot"). The same rule covers every investigation agent this skill dispatches (recon, an
impact map, a live-state read): a snapshot or a tool list with no Bash, Edit or Write, never the
build worktree. After ANY panel or investigation agent returns, run the `review-swarm`
**post-panel check** (branch, reflog and status here; each snapshot's reflog; a remote-branch
diff against the pre-panel baseline; `gh pr list --author @me --state all` and a cross-repo
`gh search prs --author @me`). An unexpected commit, push or PR is
out-of-process work: review it before you keep it, and never merge it on the agent's word.

**When a workflow-orchestration tool is not available.** Such a tool may run only after the
user opts in to multi-agent orchestration, so a quick build often cannot call it. Do not skip
Phase 6. Run the same panel with the Agent tool instead:

1. Checkpoint-commit the diff first.
2. Launch one background Agent per dimension, in the same message, so they run in parallel.
3. Bind each agent to its own snapshot from above (first action: `EnterWorktree(path=<snapshot>)`),
   never the build worktree. Tell it it must not commit, push, open a PR, or touch a production
   system. To probe behaviour, it copies the repo first (`cp -R <repo> "$(mktemp -d)/copy"`) and
   mutates only the copy. A mutation it
   leaves behind in the copy cannot reach your branch or an auto-commit. It also runs every
   probe with `HOME` set to a sandbox dir, and it never sources or line-extracts an installer or
   config script (for example a hook installer) outside that script's own test harness. A copied
   line range from a file that has since shifted can hold the real side-effect code, which then
   writes the live user config (for example, hook config merged into a live settings file). While a panel runs, a cheap
   guard is a background watcher on the live config file's hash.
4. Give the test-adequacy agent a mutation brief: delete or invert each guard in the copy. For
   every guard whose removal no test catches, report whether THE ASK needs that guard: if yes, it
   is a missing test (a defect); if no, it is a `simplify` finding to delete the guard, not a test
   to add. Also have it force one suite to fail, and
   check that the test runner exits non-zero and names that suite. **Run the unmutated control
   first, and count no kill unless it passes:** a harness that fails for its own reason kills every
   mutation. Changing `HOME` for the run hides the user's site-packages, so keep them on
   `PYTHONPATH` (`python3 -c "import site; print(site.getusersitepackages())"`). For example,
   a mutation re-run can print every mutation KILLED while its control failed with "No module named
   pytest"; only the control proves the result.
   **When the change deletes or writes data** (branches, records, files, money), the mutation
   result must come from an EXECUTED run, never from reading the code. A Codex leg in its
   read-only sandbox cannot create the copies, so its table comes back all `BLOCKED`; that is
   no result. Run the mutation script yourself, or give Codex `--sandbox workspace-write` with
   `-C` set to a scratch copy only, and run any long harness outside Codex's 600 s cap. Then
   spot-check the two most important gates yourself: remove each in a copy and confirm a test
   fails. A static pass that reads as all
   `BLOCKED` can hide safety checks that no test covers; only the executed run shows them.
   Traps when reviewing an ops run-wrapper script, a guard or a detector:
   - **Prove a new test against the previous commit's code.** Copy the old file into scratch
     (`git show <prev>:<path> > <scratch>/<path>`), run the new tests with `PYTHONPATH=<scratch>`, and
     expect red. A control made by deleting text from the script is invalid when it removes a string
     the test searches for: the test then fails for the wrong reason.
   - **A refusal test must check the guard's OWN message** and that the child never ran (a marker
     file), not only the exit code. When a later check refuses the same case, deleting the guard
     still gives a refusal, so an exit-code-only test stays green (a fake green). Pin the message, or record the redundancy as intentional.
   - **A mutant that does not compile is not a kill.** Run `python3 -m py_compile` on each mutated
     file first. Count a kill only when the run fails in the named test (pytest exit 1). Pytest
     exit 2 is a collection or syntax error: fix the mutant and run it again.
   - **Leave out tests that depend on the repo path** (`-k 'not <name>'`). A test that checks a file
     next to the source fails in every mutant copy in scratch and gives a false kill for each
     mutant. After any refactor, check that each mutant's anchor text still matches the source: a
     mutant whose anchor no longer matches changes nothing.
   - **Review the fix diff, not only the first diff.** Tightening a detector pattern to fix a false
     positive can drop real variants. Keep a replay of real inputs plus negative controls for each
     changed pattern. A new guard on shell command text must also let your own commit and PR commands
     through (for example a heredoc inside `$(...)`).
5. Treat an evidenced mutation result as self-verifying (it already shows a test that stays
   green). Send a critical or high finding without that evidence to ONE skeptic agent before you
   adopt it; a medium or lower finding gets no skeptic and follows the must-fix rule.
6. After the agents return, run the post-panel check above, then remove the snapshots
   (`git worktree remove --force <snapshot>`).

If the agents cannot bind to their snapshots (their shells lock after `EnterWorktree`; see
`review-swarm`, "If a leg cannot bind to its snapshot"), do not retry the bind. Launch the Phase 6
agents WITHOUT `EnterWorktree`, under hard rules in the prompt: read-only on the build worktree, all
probes and mutations only in `/tmp` copies, never commit, push, open a PR, or touch production.
Checkpoint-commit first and record the remote-ref baseline, then run the post-panel check when they
return. Give each agent its OWN plain copy of the checkpoint (`git archive <checkpoint> | tar -x -C
/tmp/<run>/<agent>`, not a git worktree), and have it run commands through a `/tmp` script that
`cd`s into that copy. After the panel, `git diff <checkpoint> --stat -- src tests` on the build
tree must be empty.
Give each copy its OWN virtualenv too (`uv venv` + `uv sync`, or a full copy of `.venv`), never a
symlink to the build worktree's `.venv`. Running `uv run` in the copy re-syncs the editable install
and rewrites the SHARED `site-packages/_editable_impl_<package>.pth` to the copy's `src`. The build
tree's own interpreter then imports scratch code (gates, other agents, live read-only runs). After
the panel, check that the `.pth` still names the build worktree's `src` (a mutation
agent has caused this before; checksum the file to catch it).
