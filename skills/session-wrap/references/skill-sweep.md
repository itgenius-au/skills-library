# Skill sweep (intent: closes nothing)

When Step 3 picks skill sweep, run Steps 1 to 4 in full, run Steps 5 and 6 only if the sweep changed files, skip Steps 7 and 8, and finish at Step 9. The sweep is the done wrap's learning capture without its closeout, for a window that stays open.

1. **Scan and deep pass.** Run the deep session scan and the deep pass exactly as in done mode. The deep pass is required: the user asked for the review by name, so the "trivial session" skip does not apply. Print the `Deep pass:` line. Then run the sub-session sweep and print the `Sub-session sweep:` line.
2. **Apply and recommend.** Auto-apply the doc and skill lessons (see "How to apply updates" and "Skill files: what auto-applies" in SKILL.md), print the `Skill and doc updates applied:` line, and emit the Recommendations block (or "No skill/hook/plugin recommendations").
3. **Make the edits durable, and only that.** If the sweep changed files, run Steps 5 and 6 as pause does (commit and push the branch). The worktree and branch stay mounted. If it changed nothing, skip both steps.
4. **Close nothing.** Skip Step 7 (no worktree closeout, no merge, no task-tracker wrap comment) and Step 8 (the browser tabs stay open). Do not write a resume prompt, and do not print the archive line.
5. **Recommendations ship on the reply**, the way the done path does under "On approval". Shipping them still closes nothing.

Step 9 gives the sweep's closing message.
