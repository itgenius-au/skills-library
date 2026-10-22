#!/usr/bin/env python3
"""Build a document PDF (report, memo, letter, agreement...) from one canonical Markdown source.

    build_pdf.py <input.md> [output.pdf] [--engine auto|weasyprint|chrome]
                       [--css extra.css] [--letter] [--no-page-numbers] [--keep-html]

Markdown -> HTML: pandoc (gfm, raw HTML passes through) when on PATH, else the
python-markdown package. HTML -> PDF: WeasyPrint when importable or on PATH,
else Chrome / Chromium headless (Mac app, PATH, or a Playwright cache). In auto
mode a failed WeasyPrint run falls back to Chrome. Both print the CSS
"Page X of Y" footer (Chrome needs version 131 or later). Relative image and
link paths resolve against the source file's folder. Works on macOS and Linux.
Prints the engine used and the output path; exits non-zero on any failure, so a
caller can gate on it.
"""
import argparse
import glob
import html
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
HOUSE_CSS = os.path.join(HERE, "..", "assets", "house-print.css")

CHROME_CANDIDATES = [
    os.environ.get("CHROME_BIN", ""),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
]
CHROME_GLOBS = [
    "/opt/pw-browsers/chromium*/chrome-linux*/chrome",
    os.path.expanduser("~/.cache/ms-playwright/chromium*/chrome-linux*/chrome"),
    os.path.expanduser("~/Library/Caches/ms-playwright/chromium*/chrome-mac*/Google Chrome for Testing.app"
                       "/Contents/MacOS/Google Chrome for Testing"),
    os.path.expanduser("~/Library/Caches/ms-playwright/chromium*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium"),
]


class BuildError(Exception):
    pass


def find_chrome():
    for c in CHROME_CANDIDATES:
        if not c:
            continue
        path = c if os.path.isabs(c) else shutil.which(c)
        if path and os.path.exists(path):
            return path
    for pattern in CHROME_GLOBS:
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return None


def have_weasyprint():
    try:
        import weasyprint  # noqa: F401
        return "module"
    except Exception:
        return "cli" if shutil.which("weasyprint") else None


def is_pdf(path):
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        return False
    with open(path, "rb") as f:
        return f.read(5) == b"%PDF-"


def md_body(md_path):
    if shutil.which("pandoc"):
        return subprocess.run(
            ["pandoc", "--from", "gfm", "--to", "html5", md_path],
            check=True, capture_output=True, text=True,
        ).stdout
    try:
        import markdown
    except ImportError:
        raise BuildError("No Markdown converter: install pandoc, or pip install markdown")
    text = open(md_path, encoding="utf-8").read()
    return markdown.markdown(mark_html_blocks(text),
                             extensions=["tables", "sane_lists", "md_in_html", "fenced_code"])


# A raw HTML block starts at column 0-3; 4+ spaces or a tab is an indented code block.
RAW_BLOCK = re.compile(r"^( {0,3})<(div|td)(?![^>]*\bmarkdown=)([^>]*)>")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def mark_html_blocks(text):
    """python-markdown parses Markdown inside a raw HTML block only when the block
    carries markdown="1" (md_in_html); pandoc does this by default. Add the attribute
    to <div>/<td> tags that open a line, and leave code alone: fenced code (a fence
    closes only on the same character, at least as long as the opener) and indented
    code lines."""
    out, fence = [], None
    for line in text.splitlines(keepends=True):
        m = FENCE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
            else:
                line = RAW_BLOCK.sub(r'\1<\2 markdown="1"\3>', line)
        elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                and not line.strip()[len(m.group(1)):].strip():
            fence = None
        out.append(line)
    return "".join(out)


def md_to_html(md_path, css_paths, title):
    """Return a standalone HTML string. CSS files are linked by absolute file URI,
    so url() paths inside each file resolve from that file's own folder. A <base>
    at the source folder makes relative images and links resolve from there."""
    base = Path(os.path.dirname(os.path.abspath(md_path))).as_uri() + "/"
    links = "".join(
        f"<link rel=\"stylesheet\" href=\"{html.escape(Path(os.path.abspath(p)).as_uri(), quote=True)}\">"
        for p in css_paths)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<base href=\"{html.escape(base, quote=True)}\">"
        f"<title>{html.escape(title)}</title>{links}</head>"
        f"<body>{md_body(md_path)}</body></html>"
    )


def render_weasyprint(html_path, out_pdf, mode):
    if mode == "module":
        import weasyprint
        weasyprint.HTML(filename=html_path).write_pdf(out_pdf)
    else:
        subprocess.run(["weasyprint", html_path, out_pdf], check=True)
    if not is_pdf(out_pdf):
        raise BuildError("WeasyPrint wrote no valid PDF")


def _stop(proc):
    if proc.poll() is not None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


def render_chrome(chrome, html_path, out_pdf, timeout=90):
    """Chrome on macOS can write the PDF and then never exit, so treat a valid PDF
    whose size is stable for 2 s as done, then stop our own process group.
    Any other ending (non-zero exit, timeout, not a PDF) is a failure."""
    work = tempfile.mkdtemp(prefix="docpdf-chrome-")
    if os.path.exists(out_pdf):
        os.remove(out_pdf)
    cmd = [
        chrome, "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
        f"--user-data-dir={os.path.join(work, 'profile')}", "--no-pdf-header-footer",
        f"--print-to-pdf={out_pdf}", Path(html_path).absolute().as_uri(),
    ]
    proc = None
    try:
        with open(os.path.join(work, "chrome.log"), "w") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            last, stable, done = -1, 0, False
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                time.sleep(1)
                rc = proc.poll()
                if rc is not None:
                    if rc != 0:
                        raise BuildError(f"Chrome exited {rc}")
                    done = True
                    break
                if is_pdf(out_pdf):
                    size = os.path.getsize(out_pdf)
                    stable = stable + 1 if size == last else 0
                    last = size
                    if stable >= 2:
                        done = True
                        break
            if not done:
                raise BuildError(f"Chrome timed out after {timeout}s")
    finally:
        if proc is not None:
            _stop(proc)
        shutil.rmtree(work, ignore_errors=True)
    if not is_pdf(out_pdf):
        raise BuildError("Chrome wrote no valid PDF")


def build(a):
    src = os.path.abspath(a.input)
    if not src.endswith(".md") or not os.path.exists(src):
        raise BuildError(f"Input must be an existing .md file: {a.input}")
    out = os.path.abspath(a.output or src[:-3] + ".pdf")
    if not out.lower().endswith(".pdf"):
        raise BuildError(f"Output must end in .pdf: {out}")
    if os.path.realpath(out) == os.path.realpath(src):
        raise BuildError("Output path is the source file; refusing to overwrite it")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)  # a failed build must never leave the previous PDF to be checked or sent
    for p in a.css:
        if not os.path.exists(p):
            raise BuildError(f"CSS file not found: {p}")

    work = tempfile.mkdtemp(prefix="docpdf-")
    try:
        css = [HOUSE_CSS]
        overrides = []
        if a.letter:
            overrides.append("@page { size: Letter; }")
        if a.no_page_numbers:
            overrides.append("@page { @bottom-right { content: none; } }")
        if overrides:
            p = os.path.join(work, "overrides.css")
            with open(p, "w") as f:
                f.write("\n".join(overrides))
            css.append(p)
        css += [os.path.abspath(c) for c in a.css]

        title = os.path.splitext(os.path.basename(out))[0]
        html_path = os.path.join(work, "document.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(md_to_html(src, css, title))

        wp, chrome = have_weasyprint(), find_chrome()
        if a.engine == "weasyprint" and not wp:
            raise BuildError("WeasyPrint not available (pip install weasyprint; Linux also needs libpangoft2)")
        if a.engine == "chrome" and not chrome:
            raise BuildError("No Chrome/Chromium found (set CHROME_BIN)")
        order = [a.engine] if a.engine != "auto" else [e for e, ok in (("weasyprint", wp), ("chrome", chrome)) if ok]
        if not order:
            raise BuildError("No PDF engine: install WeasyPrint, or Chrome/Chromium (see references/toolchain.md)")

        errors = []
        for engine in order:
            try:
                if engine == "weasyprint":
                    render_weasyprint(html_path, out, wp)
                else:
                    render_chrome(chrome, html_path, out)
                break
            except Exception as e:  # try the next engine in auto mode
                errors.append(f"{engine}: {e}")
                if os.path.exists(out):
                    os.remove(out)
        else:
            raise BuildError("; ".join(errors))

        if a.keep_html:
            shutil.copy(html_path, out[:-4] + ".html")
        fallback = f" (after: {'; '.join(errors)})" if errors else ""
        print(f"OK engine={engine} {out} ({os.path.getsize(out)} bytes){fallback}")
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--engine", choices=["auto", "weasyprint", "chrome"], default="auto")
    ap.add_argument("--css", action="append", default=[], help="extra CSS file, applied after the default CSS")
    ap.add_argument("--letter", action="store_true", help="US Letter instead of A4")
    ap.add_argument("--no-page-numbers", action="store_true")
    ap.add_argument("--keep-html", action="store_true", help="keep the intermediate HTML beside the PDF")
    a = ap.parse_args(argv)
    try:
        return build(a)
    except (BuildError, subprocess.CalledProcessError) as e:
        sys.exit(f"BUILD FAILED: {e}")


if __name__ == "__main__":
    main()
