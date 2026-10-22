# Change an answer on a flattened third-party PDF form

Use this when a third-party form (an insurer proposal, a government print) needs one answer changed and has
no fillable fields. Never rebuild the form: change only the answer, then prove nothing else moved.

1. **Check for fields first.** `pymupdf`: `len(list(page.widgets()))` on every page. If the form has fields,
   fill them instead of drawing text.
2. **Find the old value** with `page.get_text("words")` (points, top-left origin). Note the cell's x range,
   so the new text fits inside it.
3. **Remove the old value with a true redaction**, not a white box. A white box hides the old text on paper,
   but it stays in the text layer, where a copy-paste or a text search still finds it:
   ```python
   page.add_redact_annot(rect, fill=(1, 1, 1))
   page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
   ```
   Keep `images` and `graphics` at NONE so the form's lines and logos stay.
4. **Write the new value** with `page.insert_text(...)` (font `helv`, a size that fits the cell; two short
   lines are fine). Save to a NEW file name (`..._3.pdf`); never overwrite the original.
5. **Prove it:**
   - `page.get_text("words")` in the cell shows only the new value.
   - A page render (`get_pixmap` or `pdftoppm`) looks right. Read it.
   - `pdftotext -layout` of the old and new packs, then `diff`: only the intended lines differ (spacing shifts
     on the same page are noise). Page count is unchanged.
6. **Say what changed** in the hand-over: page, question, old value, new value.

## A form WITH fillable fields

- **Not every viewer prints the answers.** A form filled in Preview can hold its Yes/No radios as form data that Poppler
  (`pdftoppm`) leaves blank. Before sending for signature, **flatten** it with `doc.bake()`, so every answer becomes
  page content and prints everywhere.
- **Change a radio by its state, not `widget.update()`.** `update()` drew a second tick and left the old one, so both
  Yes and No printed after baking. Set the chosen widget's `/AS` to its on-state, the others' `/AS` to `/Off`, and the
  parent's `/V`, with `doc.xref_set_key(...)`, then bake.
- **One radio group can span two rows** (a form bug: two questions share a field name, so ticking one clears the
  other). Read the field names by position before trusting a blank answer.
- **To add a tick, draw a filled shape** the size of the form's own mark (`page.draw_rect(..., fill=(0, 0, 0))`).
  A symbol-font character (ZapfDingbats "n", not embedded) printed as the letter "n" in Poppler.
- **Check in two renderers**, Poppler and MuPDF, at 150 dpi or more. At 70 dpi a small tick can vanish from the
  render, which looks like a missing answer.
- **Do these checks BEFORE you send the form for signature**, never first after it is signed. Render every
  edited page in both renderers, and run `pdffonts <file>`: a symbol font with `emb` = `no` (for example
  ZapfDingbats) is a fault to fix first. Once the "n" tick was found only after signing, so the signer had
  to sign twice.

Dependency: `pymupdf` (pip; not in the system Python on every machine, so use a venv). Note that PyMuPDF is licensed AGPL-3.0 (with a commercial option from its vendor): this skill only describes how to call it, and bundles none of its code. Check that licence fits your use before you install it, or use another library such as `pypdf` for the steps that allow it.
