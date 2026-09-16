---
name: dev-brainstorming
description: "Turn a vague idea into a concrete, approved design or spec through collaborative dialogue. Classifies the request first (spike / bounded / architectural) so the ceremony fits the work, holds a hard no-build-before-approval gate, runs divergent options -> design -> spec grounded in real research, can show mockups in a browser companion, and reviews the spec before handing off to dev-writing-plans. Use when starting something new, exploring options, or scoping a change. Triggers on: brainstorm, brainstorming, ideate, explore ideas, new feature, what should we build, design session, scope this, how should we approach, think through this, feasibility, can we, is it possible."
argument-hint: "[topic or problem statement]"
---

# dev-brainstorming: Idea -> Design -> Spec

Turn ideas into fully formed designs and specs through natural collaborative dialogue. Classify how much process the request needs, then work your path: understand context, refine the idea, present a design, get your human partner's approval.

**Output style.** Everything you present to your human partner (findings, a design, the options box, the executive summary) goes in their active output style. If none is set, default to: lead with the answer, short sentences, plain words, no idiom. This shapes wording only, never the approval gate or the option set.

> **Credit.** The spike/bounded/architectural tiering, the hard approval gate, the
> red-flags table, the anti-pattern section, and the visual-companion concept below
> are adapted, in places near-verbatim, from **`superpowers:brainstorming`** by
> **Jesse Vincent** (https://github.com/obra/superpowers), which is MIT-licensed.
> See [`../../THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md) for the full
> license text and attribution. The divergent-options research flow, the spec
> template, and the executive-summary review gate are original to this repository.
> Upstream is a reference only; this file is the source of truth for how the skill
> behaves here.

<HARD-GATE>
Do NOT invoke any implementation skill, write any code, scaffold any project, or take any implementation action until you have told your human partner what you intend and they have approved it. This applies to EVERY path below - the ceremony scales with the task; the approval gate never does.
</HARD-GATE>

## Classify first: three paths

Before your first question, classify the request and say the classification out loud - "this looks bounded, so I'll present a short design here rather than write a spec" - so your human partner can override it.

- **Spike** - a feasibility question ("can we...", "is it possible...", "quick and dirty is fine") whose output is an answer, not code you keep. Present the question and what you'll try in 2-3 sentences, get a nod, then find out as cheaply as correctness allows. No spec, no plan. Report findings as a recommendation; anything you built stays labelled throwaway.
- **Bounded** - a well-scoped change to code that already exists in this repo: a new flag, a small endpoint, a one-file fix. Bounded means the flow you are changing is already here to read; if there is no existing flow to change, the task is not bounded. Ask the clarifying questions that matter, present a short design IN CHAT (a few sentences to a few short paragraphs), and STOP. Implementation starts only after your human partner says yes - a bounded task's approval is as hard a gate as an architectural one. No spec file, no plan document; build via `dev-quick-build` (or whatever small-scope build flow you use).
- **Architectural** - new projects, new subsystems, changes that restructure how components fit together or alter interfaces others depend on. Follow the full process below: research, divergent options, design, written spec, spec review, then `dev-writing-plans`.

When in doubt between two paths, take the heavier one. The ratchet is one-way: hidden complexity discovered mid-task upgrades the path - stop, say so, and step up. Nothing downgrades mid-task.

## Anti-pattern: "too simple to need approval"

Every path ends with your human partner approving your intent before implementation. A todo list, a single-function utility, a config change - the design may be two sentences in chat, but you MUST present it and get approval. "Simple" tasks are where unexamined assumptions cause the most wasted work. What scales with simplicity is the artifact, never the approval.

### Red flags (STOP - you are rationalizing)

| Thought | Reality |
|---|---|
| "This is too simple to need a design" | Simple means a short design, not no design. Two sentences in chat, then approval. |
| "I'll call it bounded and skip the spec" | Reaching for a label to skip work IS the doubt - take the heavier path. |
| "It's bounded and the design is obvious - I'll start while they read it" | The gate is the approval, not the design's length. Present, then stop until you hear yes. |
| "I understand this kind of app, so it's bounded" | Bounded measures the repo, not your familiarity. A new project has no existing flow - it is architectural. |
| "The spike works, so I'll keep the code" | A spike's output is an answer. Keeping the code is a new request - classify it. |
| "It grew, but I'm almost done - no need to re-classify" | Hidden complexity upgrades the path mid-task. Stop and say so. |

## Spike path

1. **Explore context** - enough to frame the probe.
2. **Present the question + probe plan** - 2-3 sentences.
3. **Get approval** - a nod is enough.
4. **Investigate** - as cheaply as correctness allows.
5. **Report findings** - a recommendation; label anything built as throwaway.

## Bounded path

1. **Explore context** - read the files, docs, recent commits for the flow you are changing.
2. **Ask clarifying questions** - one at a time, only the ones that matter.
3. **Present a short design in chat** - approach, files touched, how it is tested.
4. **Get approval** - STOP and wait for an explicit yes. Presenting the design and starting in the same breath is skipping the gate.
5. **Implement** - hand to `dev-quick-build` (or your own project's small-scope build flow); TDD applies; no plan document.

## Architectural path

The full flow. Create a task per step and work them in order.

### Phase 1: Diverge (research + options)

Goal: find the real options, then lead with a recommendation. Diverge in your own thinking; present a short, ranked shortlist, not the raw breadth.

1. **Clarify the problem space** - purpose (outcome, not solution), who benefits, constraints, and the trigger (why now). If the request describes several independent subsystems, flag it and help decompose into sub-projects before refining any one - each gets its own spec -> plan -> build cycle.
2. **Research context** BEFORE ideating - by default, delegate the reading:
   - **Dispatch parallel reader subagents** (a cheaper model - a mid-tier model for judgment-light reading, your smallest model for bulk - via model override) to read the relevant code, docs, and prior decisions, each returning a condensed summary, not raw file dumps. Design from those summaries so the lead turn stays uncluttered. This is on by default; skip it only for a change whose context you can already see, and keep the design synthesis itself a single pass (coding/design does not parallelize the way reading does).
   - Search the codebase for existing patterns that apply, check whatever task tracker you use (Asana, Jira, Linear, GitHub Issues, or similar) for related work or prior art, and check any long-lived notes or past-conversation history you keep for earlier decisions on this topic.
   Do not brainstorm in a vacuum - ground every option in the real code and project context.
3. **Offer the visual companion just-in-time** - NOT upfront. The first time a question would be genuinely clearer shown than described (a real mockup / layout / diagram question), offer it then, as its own message. See the Visual Companion section.
4. **Settle on the distinct approaches the space genuinely has - usually 2-4.** Strip anything that is a minor variant of another; only exceed four when the design space is truly wide, and say so. For each, know its one-line what-it-does, its key tradeoff, and a rough effort (S/M/L/XL). YAGNI ruthlessly.
5. **Resolve any orthogonal decisions first.** If the design has cross-cutting axes (e.g. a behaviour choice AND a source-of-truth choice), settle those first, each as its own question - it collapses the option space. Never present the full option set and the axes in the same turn.
6. **Present recommend-led, through the question box.** Summarise each approach in a sentence with its key tradeoff, then **recommend ONE** with a one-line why. Surface the choice through `AskUserQuestion`: the recommended option **listed first and marked "(Recommended)"** as the default path, then the alternatives, plus a "Something else / combine" row. Invite combinations only when the approaches actually compose; otherwise it is a single pick. Do NOT post a dense lettered comparison table.
7. **Ask only genuine ambiguity.** Skip questions the code or an obvious convention already settles; ask one at a time, each with a recommended default. At any point offer "accept all remaining recommendations" so a long interview can end in one step.

### Phase 2: Converge (design)

Goal: narrow to one approach and flesh it out.

1. **Lock the direction** - confirm the chosen approach (or hybrid) and state it back in one sentence.
2. **Design the solution**, in sections scaled to their complexity (a few sentences if straightforward, up to ~200-300 words if nuanced): architecture / components / data flow, user experience, integration points, data model, edge cases and out-of-scope, dependencies. Ask after each section whether it looks right.
3. **Design for isolation and clarity** - break the system into units with one clear purpose and well-defined interfaces, each understandable and testable on its own. When a file or unit is doing too much, say so.
4. **Identify unknowns** - list what needs investigation or a decision before building; flag blockers vs nice-to-knows.

### Phase 3: Specify (spec document)

Goal: a concrete spec `dev-writing-plans` can consume.

1. **Write the spec** to `docs/plans/YYYY-MM-DD-<topic>-spec.md`. **Confirm today's date from your environment first** (an assistant's own "current date" context, or `date +%F`); never infer it from training priors; use ISO `YYYY-MM-DD`. (This date discipline does not travel to subagents - restate it in any delegating prompt.) Use this template:

```markdown
# <Project/Feature Name> - Spec

## Problem
{What problem this solves and why it matters}

## Solution
{Chosen approach - 2-3 paragraph summary}

## Architecture
{Components, services, data flow in text}

## Scope
### In Scope
- {what's included}
### Out of Scope
- {what's explicitly excluded}

## Data Model
{Key entities, fields, relationships}

## Integration Points
{External services, APIs, existing systems touched}

## User Experience
{How users interact with the solution}

## Open Questions
- {Anything unresolved that needs a decision}

## Success Criteria
- {Measurable outcomes that define "done"}
```

2. **Commit the spec** to git (in your working branch or worktree). If the visual companion was used, commit any keeper mockups into a tracked dir too - the companion's `.brainstorm/` scratch dir is gitignored and does not survive a fresh checkout. If a design artefact was published and locked in, link its URL in the spec's User Experience section too - that link, not a re-description, is the design record carried into the plan, PR, and deploy record.

3. **Spec self-review** (inline, fix and move on): scan for placeholders / TBD / TODO; internal contradictions; scope too broad for one plan; requirements ambiguous enough to build the wrong thing. Fix issues inline.

4. **Spec-reviewer subagent pass** - dispatch a general-purpose subagent using `spec-reviewer-prompt.md` (in this skill dir) against the spec file. It returns Approved | Issues Found. Adopt confirmed issues, re-run the self-review, and only proceed once it is clean.

5. **User review gate (executive summary, not the file)** - do NOT tell your human partner to open or read the spec file. Present a self-contained **executive summary in chat** that lets them decide without opening anything. Link the committed spec path once, as a reference only. Keep it tight (4-7 bullets), plain English, decisions first:
   - **What gets built** - one line.
   - **Why** - the problem it solves, one line.
   - **Key design decisions** - the 2-3 choices that shaped it, each stated so a non-reader can judge it, not just named.
   - **Scope** - what is in, and what is explicitly out.
   - **Any risk, cost, or hard-to-reverse flag** worth their eye.
   - **Decisions they still own** - only real product / design / trust calls, each as a plain-English question.

   Close with: "Approve, or tell me what to change." **Wait.** If they request changes, make them and re-run steps 3-4.

6. **Hand off** - once approved, invoke `dev-writing-plans` to produce the implementation plan. Do NOT invoke any other implementation skill; `dev-writing-plans` is the only next step on this path.

## Visual Companion

A browser-based companion for showing mockups, diagrams, and visual options during brainstorming. A tool, not a mode: accepting it means it is available for questions that benefit from visual treatment; it does NOT route every question through the browser.

**When the ask IS the exact UI change end-to-end**, propose publishing an interactive mockup (an Artifact, a CodePen, or whatever shareable-by-URL canvas your environment supports) immediately and iterating on it directly with the human partner, round by round, until they say something like "lock this in." The locked artefact's URL then becomes the canonical design reference, carried (not re-described) into the spec, the plan/runbook, the PR, and the deploy record. This is a different tool from the local companion below: a published artefact is durable and shareable by URL; the companion's scratch dir is local and dies with the working directory.

**Offer it just-in-time**, not upfront. Wait until a question would be genuinely clearer shown than told, then offer it as its own message (only the offer - no other content):

> "This next part might be easier if I show you - I can put together mockups, diagrams, and comparisons in a browser tab as we go. It's still new and can be token-intensive. Want me to? I'll open it for you."

Wait for the answer. If they accept, start the server with `--open` so their browser opens to the first screen. If they decline, continue text-only and don't offer again unless they raise it.

**Per-question decision (even after they accept):** would the user understand this better by seeing it than reading it? Use the browser for content that IS visual (mockups, wireframes, layout comparisons, diagrams, side-by-side designs); use the terminal for text (requirements, conceptual choices, tradeoff lists, A/B/C/D options, scope decisions). A UI *topic* is not automatically a visual *question*.

If they accept, read the detailed guide before proceeding: `visual-companion.md` (in this skill dir). The companion is zero-dependency (Node built-ins, no npm install) and writes mockups under `<project>/.brainstorm/`.

## Rules

- Never skip divergent thinking on the architectural path - even a "known" answer surfaces better options. But diverge in your OWN thinking; what you present is a short, ranked shortlist, not the raw breadth.
- **Lead with a recommendation.** Present at most 2-4 approaches, recommend ONE with a one-line why, and keep the alternatives and reasoning visible so the choice is real. Surface choices through the question box (`AskUserQuestion`) with the recommendation preselected, never a dense options table. If the user just wants your call, give it and say why.
- **Read this skill as intent, not a rigid script.** Prefer stating the goal and constraints over enumerating steps; over-prescription reduces quality on the strongest models. The flow assumes no particular model.
- **Model & subagents (operating note):** plan on your strongest available model (raise effort before switching models - measure your workhorse model at high effort as the bar a pricier model must beat), run reader subagents on a cheaper model, and build in a fresh session.
- The spec is the architectural-path deliverable. If the session ends early, at minimum produce the spec.
- Follow existing project patterns; explore the current structure before proposing changes. Include targeted improvements to code you're working in; don't propose unrelated refactoring.
- At the review gate, the deliverable is a decision-ready **executive summary in chat**, never "go read the spec file". The committed spec is a reference, not the thing you ask them to read.
- Keep the energy generative, not bureaucratic. The approval gate is the one thing that never bends.
