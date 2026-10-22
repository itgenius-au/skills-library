#!/usr/bin/env python3
"""Verify gate for a document PDF. Run it on EVERY build, before anyone sees the file.

    verify_pdf.py <file.pdf> [--profile general|signing] [--expect TOKEN ...]
                  [--forbid TOKEN ...] [--pages N] [--size A4|Letter] [--png-dir DIR]
                  [--allow TOKEN ...] [--allow-brackets] [--allow-mixed-sizes]
                  (--expect, --forbid and --allow repeat)

Checks (needs poppler: pdfinfo, pdftotext, pdftoppm):
  1. Page count, and the size of EVERY page (pdfinfo); mixed sizes fail, unless
     --allow-mixed-sizes (a merged exhibit that keeps original pages).
  2. Every --expect token is present: names, amounts, dates, reference numbers.
     Text is whitespace-collapsed first, so a phrase wrapped across lines still matches.
  3. No forbidden text. Both profiles: TODO, TBC, template braces, lorem ipsum, plus any
     --forbid tokens. The signing profile adds DRAFT, "not legal advice", CONFIRM and
     INTERNAL, because a document that gets signed must be final.
  4. No open [square-bracket] placeholders, even wrapped across lines. Exempt: valid
     e-sign text tags, "[sic]", a year followed by a law-report code ("[2019] EWCA"),
     a bare footnote "[1]" (general profile only), and annotations ending
     "redacted]" or "removed]". A malformed
     tag such as [sig|req|signer1x] counts as a placeholder.
  5. E-sign signer tags (when present) run signer1..signerN with no gap and no signer0.
  6. Signing profile: warns when the last page holds little but a signature block
     (heuristic only; the PNG look in step 7 is the real check).
  7. Renders every page to PNG (--png-dir) so the agent can LOOK at each page.
Exit 0 = pass (warnings may print), 1 = fail.
"""
import argparse
import os
import re
import subprocess
import sys

GENERAL_FORBID = ["TODO", "TBC", "{{", "}}", "lorem ipsum"]
SIGNING_FORBID = GENERAL_FORBID + ["DRAFT", "not legal advice", "CONFIRM", "INTERNAL"]
PROFILES = {"general": GENERAL_FORBID, "signing": SIGNING_FORBID}
# E-sign text tags (this skill's anchor convention): [type|req|signerN|Label|UniqueId].
# Adjust this pattern if your e-sign tool uses a different tag syntax.
# Only a text-merge tag may name the sender; [sig|req|sender] is malformed.
ESIGN_TAG = re.compile(
    r"\[(?:(?:sig|date|initial|text|check)\|(?:req|noreq)\|signer(?P<n>\d+)"
    r"|text-merge\|(?:req|noreq)\|(?:signer(?P<m>\d+)|sender))(?:\|[^\]]*)?\]", re.I)


def tag_signer(m):
    """Signer number of a matched tag, or None for a sender text-merge tag."""
    num = m.group("n") or m.group("m")
    return int(num) if num is not None else None
BRACKET = re.compile(r"\[[^\[\]]{0,200}\]")  # spans line wraps; [] counts too
ANNOTATION = re.compile(r"(redacted|removed)\s*\]$", re.I)  # "[PIN redacted]", "[long link removed]" are deliberate
# Brackets that are not open terms. A bare number or year in brackets IS an open term in
# a draft ("within [30] days", "dated [2026]"), so citations need their context:
SIC = re.compile(r"^\[sic\]$", re.I)
YEAR = re.compile(r"^\[(19|20)\d{2}\]$")
# A full citation on the SAME line: optional volume, a report code (mixed case allowed:
# EWCA Civ, Ch, Fam, All ER, Lloyd's Rep), then a page number. "[2026]\nBETWEEN" is not one.
LAW_REPORT_AFTER = re.compile(r"^[ \t]+(\d+[ \t]+)?[A-Z][A-Za-z.']*([ \t]+[A-Z][A-Za-z.']*)*[ \t]+\d+")
NUMBER_REF = re.compile(r"^\[\d{1,3}\]$")  # "[1]" footnote style, general profile only
SIZES = {"A4": (595, 842), "Letter": (612, 792)}


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def find_missing(text, tokens):
    t = norm(text).lower()
    return [k for k in tokens if norm(k).lower() not in t]


def _word_pattern(k):
    """Marker words match as whole words. TBC in any case. TODO in caps anywhere, and
    lower/title case only as a note ("todo:"), because "todo" is ordinary Spanish
    ("all"); a Spanish source with "TODO EL ..." headings uses --allow TODO. DRAFT in
    caps or title case (the verb "draft" is fine). Other all-caps tokens (CONFIRM,
    INTERNAL) in caps only, because "confirm" and "internal" are ordinary words."""
    if k == "TBC":
        return re.compile(r"\bTBC\b", re.I)
    if k == "TODO":
        return re.compile(r"\bTODO\b|\b[Tt]odo\s*:")
    if k == "DRAFT":
        return re.compile(r"\b(DRAFT|Draft)\b")
    if k.isupper() and k.isalpha():
        return re.compile(r"\b" + re.escape(k) + r"\b")
    return None


def find_forbidden(text, tokens, strip_tags=True):
    t = norm(ESIGN_TAG.sub(" ", text) if strip_tags else text)
    hits = []
    for k in tokens:
        pat = _word_pattern(k)
        if (pat.search(t) if pat else norm(k).lower() in t.lower()):
            hits.append(k)
    return hits


def open_placeholders(text, profile="general"):
    """Open [bracket] terms. Exempt: e-sign tags, "[... redacted]"/"[... removed]" notes,
    "[sic]", a year followed by a law-report code ("[2019] EWCA Civ 1"), and in the
    general profile only a bare footnote number ("[1]")."""
    t = ESIGN_TAG.sub(" ", text)
    hits = set()
    for m in BRACKET.finditer(t):
        b = norm(m.group(0))
        if ANNOTATION.search(b) or SIC.match(b):
            continue
        if YEAR.match(b) and LAW_REPORT_AFTER.match(t[m.end():m.end() + 40]):
            continue
        if profile == "general" and NUMBER_REF.match(b):
            continue
        hits.add(b)
    return sorted(hits)


def signer_gaps(text):
    """Return (signer numbers, missing numbers, invalid numbers such as signer0)."""
    nums = sorted({n for n in (tag_signer(m) for m in ESIGN_TAG.finditer(text)) if n is not None})
    if not nums:
        return [], [], []
    missing = [n for n in range(1, max(nums) + 1) if n not in nums]
    return nums, missing, [n for n in nums if n < 1]


def page_size_name(w, h):
    w, h = sorted((w, h))  # landscape A4 is still A4
    for name, (sw, sh) in SIZES.items():
        if abs(w - sw) <= 3 and abs(h - sh) <= 3:
            return name
    return f"{w:.0f}x{h:.0f}pt"


def pdfinfo(path):
    """Return (page count, sorted set of page-size names across ALL pages)."""
    out = subprocess.run(["pdfinfo", path], check=True, capture_output=True, text=True).stdout
    pages = int(re.search(r"^Pages:\s+(\d+)", out, re.M).group(1))
    per_page = subprocess.run(["pdfinfo", "-f", "1", "-l", str(pages), path],
                              check=True, capture_output=True, text=True).stdout
    sizes = {page_size_name(float(w), float(h))
             for w, h in re.findall(r"^Page\s+\d+ size:\s+([\d.]+) x ([\d.]+)", per_page, re.M)}
    if not sizes:
        m = re.search(r"^Page size:\s+([\d.]+) x ([\d.]+)", out, re.M)
        sizes = {page_size_name(float(m.group(1)), float(m.group(2)))}
    return pages, sorted(sizes)


def page_text(path, page):
    # Reading order, not -layout: -layout puts side-by-side columns on one line,
    # which splices a wrapped phrase in one cell with text from the next cell.
    return subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), path, "-"],
                          check=True, capture_output=True, text=True).stdout


def render_pngs(pdf, png_dir):
    """Render every page; first delete this PDF's images from an earlier run, so the
    folder holds only the pages of the file being checked."""
    os.makedirs(png_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(pdf))[0]
    old = re.compile(re.escape(name) + r"-\d+\.png$")
    for f in os.listdir(png_dir):
        if old.match(f):
            os.remove(os.path.join(png_dir, f))
    subprocess.run(["pdftoppm", "-r", "70", "-png", pdf, os.path.join(png_dir, name)], check=True)
    return sorted(os.path.join(png_dir, f) for f in os.listdir(png_dir) if old.match(f))


def orphaned_execution_page(last_text):
    words = len(norm(ESIGN_TAG.sub(" ", last_text)).split())
    return words < 40 and re.search(r"signature|executed|signed by", last_text, re.I) is not None


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--expect", nargs="+", action="extend", default=[], help="repeatable")
    ap.add_argument("--forbid", nargs="+", action="extend", default=[], help="repeatable")
    ap.add_argument("--allow", nargs="+", action="extend", default=[], choices=sorted(set(SIGNING_FORBID)),
                    help="waive a built-in marker for this document, e.g. --allow TODO for a Spanish source")
    ap.add_argument("--allow-mixed-sizes", action="store_true",
                    help="a merged exhibit that keeps original pages of other sizes; skips the size checks")
    ap.add_argument("--pages", type=int)
    ap.add_argument("--size", choices=list(SIZES))
    ap.add_argument("--profile", choices=list(PROFILES), default="general",
                    help="signing = a document people will sign: strict final-text checks")
    ap.add_argument("--png-dir")
    ap.add_argument("--allow-brackets", action="store_true", help="square brackets are deliberate fill-by-hand blanks")
    return ap


def main(argv=None):
    a = parser().parse_args(argv)

    fails, warns = [], []
    pages, sizes = pdfinfo(a.pdf)
    texts = [page_text(a.pdf, p) for p in range(1, pages + 1)]
    full = "\n".join(texts)
    print(f"{a.pdf}: {pages} page(s), {'/'.join(sizes)}")

    if a.pages and pages != a.pages:
        fails.append(f"page count {pages}, expected {a.pages}")
    if a.allow_mixed_sizes:
        if len(sizes) > 1:
            warns.append(f"mixed page sizes allowed: {sizes}")
    else:
        if len(sizes) > 1:
            fails.append(f"mixed page sizes: {sizes}")
        if a.size and sizes != [a.size]:
            fails.append(f"page size {sizes}, expected {a.size}")
    miss = find_missing(full, a.expect)
    if miss:
        fails.append(f"expected text missing: {miss}")
    builtin = [k for k in PROFILES[a.profile] if k not in a.allow]
    if a.allow:
        warns.append(f"built-in markers waived: {a.allow}")
    bad = find_forbidden(full, builtin) + find_forbidden(full, a.forbid, strip_tags=False)
    if bad:
        fails.append(f"forbidden text present: {bad}")
    ph = open_placeholders(full, a.profile)
    if ph:
        (warns if a.allow_brackets else fails).append(f"open placeholders: {ph}")
    nums, gaps, invalid = signer_gaps(full)
    if invalid:
        fails.append(f"e-sign signer numbers must start at 1: found {invalid}")
    elif gaps:
        fails.append(f"e-sign signers not contiguous: have {nums}, missing {gaps}")
    elif nums:
        print(f"e-sign signers: signer1..signer{max(nums)}")
    if a.profile == "signing" and pages > 1 and orphaned_execution_page(texts[-1]):
        warns.append("last page holds little but a signature block: pull it up with the clause before it")
    if not full.strip():
        fails.append("no extractable text (scanned image or broken render)")

    if a.png_dir:
        pngs = render_pngs(a.pdf, a.png_dir)
        if len(pngs) != pages:
            fails.append(f"rendered {len(pngs)} page images for {pages} pages")
        print(f"page images ({len(pngs)}): open EVERY one and look before you share")
        for p in pngs:
            print("  " + p)

    for w in warns:
        print("WARN", w)
    for f in fails:
        print("FAIL", f)
    print("RESULT", "FAIL" if fails else "PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
