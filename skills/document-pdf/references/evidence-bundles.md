# Evidence bundles and exhibit packs

Use this for a claim letter with exhibits, a dispute pack, an auditor's evidence set, or a bank or KYC document pack.

## Shape

- **Letter first.** `00-<claim-letter>.pdf`, built with this skill like any other document. It ends with an exhibit list that names every file.
- **One exhibit per fact.** `E01-<kebab-description>.pdf`, `E02-...`. One email, receipt or record per exhibit, in time order.
- **Check how the recipient takes files.** Some portals take one file per upload. Merge into a single bundle only when the recipient wants one file.

## Building an exhibit from an email

- Print a header block: From, To, Cc, Date, Subject, and the message ID.
- Under the Date, add the local time where the event happened ("= 10:27 on 5 May 2031, local time at the event (UTC+2)"). Use the correct daylight-saving offset for that date.
- Body as plain text. Replace a long tracking link with "[long link removed]", but keep any short link that carries a reference number.
- Put the original attachments after the email printout. Keep their original pages: `pdfunite email.pdf attach1.pdf attach2.pdf E01-....pdf` (poppler), or `pypdf`. Do not re-render an original document.
- Footer on every page: "Exhibit E0x - <matter> - page n".

## Redaction

- Redact what the recipient does not need: PINs, card numbers, home addresses, phone numbers, other people's details.
- Write the redaction in the text ("[PIN redacted]"). The verify gate accepts a bracket that ends in "redacted]" or "removed]" as a deliberate note, not a placeholder. A black box over text can leave the text selectable underneath.
- Check with the gate: `--forbid "<the PIN>" "<the phone number>"`, so the build fails if one leaks.

## Verify the pack

- Gate the email printout on its own (full checks, `--size A4`) BEFORE you merge it with the attachments.
- Then gate each merged exhibit with `--allow-mixed-sizes`, because original pages keep their own size (a US Letter receipt, a phone scan). Set `--expect` to the reference numbers that exhibit must show (booking reference, invoice number, amount).
- Run `pdfinfo` on each exhibit to get the page counts. List those counts in the exhibit index.
- Look at every page of every exhibit (render with the gate's `--png-dir`).
- New revision, new folder (`final-v2/`). Never mix versions in one folder.

## Auditor or regulator sets

- Cover page and index first (`00-index.pdf`), then the exhibits, in the order the index lists them.
- Run a date audit: a script that pulls every date from every PDF and checks each one against the source records.
