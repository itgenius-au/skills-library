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

**No local browser extension?** When your interactive browser tool is not available (a cloud VM, a headless or unattended run, a surface behind an access gateway or SSO), run the pass on a remote or headless browser service that can hold a saved, signed-in session. It counts as an available browser. Reading, navigating, clicking, and screenshots are fine, plus test data under the Reversible smoke-data rule below. Other writes to live systems, typing credentials, or capturing a new login profile follow their normal rules and need the owner's go-ahead.

1. **Establish the target.** Production when the caller deployed; the worktree / preview build otherwise. Confirm the URL before acting.
2. **Interact, do not just look.** Exercise every acceptance point of the change: click each new control, drive the flow a real user would, and check counts / orders / states against what the data implies - not against the label. A screenshot of a page that rendered is not verification; a control you clicked that did the right thing is.
3. **Capture evidence.** Screenshot each verified acceptance point. Note what you checked and what the data said it should be.
4. **Signed-out / SSO:** click the sign-in button, but do not act on a third-party identity provider's own login page (Google, Microsoft, etc.) - hand the account-pick to the user in one clear sentence, then continue once they confirm. **Never type credentials.**
5. **Record the result:** update the caller's runbook / deploy record persona-pass line from OWED to DONE with what was verified.

### Authenticated or unattended surfaces (SSO / access gateway)

Step 4 assumes a local browser tool, a signed-in browser, and the user present. When that does not hold - a headless / cron / cloud-VM run, or a surface behind an **access gateway plus SSO** - drive the pass through a remote or headless browser service with saved authenticated profiles, and run an **auth preflight FIRST**:

- **Probe reuse-auth before the pass.** Reuse the saved profile, open the target, and confirm you land IN the app - not on the identity provider's login page or the gateway's block page. A captured SSO session decays: it can show the account **"Signed out"** days after capture, so a profile that worked last week may not today.
- **If signed out, STOP and re-capture - do not push through.** Capture a fresh profile once via an attended login (the human types the password, never the agent), then reuse it. Discovering a dead profile mid-QA wastes the run and can leave a false OWED.
- **A gateway service token is not a general key.** It bypasses the IdP login only if it is in that specific app's access policy, and it carries no user identity - so a surface that maps a signed-in user to server-side entitlements (per-department, per-tenant) can pass the gateway yet deny the data. For entitlement-gated pages, prefer a real captured user session.
- **Unattended with no live profile:** record the pass OWED with the exact reason and name the single unblock - a fresh profile capture - rather than reporting a false green.
- **Headless browsers cannot hover.** A cloud/headless browser reports `matchMedia('(hover: hover)')` as false, so CSS-framework `hover:` / `group-hover:` / `peer-hover:` styles never apply there. Prove hover-revealed UI (tooltips, menus) through keyboard focus instead, log the media query result, and record the mouse-hover path OWED for a real desktop - never as a product failure.

### No browser surface (ops helper, CLI, VM tooling)

Some deliverables have no page to click: a script an owner runs on a VM, a CLI, a cron helper. "Green tests" is still not done. Run the real tool on the real host:

- **Target a disposable instance, never a live one.** Make a throwaway object of the same kind (a test session, a test record, a sandbox account), and name it so it reads as a test, for example "<tool> E2E test (ignore)". Drive the tool against it exactly as the owner would. Leave it stopped or archived, not deleted, and say where it is.
- **Run a read-only pass on the real state first** (`--dry-run` or equivalent), and confirm it classifies live data the way the plan expects. For a classifier or rules engine, check the output proportions (count per bucket, top senders or sources per bucket) against what the data implies, and read a sample of each "sure" bucket. Fixtures pass a weak rule; real data shows it. Example: a live scan of a few hundred real threads put nearly half of them in the top-priority bucket and real people's group mail in a sure noise bucket, three rule defects every fake had passed.
- **Add a deliberate positive control for the most dangerous path.** If the tool exists to avoid a harmful outcome (a duplicate, a double charge, an unwanted action), cause that outcome on purpose, on the disposable instance only, and confirm the tool's detection flags it. Capture the real system output and add it as a regression-test fixture. A guard only ever tested against an imagined message is unproven.
- **A tool that keeps its own state (a cron poller, a queue worker): run the INSTALLED copy in LIVE mode over a disposable home.** Make a throwaway `HOME` that holds a copy of the real state file (for a missed-case fix, the backup from before the fix, so the exact failing case is in it) and every folder the tool expects to exist (its working or spawn folder too; a missing one kills the run at the side-effect call). Keep its real reads (the task API, the session listing) pointed at the real services, and put a logging stub first on `PATH` for the one command with the side effect (the command that starts a session, sends, or charges), so nothing real happens. Run it twice, like the scheduler: the first run must take the action, the second must not repeat it. Hash the real state file before and after; it must not change. Name the folder as a test and leave it in place.
- **A change that writes to a third-party API (for example a field set in a task tracker): prove it against the REAL API.** Run the deployed code's payload builder on a disposable test object in a private test project with no human members, so nobody is notified. Write each value the change can produce and read it back. Add a NEGATIVE control the API must reject (for example a retired option id) to prove the check can fail. Then complete or archive the test object, never delete it.
- **Loop on what the live run finds.** A defect the live run catches loops back like a browser-caught build bug (failing test, fix, gates, review, redeploy), with the same bound of 2 cycles.
- Record the evidence (commands, verdicts, captured output) in the deploy record, and report `QA: pass` / `QA: <n> defects routed` as usual.

### Harness changes (agent hooks, settings, plugins)

A hook or settings change has no page either, and a unit test that pipes JSON into the hook script does not prove the harness delivers it. Verify it in the real harness:

- **Use a fresh headless session.** Hooks load when a session starts, so the session that installed the change proves nothing. Run your agent CLI in non-interactive mode (for Claude Code, `claude -p "<run one command that should trigger the hook, then quote any hook context you received>" --output-format stream-json --verbose`), with the smallest task and a turn cap.
  - **Pick the trigger tool from the session's own tool list.** A headless session does not attach every MCP server an interactive one has. Read the `tools` and `mcp_servers` fields of the stream's `init` event, and choose a read-only tool that is listed. If you pick one that was not attached, the calls fail with "No such tool available", the hook never runs, and the run proves nothing. A failed tool call is not a negative result.
  - **A plugin skill change: load the BRANCH plugin, not the installed one.** Run from a throwaway repo outside every checkout, pointing the CLI at the branch copy of the plugin (for Claude Code, `--plugin-dir <clone>/<plugin path>` with `--setting-sources project --strict-mcp-config`, a narrow `--allowedTools` list, a turn cap, and stdin from `/dev/null`). Use a temporary config directory so the branch's session-start hook stays off your real settings, and checksum the real settings file before and after. The Skill tool result may say only "Launching skill", so prove the branch copy loaded from the injected "Base directory for this skill" message. Tell the agent to run each shell command on its own: a narrow Bash rule denies a chained `; echo "exit=$?"`. Then check the files on disk and the result event's `permission_denials` list.
- **Check the transcript, not only the model's answer.** Take the session id from the stream's `init` event, open that session's transcript file, and grep for the hook's own text. A model can misreport what it saw.
- **Cover each delivery path, plus a negative control.** Each event the hook is registered on (for example a tool hook's success and failure routes) gets its own fresh session; a hook with a cool-down needs a new session per case. Add one run that must NOT trigger it.
- **Blocking hooks: prove they cannot trap running sessions.** Settings are reloaded mid-session, so a Stop or PreToolUse hook reaches sessions that are already running. Run the installed script by hand against an older session's transcript and confirm it stays silent where it should.
- **Installer changes: dry-run first.** Run the installer against a copy of the user's config, diff the result, and only then run it for real.

### Heavy / async data pages

Wait for REAL rows, not skeletons, before you judge a page: poll until the loading placeholders are gone and data (or an explicit empty state) is present, and reload once or twice if a cold load stalls. A page that skeletons then **never populates, with no error, retry, or degradation notice, is a silent-failure Product finding** - not an Execution flake to retry away. Note the load time; a fetch that aggregates a third-party API (for example a payments API) across accounts can rate-limit under repeated QA loads, so isolate genuine app-instability from your own load pattern with one controlled cold load before you rank severity.


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

## Rule out a broken check first

Before treating a browser/QA failure as a product defect, confirm the check itself is sound:

- The interaction actually **reached** the target operation - not a stuck spinner, a stale selector, an extension hiccup, or a timeout.
- The **rendered** page (a screenshot of the real surface) is what violated the acceptance point, not an unread tool error underneath.

- **Present is not visible.** An element in the DOM with `display: block` can still be clipped by an `overflow: hidden` ancestor, painted over by a later sibling at the same `z-index`, or pushed off-screen. Prove visibility with `document.elementFromPoint` at the element's centre AND corners (it must return the element itself), and read the screenshot - a numeric check can pass while the screenshot shows the break.
- **Prove the checks discriminate: run them on the previous build first.** Before the deploy, run the same live QA script against production as it is. Every check of the new feature must FAIL there; a check that passes on both builds proves nothing. In practice many checks fail on the old build, and the control can expose a fake-green check.
- **An SPA fallback answers every path.** A single-page app's server returns `200 text/html` (its `index.html`) for any unknown path, so "the file returns 200 text/html" passes even when the file is missing. Match something only the real file has, such as its own `<title>` or a rendered element.
- **Known scripted-check traps** (Execution, not Product): `innerText` applies CSS `text-transform`, so match uppercased labels on `textContent`; `elementFromPoint` skips `pointer-events: none` elements, so enable pointer events on the target only while measuring; rendered text collapses runs of spaces, so normalise whitespace before comparing names from an API.

Classify it: **Product** (the rendered behaviour is genuinely wrong - route it below), **Execution** (the check or tool failed to reach or observe), or **Environment / Unknown**. **Never resolve an Execution or Unknown case by loosening a wait, a retry, or an assertion** - fix the check and re-run. A tooling failure is not a licence to change product code, and a backend/log/DB check never overrides a contradictory screenshot (when they disagree, the rendered page is the finding).

## Severity triage: route the defect, do not just patch

A defect the browser pass surfaces is a real finding on the current surface (production, if the caller already deployed). Never ship past it or log it as a "known issue". Classify it, then route:

| Severity | What it means | Route to |
|---|---|---|
| **Minor (build bug)** | The concept is right and the plan is right; the implementation has a bug - a rendered break, a wrong count / order, a control that does nothing, an off-by-one. Fixable in place. | **Back to the calling build skill's own build loop** (e.g. `dev-quick-build` or `dev-auto-build`): reproduce with a failing test, fix to green (TDD), re-run gates, re-review the diff, re-ship, then re-verify here. |
| **Major (plan wrong)** | The implementation faithfully followed the plan, but verification shows the PLAN was wrong - a whole acceptance criterion is unmet by design, a slice is missing, a data-model / semantic assumption baked into the plan is false. Patching in the build loop would be lipstick. | **`dev-writing-plans`** - revise the plan, then re-enter the build. |
| **Concept wrong** | Verification (or the user seeing it live) shows the FEATURE itself is wrong - it solves the wrong problem, the UX concept is off, the approach is rejected on sight. | **`dev-brainstorming`** - re-design from the spec before any more building. |

Escalation ladder: **bug -> plan -> concept.** When unsure between two levels, take the higher one - a mis-scoped patch on a plan-level miss wastes a build cycle. A genuine product / design / trust decision is never settled inside a fix: escalate it to the user.

End every pass with exactly one result line for the caller's shipped comment: `QA: pass`, `QA: OWED <what>`, or `QA: <n> defects routed`. This skill posts nothing to your task tracker.

## Bounded loop (minor path only)

The minor / build-bug loop is **bounded: max 2 cycles.** If the defect survives 2 build-fix-verify cycles, STOP: if the caller deployed, roll back to the previous good revision (the rollback pointer in the deploy record), record the outstanding break in the runbook, and surface it to the user with what was tried and the suggested next step. Shipping a browser-broken page and walking away is never the outcome.

**Prove each fix on the real surface BEFORE redeploying it** - a redeploy is not a test run (no live iteration). Use the cheapest option that renders the new code with real data and real auth: a no-traffic revision's tag URL; a staging deploy; or, for an auth-gated SPA with no usable staging, open the LIVE origin over the saved browser profile with request interception on, serve `index.html` and the static assets from the local build, and let the API calls pass through to production. Run the same checks that caught the defect (screenshots, visibility at desktop and phone widths, console errors), confirm they pass, then redeploy and re-verify on the live URL. An interception pass that also serves the API is not proof - the data must be live.

The major and concept-wrong paths are not loops here - they leave this skill and re-enter the pipeline upstream (`dev-writing-plans` / `dev-brainstorming`), which run their own gates before the work returns to a build skill and, eventually, back to this gate.

## Relationship to other skills

- A build skill (e.g. `dev-quick-build` / `dev-auto-build`): calls this skill as its closing verify phase, instead of carrying its own browser pass.
- `dev-writing-plans`: the route for a **major / plan-level** finding.
- `dev-brainstorming`: the route for a **concept-wrong** finding.
- `session-wrap`: runs AFTER this gate is green (or recorded OWED) to integrate and close out. This skill does not wrap or merge.
