---
name: dev-qa-verify
description: "The verification-before-completion gate: prove a change works on the real surface before anything is called done. Runs an interactive browser pass (interact, do not just look) and triages any defect by severity - a build bug loops back to the build skill, a plan-level miss routes to dev-writing-plans, a wrong-concept finding routes to dev-brainstorming. Meant to be called as the closing verify phase of a build skill (e.g. dev-quick-build, dev-auto-build) and can also be run standalone against any finished change; it never deploys. Triggers on: qa verify, qa-verify, verify this, verification pass, browser verify, persona QA, did it actually work, verify before done, prove it works, is it really done."
---

# dev-qa-verify: Verify Before Complete

A single-purpose QA/verification skill. Its one job: prove a change actually works on the real surface, and route the work correctly when it does not. It is meant to run as the closing phase of a build pipeline (a quick, single-session build or a longer plan-driven build) and can also be invoked directly to verify any finished change.

> **Credit.** The core discipline here, "green gates are not proof a change works," is adapted from [`superpowers:verification-before-completion`](https://github.com/obra/superpowers) by **Jesse Vincent**, MIT licensed. This skill generalizes it into a browser-based verification pass plus a severity-triage router. Upstream is a reference only; this file is the source of truth for this repo. Full license text: [`../../THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).

## Entry rule: green is not done

A passing test suite, a green build, and a clean review prove the code compiles and does what its tests assert. They do NOT prove the change works for a real user on the real surface. CLI smokes pass while rendered pages are broken. **Nothing is "done" until it has been watched working on the real surface, or the pass is explicitly recorded OWED with the reason.** Do not report a change complete, and do not let a calling build skill close out, until this gate has run or been recorded OWED.

## What this skill is and is not

- **It verifies; it never deploys.** The calling build skill owns the deploy/merge decision and has already run its deploy or staged a push-ready branch BEFORE calling here. `dev-qa-verify` runs against whatever is now live: production if the caller deployed, the worktree / preview build otherwise.
- **It is a shared closing phase.** A quick single-session build and a longer plan-driven build can both hand off to it instead of carrying their own browser loop. It can also be invoked standalone on any finished change.
- **It decides where the work goes next** when it finds a defect - that routing (below) is the reason it is worth keeping as one skill rather than duplicating the logic in every build path.

## The verification pass

Use whatever interactive browser automation tool you have available (a browser-driving extension, an MCP browser tool, or equivalent) - the point is to drive the real UI, not to read code and assume it works.

1. **Establish the target.** Production when the caller deployed; the worktree / preview build otherwise. Confirm the URL before acting.
2. **Interact, do not just look.** Exercise every acceptance point of the change: click each new control, drive the flow a real user would, and check counts / orders / states against what the data implies - not against the label. A screenshot of a page that rendered is not verification; a control you clicked that did the right thing is.
3. **Capture evidence.** Screenshot each verified acceptance point. Note what you checked and what the data said it should be.
4. **Signed-out / SSO:** click the sign-in button, but do not act on a third-party identity provider's own login page (Google, Microsoft, etc.) - hand the account-pick to the user in one clear sentence, then continue once they confirm. **Never type credentials.**
5. **Record the result:** update the caller's runbook / deploy record persona-pass line from OWED to DONE with what was verified.

### OWED convention (no browser this session)

If no browser is connected (a scheduled / background run) or the target is signed out and the user is not present, **record the pass as OWED with the reason and continue** - do not block. An OWED pass does not trigger the loop below: there is nothing to loop on until a browser pass actually runs. Say so in the final summary and leave the single follow-up (the browser pass) named.

**Output style.** Write the final summary and any severity triage in the reader's active output style. If none is set, default to: lead with the answer, short sentences, plain words, no idiom.

### Reversible smoke-data rule

Verification MAY create and exercise real write paths, including test / smoke data, without an approval pause, when ALL hold:

- **Reversible and self-contained:** create, then remove, your own test artifacts, and confirm the removal landed. Never delete or overwrite pre-existing real data.
- **Toggling a real, pre-existing record's own control (a tick / status / flag field) is reversible too** - capture the field's exact prior value before changing it, verify the effect, then set it back and confirm the revert landed. "Never overwrite pre-existing real data" means never LEAVE someone else's data changed, not a ban on a captured-and-reverted toggle during your own verification pass.
- **Prefers staging / test-mode / test accounts.** On a production surface, only touch data invisible to real customers that sends no notification and triggers no downstream automation.
- **Emits nothing external:** no email / SMS / DM / chat to real people, no money movement, no publish to a public surface. These stay human-gated regardless of reversibility.
- **Audited:** log every created artifact and its cleanup in the runbook, and every toggled field with its prior value and confirmed revert. A failed cleanup or revert is a blocking finding, never silent residue.

## Severity triage: route the defect, do not just patch

A defect the browser pass surfaces is a real finding on the current surface (production, if the caller already deployed). Never ship past it or log it as a "known issue". Classify it, then route:

| Severity | What it means | Route to |
|---|---|---|
| **Minor (build bug)** | The concept is right and the plan is right; the implementation has a bug - a rendered break, a wrong count / order, a control that does nothing, an off-by-one. Fixable in place. | **Back to the calling build skill's own build loop** (e.g. `dev-quick-build` or `dev-auto-build`): reproduce with a failing test, fix to green (TDD), re-run gates, re-review the diff, re-ship, then re-verify here. |
| **Major (plan wrong)** | The implementation faithfully followed the plan, but verification shows the PLAN was wrong - a whole acceptance criterion is unmet by design, a slice is missing, a data-model / semantic assumption baked into the plan is false. Patching in the build loop would be lipstick. | **`dev-writing-plans`** - revise the plan, then re-enter the build. |
| **Concept wrong** | Verification (or the user seeing it live) shows the FEATURE itself is wrong - it solves the wrong problem, the UX concept is off, the approach is rejected on sight. | **`dev-brainstorming`** - re-design from the spec before any more building. |

Escalation ladder: **bug -> plan -> concept.** When unsure between two levels, take the higher one - a mis-scoped patch on a plan-level miss wastes a build cycle. A genuine product / design / trust decision is never settled inside a fix: escalate it to the user.

## Bounded loop (minor path only)

The minor / build-bug loop is **bounded: max 2 cycles.** If the defect survives 2 build-fix-verify cycles, STOP: if the caller deployed, roll back to the previous good revision (the rollback pointer in the deploy record), record the outstanding break in the runbook, and surface it to the user with what was tried and the suggested next step. Shipping a browser-broken page and walking away is never the outcome.

The major and concept-wrong paths are not loops here - they leave this skill and re-enter the pipeline upstream (`dev-writing-plans` / `dev-brainstorming`), which run their own gates before the work returns to a build skill and, eventually, back to this gate.

## Relationship to other skills

- A build skill (e.g. `dev-quick-build` / `dev-auto-build`): calls this skill as its closing verify phase, instead of carrying its own browser pass.
- `dev-writing-plans`: the route for a **major / plan-level** finding.
- `dev-brainstorming`: the route for a **concept-wrong** finding.
- `session-wrap`: runs AFTER this gate is green (or recorded OWED) to integrate and close out. This skill does not wrap or merge.
