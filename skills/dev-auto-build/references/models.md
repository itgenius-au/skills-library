# Models and effort by role

This is the one place where `dev-auto-build` names a model tier or an effort setting. SKILL.md names
roles only (the one command line in Phase 1 passes the build effort as a flag). Change a default here, not in
the prose. Do not hard-code a model version: set the exact model in your agent or CLI configuration.

| Role | Default | Notes |
|---|---|---|
| Orchestration and gate-running | The fast, cheaper tier of your Claude models | Reads diffs, re-runs the gates, writes the runbook. It does not build. |
| Build agent (Phase 1 builds and fix-runs) | Codex CLI through the `review-with-codex` wrapper, `--effort high`, `--timeout 3600` | Build tier, not review tier. |
| Build agent, high-risk work | The same agent at `xhigh` effort | Only for security, authz, migration or architectural tasks, and only when the plan and invocation authorise that work. |
| Review panel (Phase 3) | Whatever `review-swarm` dispatches | Four independent models. `review-swarm` holds its own reviewer settings. |
| Token ceiling | About 200k per plan | A breach is a hard stop: report progress and what remains. |
