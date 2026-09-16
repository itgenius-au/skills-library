---
name: dev-debugging
description: "The house debugging discipline for a bug or unexpected behaviour: reproduce it on demand, form one testable hypothesis, isolate the cause with evidence (measure live state, never reason from the docs or the recipe), fix the root cause not the symptom, then verify the reproduction passes and lock it with a regression test. Use whenever something is broken, failing, flaky, throwing, or behaving differently from expected and you need to find out why before changing code. Triggers on: debug, debug this, why is this failing, why is this broken, this is broken, unexpected behaviour, it's not working, flaky test, intermittent, root cause, trace this bug, investigate this error, find the cause."
---

# dev-debugging: Find the Cause, Then Fix It

A discipline for turning "it's broken" into a verified root-cause fix, without guessing. Invoke it BEFORE changing code to fix a bug - the fix comes last, after the cause is proven.

> **Adapted from** [`superpowers:systematic-debugging`](https://github.com/obra/superpowers) by Jesse Vincent, MIT licensed. Upstream is a reference only; this file is the source of truth. ("systematic" dropped from the name - the discipline is the point, not the adjective.) Full upstream attribution: [`../../THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).

## The rule

Do not change code to fix a bug until you can reproduce it and you have evidence for the cause. A fix applied to an unreproduced bug, or to a symptom, is a guess: it either does nothing, hides the problem, or moves it. Guessing feels faster and is almost always slower.

## The five steps

Work them in order. Create a todo per step and do not skip ahead - a fix that jumps from step 1 to step 4 is the shotgun anti-pattern.

### 1. Reproduce
Make it fail on demand. Find the smallest, most reliable set of inputs / state / steps that triggers it. A bug you cannot reproduce, you cannot prove you fixed. For an intermittent / flaky failure, reproduce the *conditions* (timing, ordering, concurrency, a specific data shape) until the failure is repeatable, even if not every run.

### 2. Hypothesize
State ONE specific, testable theory of the cause: "the count is wrong because the query excludes suspended rows server-side." Not a list of five vague suspicions. One theory you can prove or kill with a single observation. If you truly have several, rank them and test the cheapest-to-check first, one at a time.

### 3. Isolate with evidence
Prove or kill the hypothesis by looking at real state, not by reasoning about what the code "should" do:

- **Measure live, never reason from the recipe.** Read the actual value, the actual response, the actual row, the actual log line - from the running system, not from the docs, the comment, or your memory of how it works. Documentation and prior claims are unverified hypotheses.
- **Narrow it.** Bisect the input, the code path, the commit range (`git bisect`), or the time window until the boundary between works and fails is a single change. Add temporary instrumentation (a log, a breakpoint, a printed value) at the boundary.
- **Confirm a negative with a positive control.** "Zero results" is not a finding until a case you KNOW should return results does. If nothing reproduces, prove your harness can observe a failure at all.

Loop 2 → 3 until one hypothesis is confirmed by evidence. Do not proceed to the fix on a theory you have not proven.

### 4. Fix the root cause
Fix the cause you proved, not the symptom. A clamp on a bad value, a retry around a race, a null-guard over a wrong assumption - these hide the bug; they do not fix it. If a deadline forces a symptom patch, say so explicitly, mark it a mitigation, and record the real cause to fix. Keep the fix scoped to the proven cause; do not fold in unrelated refactors.

### 5. Verify
- Re-run the step-1 reproduction: it must now pass.
- **Add a regression test** that fails without the fix and passes with it - this is how the bug stays dead.
- Confirm you did not just move the bug: re-run the surrounding suite and check the adjacent paths the fix touched.
- For a live-surface bug, verify on the real surface (hand to `dev-qa-verify` if it has a UI surface).

**Output style.** State the proven cause and the fix in the reader's active output style. If none is set, default to: lead with the answer, short sentences, plain words, no idiom.

## Red flags (stop - you are guessing)

| Thought | Reality |
|---|---|
| "I'll just add a try/except / null-check and move on" | That hides a symptom. What is null, and why? Go to step 3. |
| "It's probably X, let me change X" | "Probably" is an unproven hypothesis. Prove it (step 3) before editing. |
| "I can't reproduce it, but I think I know the fix" | An unreproduced fix is unverifiable. Reproduce first (step 1). |
| "The docs / comment say it works this way" | Docs are a hypothesis. Measure the live value (step 3). |
| "Tests pass now, so it's fixed" | Did you re-run the exact reproduction and add a regression test? (step 5) |
| "Let me change a few things and re-run" | Change ONE thing at a time, or you cannot attribute the result. |

## Relationship to other skills

- Hand a UI-surface fix to `dev-qa-verify` for the browser pass once the reproduction passes.
- A bug that turns out to need a real feature change routes into the build pathway (`dev-quick-build` / `dev-auto-build`); a bug that reveals a wrong design routes to `dev-brainstorming`.
