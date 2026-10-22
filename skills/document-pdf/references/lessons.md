# Lessons: the fault behind each rule

Mined from many real document sessions (reports, memos, agreements, evidence packs). People and entities are left out on purpose.

| Fault seen | Rule it created |
|---|---|
| Five different engines (Chrome, WeasyPrint, fpdf2, reportlab, LibreOffice) across sessions, each set up from scratch; the only helper script was Mac-only | One builder with engine auto-detect (`build_pdf.py`) |
| The only copy of a contract's HTML was in a scratchpad that got cleared | One canonical Markdown source in a durable place |
| A "printable copy" was an old PDF copied to Downloads, without the latest edits | Re-render, never re-send |
| Final signing PDFs still said "DRAFT" and "not legal advice"; the requester had to point it out twice | `--profile signing` fails on DRAFT and disclaimer text |
| A `[Date]` placeholder reached a signing PDF | Gate fails on open brackets (e-sign tags excluded) |
| Signature boxes too small to sign in; e-sign fields sized from the tag font were too small | 20 mm signature space, white tags as anchors for larger fields |
| First render of a deed had "Executed as a deed" and no signature blocks | Execution blocks are a drafting step, with per-entity wording |
| Signature boxes fell onto a page of their own | `.keep` wrapper, plus the gate's orphan-page warning, plus looking at the PNGs |
| A subagent said the build was fine; it had only checked text | The orchestrator looks at every page itself |
| `grep` for a phrase returned 0 because the phrase wrapped across lines | The gate collapses whitespace before matching |
| Lowercase "it" in an entity name, wrong trading address | Copy names and addresses from the register; check trading vs registered |
| A form's pre-filled signing date was earlier than the real signing date | Never back-date; "on or about" for the effective date |
| Dates that disagreed across the documents of one pack | Date audit across the pack against the source records |
| A shared drive still showed old text after an in-place update | New file per version, or verify with `md5Checksum` |
| An e-sign "draft" still emailed the signer, who got a duplicate | Know what your e-sign tool sends at each step; dry run first |
| An e-sign connector needed a public URL for the file | Do not use that route for confidential documents |
| Reflowing a lawyer's Word file moved the signature lines | LibreOffice for faithful conversion; place fields by coordinates |
| Drafts grew long; the requester cut them back each time | Brief by default; no unasked annexures or disclaimers |
| Reviews found real drafting errors (a payment trigger with no date, a release undone by its own carve-out) | Review swarm for money, releases and ownership changes |
| Working files sat in a worktree that was about to be deleted | Git-ignored working folder, backed up to private storage before cleanup |
| The requester wanted to check the live e-sign document before others signed | The internal approver is signer1; others in any order |
