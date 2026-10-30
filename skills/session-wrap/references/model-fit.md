# Step 2: model fit check (all modes)

After the summary, add a short **model fit** note so model choices can be calibrated over time. This runs in every mode (pick up / pause / done): it is part of reviewing the conversation, not a mode-specific step.

1. **Name the model that ran this session** (self-identify from the environment), and note the reasoning effort used.
2. **Judge it against the work actually done**, using four signals:
   - *Reasoning depth*: subtle multi-step correctness (concurrency, ordering, idempotency, auth precedence) versus mechanical edits.
   - *Impact*: production data, money, security or irreversible effects versus low-stakes and reversible work.
   - *Breadth*: large cross-file diffs held in view at once versus small localized changes.
   - *Autonomy*: long unattended agentic runs versus interactive back-and-forth.
3. **Give a one-line verdict** (covering both model tier and reasoning effort), one of: **Well matched**; **Over-powered** (a cheaper tier would very likely have done this as well); or **Under-powered** (subtle-correctness or high-impact elements where a stronger tier was worth it - name the specific thing).

Keep it to a few lines. A trivial session gets one ("Model fit: fine, trivial session"). The goal is a running signal to pattern-match on, not a formal audit.

**Pickup companion (forward-looking).** The check above grades the model that *ran* this session (backward-looking). In **pick up** mode only, the handoff (Step 9) pairs it with a forward-looking suggestion for the model the *next* session should start on, graded against the **remaining** work. The two often land on different tiers: a session that did the hard design on a premium tier usually hands off a build-against-a-plan that a step-down tier executes just as well. Compute that forward suggestion at the pick up handoff, not here, because the intent is not known yet.
