# Step 4: learning capture (every intent; pause reads it without the scan and the deep pass)

The checklist item about recording decisions stays in SKILL.md, Step 4, because it applies to every intent, pause included. In the first sentence of "Improvement decision", "auto-apply above" means SKILL.md, section "How to apply updates".

**Depth goes in project docs; keep memory and project instruction files lean.** Project docs (`docs/*.md`) are where comprehensiveness belongs: capture the full context, the *why*, how it works, and how to operate or reproduce it - err toward more detail. Memory files and `CLAUDE.md` are the opposite discipline: tight one-line pointers and routing, never doc-level prose (they load into every session). When a session surfaces a reusable *procedure*, it belongs in a skill, not one-off prose: a new skill or a behaviour change goes through the improvement decision below, and a lesson-type note to an existing skill auto-applies (see "Skill files: what auto-applies" in SKILL.md). Strong bias: extend the relevant project's existing doc rather than create a new memory entry; reserve new memory for patterns that genuinely span projects.

Checklist:

- Architecture changed.
- Infrastructure or environment changed.
- External service behavior learned.
- New credentials, services, webhooks, or scheduled jobs introduced.
- Deployment process changed.
- Project instructions or routing became stale.
- A gotcha was discovered.
- A deploy or rollback happened.
- A reusable workflow emerged - a skill, not prose. A new skill or a behaviour change is a recommendation (improvement decision below); a lesson-type note to an existing skill auto-applies.
- A transferable rule is stuck in a dated doc (plan, deploy record, audit): promote it to `gotchas.md` or the evergreen topic doc. If this session restated a rule that already sits in an earlier dated doc, that promotion is overdue - do it now.
- Project-instruction routing: (a) any doc created or substantially extended this session gets a routing line; (b) re-read the existing lines for THIS session's feature area and confirm they still tell the truth (a stale index is read first, fixed last).
- Core docs exist AND are accurate: every project needs `docs/gotchas.md`; `architecture.md` and `deployment.md` only where something deploys. Re-read the ones touching this session's subject - an exists-but-wrong doc is worse than a missing one.
- Stale `AGENTS.md` fork: if an `AGENTS.md` duplicates `CLAUDE.md` and has drifted, make it a symlink to `.claude/CLAUDE.md` or maintain it deliberately.

Prefer project documentation over global memory.

Priority order:

| Priority | Target | What belongs there |
|---|---|---|
| 1 | Project `docs/architecture.md` | System shape, components, data flow |
| 1 | Project `docs/deployment.md` | Deploy commands, environment, verification |
| 1 | Project topic docs | Integration-specific behavior |
| 2 | Project `docs/gotchas.md` | Project-specific footguns |
| 2 | Project `.claude/CLAUDE.md` or `AGENTS.md` | Routing pointers to new docs |
| 3 | Shared or parent-repo docs | Cross-project patterns only |

Do not create new memory files for project-specific details when an existing project doc can be extended.

## Improvement decision (skills, hooks, plugins)

Docs, and lesson-type notes in an existing skill, auto-apply above. New skills, skill behaviour changes, hooks, and plugins are a different class, and the PRIMARY way to surface them is **your own judgement of the conversation, not phrase-matching.**

**Run this self-assessment on EVERY done wrap, whether or not the user named it:** ask *"did a reusable procedure, workflow, or rule emerge this session?"* Look for a novel multi-step process, a non-obvious sequence, a workaround for how a system behaves, an integration recipe, or a correction that should hold next time. If it is plausibly reusable, recommend it (skill / hook / plugin / doc) - even if the user never asked and it happened once. The directive and error signals from the deep session scan are a **supplement** that catches explicit asks and repeated friction your memory may have dropped; they are not the trigger.

**How to judge (do NOT gate this on repetition):**

- **A clearly reusable procedure or rule fires at n=1** - your semantic call. If a future session would benefit from repeating what happened here (a working sequence, a recipe, a rule that should hold), recommend it even if it was unnamed and occurred once.
- **Explicit user directives fire at n=1** and are self-authorising: "from now on", "update the skill", "why isn't this a skill", "make this a hook", "next time do X", and scope rejections like "I didn't ask for that" or "I don't know why you're doing X". (Assistant prose like "I've updated the skill" is not a directive; the scan excludes it.)
- **Weak or ambiguous friction signals need n>=2** - a bare repeated correction or a recurring tool error counts only when it recurs. The n>=2 bar is for THESE noisy signals, NOT for a procedure you judge clearly reusable; never let it suppress a genuine once-emerged procedure.

**Escalation ladder - which target holds the lesson:**

| Signal | Target | Handling |
|---|---|---|
| A rule that was wrong or restated (especially twice) | `CLAUDE.md` / `gotchas.md` | doc auto-apply |
| A lesson, gotcha, or corrected fact for an existing skill | that skill's Lessons / notes | doc auto-apply ("Skill files: what auto-applies") |
| A reusable procedure (even once) or a re-typed prompt | a new skill, or a behaviour change in an existing one | recommend-only |
| Something that must happen every time | a hook | recommend-only |
| A lesson a second repo also needs | a plugin | recommend-only |

**Recommendations output block.** Emit one consolidated block as a numbered list (1, 2, 3), one item per candidate: the target (new skill `x` / fold into skill `y` / hook / plugin), the evidence quote (from the session), the proposed change in a clause, the next step (open a PR to wherever that skill lives; edit the hooks or plugin manifest for a hook or plugin), and a **Recommend:** disposition (approve / decline / defer) with a few words of why. End the block with one line: Reply "go" to accept every recommendation, or answer by number (for example "1: approve, 2: defer"). This is the same decision format as the `exec-summary` skill. These are shipped at Step 7, not here. If nothing qualifies, say "No skill/hook/plugin recommendations" - that sentence covers recommendations ONLY.

## Deep pass agents

- **Candidates present:** dispatch one small subagent (a mid-tier or small model) per strong candidate (bounded, top 5; log any you drop - never silently cap). Each reads the transcript span the scan named and returns: is this a real reusable procedure or rule? which skill, doc or hook holds it? a drafted change? Merge its verdicts into the Recommendations block.
- **Forced but zero candidates** (compacted, long, or "go deep" with none found): run ONE bounded general-review subagent over the stitched spans, so "go deep" has real work - do not no-op. (For a long or compacted transcript, use the slice agents below instead of the one agent.)
- **Long or compacted transcript: slice it.** When the transcript is over about 2,000 lines, or the session was compacted, split the stitched spans into N slice agents of about 1,500 lines each, one line range per agent, instead of one agent over the whole span. The slice agents sit outside the top-5 cap above; merge their verdicts into the Recommendations block. Never rely on a scan of user turns only for content from before a compaction: early corrections sit there, and the scan does not weigh them.
