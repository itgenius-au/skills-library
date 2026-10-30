# Cost-saving build: payoff and code budget

**A cost-saving build states its payoff and a code budget.** This applies only when the ask exists to
cut cost (money, tokens or spend); every other build skips it. Before Phase 3, write three lines in
the runbook Decisions: the expected saving; the measure that proves it (what runs, on what, and the
pass mark); and a code budget, counted as the lines the branch adds to code and test files
(`git diff --numstat origin/<default>...HEAD`, docs and the runbook not counted). Phase 3 asks a fifth
question for such a build: is the budget in proportion to the saving? Two events are stops in the
Phase 7 list: the count is over budget at Phase 5 (add and commit a checkpoint first, so staged,
unstaged and new files are counted), or the measure misses its pass mark. Run the measure before any
further round of building, and before the deploy when it can run off production; a miss that only
shows after the deploy is reported with a rollback-first recommendation. At either stop, tell the
user and park the build (Phase 7, and Wrap "Parking a build that stopped before it was safe"). A next
round needs the user's go and a new budget; silence is not a go. Why: a cost-saving build whose code costs more than it saves is a net loss.
