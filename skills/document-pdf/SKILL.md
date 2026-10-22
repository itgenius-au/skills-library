---
name: document-pdf
description: "Make a checked PDF from one Markdown source: reports, memos, letters, statements, translations, agreements, deeds, resolutions, claim letters and evidence bundles. Builds on macOS or Linux, runs a verify gate (facts present, no placeholders, page size, a look at every page), and hands over a draft, never a send. A signing profile adds strict final-text checks, execution blocks and review. Use it WHENEVER you produce, rebuild or re-version a PDF, even for 'make it a PDF'. Not for editing existing PDFs (use a PDF editing skill or tool). Triggers on: make it a pdf, generate a pdf, export to pdf, pdf report, pdf memo, pdf letter, re-render the pdf, new pdf to check, printable copy, legal pdf, pdf for signing, signature-ready pdf, draft the agreement, draft a deed, separation agreement, board resolution, sale contract, claim letter, evidence bundle, exhibits, bilingual pdf, convert the docx to pdf."
---

# Document PDF

Make PDF documents the same way every time: one Markdown source, one build command, one verify gate, then a draft hand-off. The method comes from many real document sessions: reports, memos, translations, letters, contracts, deeds and evidence packs. Each rule fixes a fault that reached the reader at least once.

## Five rules

1. **One canonical source.** Write the document as Markdown in a durable place. Never keep hand-edited HTML as the only copy. A cleared scratchpad once lost the only source.
2. **Re-render, never re-send.** Every "new PDF" is a fresh build of the current source. Never copy an older PDF. A stale PDF once went out without the latest edits.
3. **Gate every build.** Run the verify script on every PDF, before anyone sees it.
4. **Look at every page.** Text checks miss layout faults. Render the pages to PNG and look at them yourself. A subagent's "it built" is not a layout check.
5. **Draft, don't send.** You prepare the file, the email draft or the e-sign draft. The requester sends, or gives an explicit "send" for that document.

## Workflow

### Step 1: Intake

Ask once, in one message, and mark what you inferred:

- **Purpose and reader**: one line.
- **Key facts**: names, amounts, dates, reference numbers. These become the gate's `--expect` tokens.
- **Will anyone sign it?** If yes, also read [references/signing-documents.md](references/signing-documents.md) now. It adds intake, drafting rules, execution blocks and review.
- **Confidentiality**: ordinary, or sensitive (HR, personal, deal terms).
- **Delivery**: chat, a shared folder, email draft, e-sign, or a portal.
- **A precedent**, if one exists. A previous document of the same kind beats a blank page.

### Step 2: Put the source in the right place

| Class | Source | PDFs |
|---|---|---|
| Ordinary | The owning repo, `docs/<area>/YYYY-MM-DD-<topic>.md` (committed) | `pdf/` beside the source, git-ignored |
| Sensitive | A git-ignored case folder in the repo (for example `.case/`), backed up to private storage you control | The same folder |

- Confirm the ignore rule with `git check-ignore <path>` before the first build.
- Keep build helper scripts in the scratchpad, never beside sensitive files.
- Keep working notes in a separate `NOTES.md`, or in HTML comments (`<!-- ... -->`), which the renderer drops.

### Step 3: Write the Markdown

- Headings, numbered lists and pipe tables render as styled HTML. Tables get borders and a shaded header row.
- Raw HTML passes through for layout the Markdown cannot express: `<div class="pagebreak"></div>`, `<div class="keep">...</div>` (keep together), `<table class="bilingual">` (two-language rows).
- Avoid emoji; they often drop out. Check special glyphs (€, ☑, accents) in the page images.
- A matter-specific look goes in an extra CSS file (`--css`), not in an edited default stylesheet.

### Step 4: Build

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/build_pdf.py" <source.md> <out.pdf>
```

- Engine order: WeasyPrint, then Chrome/Chromium headless (Mac app, PATH, or the Playwright cache). If WeasyPrint fails, auto mode falls back to Chrome. `--engine` forces one.
- The default is A4 with "Page X of Y" in the footer. `--letter` gives US Letter. `--no-page-numbers` removes the footer.
- Relative image paths resolve from the source file's folder.
- No engine? Read [references/toolchain.md](references/toolchain.md) for setup per OS and the known gotchas.
- **Name by version**: `<Title> - v<N>.pdf`. Never overwrite a version someone has already seen. In a pack, prefix files `00-`, `01-`... in reading or signing order.

### Step 5: Verify gate (every build)

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/verify_pdf.py" <out.pdf> --expect "<fact 1>" "<fact 2>" \
  --size A4 --png-dir <scratch>/png                 # add --profile signing for a document that gets signed
```

- **Both profiles fail on:** a missing `--expect` token, `TODO` / `TBC` / template braces, open `[placeholders]`, an e-sign signer gap, mixed page sizes, or a wrong page size or count.
- **`--profile signing` also fails on:** `DRAFT` or "Draft", "not legal advice", `CONFIRM` and `INTERNAL`. It also warns about a signature-only last page.
- Pass single, distinctive tokens to `--expect`, such as an amount or a reference number. `--expect` and `--forbid` can repeat.
- Not placeholders: `[sic]`, a case citation (`[2019] EWCA Civ 1`), and in the general profile a footnote number (`[1]`). Any other bracketed text is, including "within [30] days" or "dated [2026]" in a document that gets signed.
- A built-in marker that is a real word in your document (for example a Spanish heading "TODO EL CONTRATO", or "todo: ...") can be waived for that run with `--allow TODO`. The gate prints the waiver as a warning.
- Then **open every PNG** with the Read tool. Check for clipped text, missing glyphs, tables that split badly, and blocks that land on a page of their own.
- Fix the source, rebuild and re-run the gate. Never patch the PDF.

### Step 6: Review (scale to the stakes)

- **A document that gets signed**: follow the review in [references/signing-documents.md](references/signing-documents.md).
- **Numbers that someone will act on** (tax, billing, a register): one independent check of the figures against the source records before you share the PDF.
- **Everything else**: your own read of the page images is enough.

### Step 7: Deliver (draft, don't send)

- **Shared drive or folder**: upload a new file for each version. Some services keep a cached preview of the first upload when you update a file in place, so readers see old text. Compare a checksum of the uploaded file with the local one.
- **Email**: create a draft (not a sent message) with the PDF attached. Read the draft back and check the attachment byte for byte.
- **E-sign**: see [references/signing-documents.md](references/signing-documents.md).
- **Report in chat**: files, version, page count, gate result, and what is waiting on whom.

## Other inputs

- **Evidence bundles and exhibit packs** (claims, disputes, KYC, auditors): [references/evidence-bundles.md](references/evidence-bundles.md).
- **A third party's Word file, or a government form**: never rebuild it. See "Inputs you must not rebuild" in [references/signing-documents.md](references/signing-documents.md).
- **Editing an existing PDF** (merge, split, fill a form, extract): use a PDF editing skill or tool. Merging exhibits is covered in the evidence-bundles reference. To change an answer on a flattened third-party form (no fillable fields), follow [references/edit-existing-pdf.md](references/edit-existing-pdf.md).

## Why each rule exists

[references/lessons.md](references/lessons.md) lists the faults from past sessions and the rule each one created. Read it before you relax a rule.
