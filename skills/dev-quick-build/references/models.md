# Models and effort by role

This is the one place where `dev-quick-build` names a model tier or an effort setting. SKILL.md and
the other references name roles only. Change a default here, not in the prose. Do not hard-code a
model version: set the exact model in your agent or CLI configuration.

| Role | Default | Notes |
|---|---|---|
| Gate runs (Phase 5 test-runner subagent) | The fast, cheaper tier of your Claude models | Returns a pass/fail digest. It never edits code. |
| Plan review (Phase 3) | `review-swarm` quick mode: all four legs, the Codex leg at `xhigh` effort | Each leg capped at 570 s; one round; a leg that has not returned is `unavailable`, with no retry. |
| One-pass review (Phase 3, small change) | `review-with-codex` `snapshot-review.sh` with `--effort high --timeout 600` | One combined review after Phase 5, in place of the plan review plus the Phase 6 panel. |
| Phase 6 finder and skeptic agents | The default model of your agent tool | 10 minutes each; one that has not returned is dropped, with no retry. |
