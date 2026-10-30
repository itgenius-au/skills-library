# Phase 6: executed harness for a script that changes live host state

**A script that changes live host state gets an executed harness leg.** When the diff
includes an ops script that edits crontabs, sudo-owned files, systemd units, or another user's home
on a live host, static review is not enough. The test-adequacy agent (not an extra agent) also RUNS
the script's real stages on a
disposable Linux host that simulates the target: the happy path, rollback, an abort midway then
rollback, a re-run after an interruption, every guard, and injected read failures. Simulate the
target for real (its users, cron, sudo, flock, file modes); stub only external services (the CLI
the script drives, your git host, cloud APIs, SaaS APIs). Choose the host in this order:
1. An ephemeral spot / preemptible cloud VM in a sandbox project of your own (for example on
   GCE: `--provisioning-model=SPOT`, `--max-run-duration=2h` and
   `--instance-termination-action=DELETE`), so it deletes itself even if the session dies.
   Delete it when the panel ends and confirm it is gone.
2. A CI runner (a manually triggered workflow in a scratch repo).
3. Local Docker, only when the operator agrees.

Never the operator's laptop by default, and never the production host. Execution finds what
reading cannot (a rollback-then-retry deadlock, a non-atomic backup, a gate that passes on a
failed read), so re-run the harness after each fix.
