# Phase 3: one pass for a small change

In this file, "the four questions above" means the four questions of the plan review in SKILL.md, Phase 3, first bullet.

- **One pass for a small change.** When the change is text only or small (about
  100 lines or fewer) and touches no authz, migration, secrets, or production or customer
  data write, you may run ONE combined review after Phase 5 instead of this plan review
  plus the Phase 6 panel: commit a checkpoint, then run `review-with-codex`'s
  `snapshot-review.sh` on it with `--effort high --timeout 600` (a plain copy plus a
  merge-base diff; see that skill and `models.md`). Give
  it the runbook's "Ask (verbatim)", the four questions above (and the budget question for a
  cost-saving build), and the Phase 6 test-adequacy question. Record "one pass" and the reason in
  the runbook Build log; Phase 6 is then done. The rule is one review pass sized to the risk.
  **Not for code that hides or checks sensitive data**, whatever its size: redaction,
  scrubbing, escaping, or a leak or secret check. Its defects are inputs it misses, so run the
  plan review and the full Phase 6 panel, and give the correctness agent an adversarial-input
  brief (unusual spacing, case, Markdown wrappers, a value inside another value, every format
  the ask names). A small helper of this kind that gets one review pass tends to draw a newly
  missed format on every later review.
