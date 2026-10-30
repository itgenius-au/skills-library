# Steps 4 and 5: synthesis checks and report format

**A leg that cannot run commands cannot report command output.** The GLM leg sees only the text its subagent inlined; it has no shell and no repo access. If its report claims "I ran X" with output, commit SHAs, file listings, or machine state, treat that evidence as UNVERIFIED: check the cited commits, files, and paths yourself. If they do not exist, the leg fabricated them. Exclude that leg from the consensus denominator and say so in the header (e.g. `GLM (excluded: fabricated evidence)`), even when its verdict is "clean". A leg without a shell can report a non-existent commit, a non-existent CI file, and false repo state, all under a "no defects" verdict.

**A finding that rests on vendor or API documentation is re-checked before it decides anything.** Legs often quote a page from memory, and the quote can come from an older version. Before you adopt OR reject such a finding: re-fetch the page, note its last-updated date, and quote the current text. Where a live probe exists (a validate-only or dry-run call, a read), settle the claim with it. Record which source decided it.

**A "tests leak state" finding needs the nearest `conftest.py` first.** Autouse fixtures often reset module globals for each test. Check them before you count the finding: two legs can both report a shared-cache leak that an autouse fixture already resets per test.

```
## Review Swarm - <mode>: <subject>
Models: Codex (<model>, <status>) · Gemini (<model>, <status>) · GLM (<model>, <status>) · Fable (<model>, <status>)

### Findings
| # | Type | Severity | Consensus | Finding | Location | Action |
|---|------|----------|-----------|---------|----------|--------|
| 1 | defect      | Critical | 4/4       | ...     | file:line| ...    |
| 2 | defect      | High     | 2/4 (C,F) | ...     | file:line| ...    |
| 3 | enhancement | Medium   | 1/4 (GLM) | ...     | file:line| log as follow-up; owner decides |

### Must-fix defects (before ship/act)
1. ...

### Simplify (remove; outside the ask)
1. ...

### Advisory (NOT for this build - one line each, log as follow-ups)
1. ...

### Agreed clean
[Areas all available models checked and passed, with the evidence - not a bare "looks fine".]

### Disagreements worth a closer look
[Where models contradict each other. Offer /review-debate to litigate.]
```
