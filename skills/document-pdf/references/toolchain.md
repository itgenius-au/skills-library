# Toolchain: setup and gotchas

## Probe first

```bash
which pandoc weasyprint soffice pdfinfo pdftotext pdftoppm pdfunite
python3 -c "import weasyprint" ; python3 -c "import markdown"
ls ~/.cache/ms-playwright /opt/pw-browsers 2>/dev/null
```

`build_pdf.py` needs one Markdown converter (pandoc, or the `markdown` Python package) and one engine (WeasyPrint, or Chrome/Chromium). `verify_pdf.py` needs poppler (`pdfinfo`, `pdftotext`, `pdftoppm`).

## Setup per OS

| OS | Converter | Engine | Poppler |
|---|---|---|---|
| macOS | `brew install pandoc` | Google Chrome app (found automatically), or `brew install pango` then WeasyPrint in a venv | `brew install poppler` |
| Linux (Debian/Ubuntu) | `sudo apt-get install pandoc` | `sudo apt-get install libpangoft2-1.0-0` then WeasyPrint in a venv; or `pip install playwright && playwright install --with-deps chromium` | `sudo apt-get install poppler-utils` |

Make the venv outside the case folder:

```bash
python3 -m venv ~/.venvs/document-pdf && ~/.venvs/document-pdf/bin/pip install weasyprint markdown pypdf
~/.venvs/document-pdf/bin/python "${CLAUDE_SKILL_DIR}/scripts/build_pdf.py" in.md out.pdf
```

## Gotchas (each one cost a session time)

- **WeasyPrint on Linux** imports, then fails with `cannot load library 'libpangoft2-1.0-0'`. Install the system package above. On macOS it needs `brew install pango`, and sometimes `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`.
- **`pip install` refused** (PEP 668, "externally managed environment"). Use a venv. Do not use `--break-system-packages`.
- **`python3 -I` hides user-installed packages.** Use `-I` for scripts that read untrusted files, but run venv scripts with the venv's own `python`.
- **Chrome headless on macOS writes the PDF and then never exits.** The builder polls for a stable file and kills only its own profile. `--headless=new` with `--virtual-time-budget` once wrote nothing, so the builder uses plain `--headless`.
- **Chrome adds a URL and date header/footer** unless `--no-pdf-header-footer` is set. The builder sets it. The CSS footer ("Page X of Y") still prints in Chrome 131 and later.
- **pandoc prints the file name as a heading** if you pass `--metadata title`. The builder sets the HTML `<title>` itself.
- **pandoc to `.docx`** loses the signature-box layout. Ship the PDF as the signable file. Offer Word only as an editable copy.
- **A third party's `.docx`**: convert with `soffice --headless -env:UserInstallation=file:///tmp/lo_profile_$$ --convert-to pdf --outdir <dir> <file.docx>`. The separate profile stops a running LibreOffice from blocking the job. QuickLook (`qlmanage`) and pandoc reflow the layout. Do not use them for this.
- **Glyphs**: core Helvetica in fpdf/reportlab has no €, ☑ or non-Latin letters. The HTML engines use system fonts. Check those characters in the PNGs. Emoji often drop out, so remove them from the source.
- **fpdf2** (last resort only): never call `multi_cell(0, ...)` after `set_x(indent)`. Pass an explicit width. Use a DejaVu TTF for Unicode.
- **Some upload CLIs reject a path outside the current directory.** Build inside the working folder, then upload with a relative path.
- **Cloud-drive in-place updates** keep the link, but the web viewer may show the cached preview of the first upload. Compare the stored checksum with the local file. Upload a new file if a reader still sees old text.
- **Long tool parameters**: a large PDF can be too big to pass inline to an MCP tool. Attach it from disk with a script instead.
