# Documents that get signed

Read this when the PDF is an agreement, deed, release, resolution, statutory statement, signed letter, or anything else someone will sign. It adds to the general workflow in SKILL.md; it does not replace it.

> This is a drafting and layout workflow, not legal advice. Wording and execution rules differ by entity and jurisdiction. Have a qualified person confirm anything that binds money, rights or a filing.

## Extra intake

- **Parties**: full legal names, entity numbers (company or tax registration numbers), addresses. Check the trading vs registered address.
- **Governing law**, and where each party signs. This sets the execution blocks.
- **Effective date vs signing date.**
- **Signers, in order.** A good default: the internal approver signs first, so they can check the live document. Then everyone else signs in any order.
- **Who may sign** for each entity: confirm from the register or the constitution. Do not assume the requester signs.

## Drafting rules

- **Brief.** Only what the document needs: parties, the decision or deal, money, dates, release, governing law, execution. Requesters cut long drafts every time.
- **No unasked extras.** No annexure lists, no other-entity detail, no "seek legal advice" lines, no disclaimers, unless asked. Say once in chat that the text is AI-drafted and reviewed, not lawyer-settled.
- **Honest dates.** Never back-date. Sign on the real date, and record an earlier effective date as "on or about <date>". A pre-filled signing date that differs from the real one is a false execution date.
- **Numbered clauses**: `**1. Title.** text`, with `(a)`, `(b)` sub-clauses. Define terms in bold on first use: `(**Company**)`.
- **Names**: copy entity names exactly from the register, capitals included.
- **Final means final.** No `DRAFT`, "not legal advice", working notes or open `[placeholders]` in the PDF. Run the gate with `--profile signing`, which enforces this.

## Execution blocks

Copy the HTML from [execution-blocks.md](execution-blocks.md). It also lists capacity wording used before (company under a statutory execution rule, US LLC, Hong Kong company, individual with witness, sworn statement before a notary).

- One e-sign text tag per field (`[sig|req|signerN]`, `[date|req|signerN]`). The CSS prints the tags white. Number signers 1..N with no gap.
- Keep the execution block on the same page as the last clause (`<div class="keep">`).
- At least 20 mm of signing space per signature. Signers said smaller boxes left no room.

## Review

- **Money, releases, employment, shares, or anything filed with a regulator**: run `review-swarm` on the source text. Brief the reviewers on what to check and what not to reopen. Settle each finding as a numbered decision with a recommendation, then rebuild.
- **Simple signed letters**: one independent check (`review-with-codex`).
- Common catches: a payment trigger with no date; a carve-out that undoes the release; "ex gratia" wording that lets the payee keep both the payment and the claim; the wrong signer for an entity; dates that differ from the source records.

## E-sign delivery

- Pick your e-sign tool and learn how it finds fields (text anchors, coordinates, or manual placement). If it reads text anchors, map the white tags to its syntax first.
- Do a dry run that shows the field positions. Then create a **draft**, or a one-signer proof to the approver. Send only on an explicit "send" for that document.
- Know what your tool does at each step: a "draft" in some tools still emails the signer.
- Cancel the old request before you send a corrected one.
- Some connectors build an envelope only from a template or from a public URL. Do not put a confidential file at a public URL.

## Inputs you must not rebuild

- **A third party's Word file**: convert it faithfully with LibreOffice (`soffice --headless --convert-to pdf`). pandoc and macOS QuickLook reflow it and move signature lines. Find the signature lines with `pdftotext -bbox` and place e-sign fields by coordinates.
- **Government or registry forms**: the preparer's system is the record. Ask them to fix errors at source. Place a signature field by coordinates on the officeholder page only.

## Record

- File the executed copy as `... - EXECUTED.pdf` beside the source.
- Sensitive matters (HR, personal): keep the case folder git-ignored, confirm with `git check-ignore`, and back it up to private storage you control after each version and before any worktree cleanup.
