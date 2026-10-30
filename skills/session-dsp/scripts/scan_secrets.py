#!/usr/bin/env python3
"""Scan what a session wrap or a squash is about to commit or push for leaked secrets.

Auto mode scans what a push publishes: each commit not yet on a remote, plus anything staged. A push
carries every commit, so a value added in one commit and removed in the next still counts, and so does
a value added while resolving a merge (that read needs a recent git; on an older one the scan exits 1, it
never reports clean). Lines already on a remote (for example a merged main) do not. With --base, it scans
the lines ADDED between that commit and the index, which is what a squash to it would commit. Prints each
finding with the secret masked, so the value never lands in a transcript.

    python3 scan_secrets.py                 # base = upstream, else merge-base with origin's default branch
                                            # (neither found: exit 1, pass --base)
    python3 scan_secrets.py --base <rev>    # e.g. the squash window's LAST_NONWIP (see SKILL.md)

Exit codes: 0 clean, 2 secret(s) found (stop: do not commit or push), 1 the scan could not run.

To keep a line that is a known false positive, add `secret-scan: allow` to that line.
Python 3 standard library only.
"""
import argparse
import re
import subprocess
import sys

# High-signal patterns: name -> regex.
PATTERNS = [
    ("Private key block", r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    ("Google API key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("Google OAuth client secret", r"GOCSPX-[0-9A-Za-z_\-]{10,}"),
    ("Google OAuth refresh token", r"\b1//[0-9A-Za-z_\-]{25,}"),
    ("Google access token", r"\bya29\.[0-9A-Za-z_\-]{20,}"),
    ("AWS access key id", r"\bAKIA[0-9A-Z]{16}\b"),
    ("GitHub token", r"\bgh[pousr]_[0-9A-Za-z]{20,}"),
    ("GitHub fine-grained token", r"\bgithub_pat_[0-9A-Za-z_]{20,}"),
    ("Slack token", r"\bxox[baprs]-[0-9A-Za-z\-]{10,}"),
    ("Slack webhook", r"https://hooks\.slack\.com/services/[A-Za-z0-9/_\-]+"),
    ("Google Chat webhook token", r"chat\.googleapis\.com/\S*[?&]token=[A-Za-z0-9_\-]{10,}"),
    ("Stripe live key", r"\b[rs]k_live_[0-9A-Za-z]{16,}"),
    ("Anthropic API key", r"\bsk-ant-[0-9A-Za-z_\-]{20,}"),
    ("OpenAI API key", r"\bsk-(?:proj-)?[0-9A-Za-z_\-]{32,}"),
    ("Personal access token (id/secret form)", r"\b[12]/[0-9]{16}:[0-9a-f]{32}\b"),
    ("JWT", r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    ("Bearer token", r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}"),
    ("Meta access token", r"(?<![A-Za-z0-9])EAA[A-Za-z0-9]{20,}"),
    ("Generic secret assignment",
     r"(?i)\b(?P<key>password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret"
     r"|private[_-]?key)[\"'`*\\]*\s*[:=]\s*(?P<quote>\\?[\"']|)(?=(?P<val>[^\s\"'$<{][^\s\"']{7,}))"),
]
COMPILED = [(name, re.compile(rx)) for name, rx in PATTERNS]

# A match that looks like a placeholder or a reference, not a value.
PLACEHOLDER = re.compile(
    r"(?i)(example|sample|template|your[_-]|changeme|change_me|placeholder|dummy|redacted|xxxx+|\*\*\*\*"
    r"|<[^>]+>|\$\{[^}]+\}|\$\([^)]+\)|process\.env|os\.environ|getenv|secrets\.)"
)
# A generic-assignment value that is code, not a literal: an identifier, attribute access or call/index,
# with no digit in its name (`request.form[`, `args.client_secret`, `get_secret(name)`, `self.api_key`).
# A quoted value is a literal, so this applies only to an unquoted one.
CODE_REF = re.compile(r"[A-Za-z_][A-Za-z_.]*(\(.*|\[.*)?")
ALLOW_MARKER = "secret-scan: allow"


def code_ref_core(val):
    """Drop what wraps a value in docs and code (backticks, closing quotes or brackets, a literal \\n)."""
    return re.sub(r"(\\[nrt])+$", "", val).rstrip("`'\",;)]}")


def field_name(s):
    """Case and - or _ do not matter: `ACCESS_TOKEN = "access-token"` names a field and holds no secret."""
    return s.lower().replace("-", "_")


ALLOW_FILE = re.compile(r"(?i)\.(example|sample|template|dist)$")
HUNK = re.compile(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
DIFF_FLAGS = ("-U0", "--no-color", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/")
DOTENV = re.compile(r"(?i)(^|/)\.env(\.(local|development|production|staging|test))?$")


def git(*args):
    # core.quotepath=off: non-ASCII names print as-is instead of quoted octal escapes.
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def diff_path(header):
    """File name from a '+++ ' line, or None for /dev/null. Handles C-quoted names."""
    name = header[4:].rstrip("\t")
    if name.startswith('"') and name.endswith('"'):
        raw = name[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
        name = raw.encode("latin-1", "replace").decode("utf-8", "replace")
    return name[2:] if name.startswith("b/") else None


def resolve_base(base):
    """Return the base commit: 'auto' = upstream, else merge-base with origin's default branch, else None."""
    if base != "auto":
        return base
    up = git("rev-parse", "--verify", "-q", "@{u}")
    if up.returncode == 0 and up.stdout.strip():
        return up.stdout.strip()
    for ref in ("origin/HEAD", "origin/main", "origin/master"):
        mb = git("merge-base", "HEAD", ref)
        if mb.returncode == 0 and mb.stdout.strip():
            return mb.stdout.strip()
    return None


def mask(s):
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "*" * min(12, len(s) - 6) + s[-2:]


def scan_diff(diff_text):
    """Yield (file, line_no, rule, masked) for every secret on an added line of a unified diff.

    Each hunk's counts decide what is content, so an added `++ x` is not read as a `+++ ` file header.
    """
    cur_file, new_line, old_left, new_left = None, 0, 0, 0
    for raw in diff_text.split("\n"):
        if not old_left and not new_left:
            hunk = HUNK.match(raw)
            if hunk:
                old_left, new_line, new_left = int(hunk[1] or 1), int(hunk[2]), int(hunk[3] or 1)
            elif raw.startswith("+++ "):
                cur_file = diff_path(raw)
            continue
        if raw.startswith("-"):
            old_left -= 1
        elif raw.startswith("+"):
            new_left -= 1
            line = raw[1:]
            if cur_file and not ALLOW_FILE.search(cur_file) and ALLOW_MARKER not in line:
                for name, rx in COMPILED:
                    for m in rx.finditer(line):
                        val = m.groupdict().get("val")
                        if PLACEHOLDER.search(m.group(0) + (val or "")):
                            continue
                        if val:
                            quote = m.group("quote")
                            if quote:
                                literal = val.removesuffix("\\") if len(quote) == 2 else val
                                if field_name(literal) == field_name(m.group("key")):
                                    continue
                            elif CODE_REF.fullmatch(code_ref_core(val)):
                                continue
                        yield cur_file, new_line, name, mask(m.group(0))
            new_line += 1
        elif not raw.startswith("\\"):       # context: diff.interHunkContext adds it even with -U0
            old_left -= 1
            new_left -= 1
            new_line += 1


def publish_reads(base, auto, *flags):
    """The git reads that show what is about to leave (see the module docstring), with these output flags."""
    if not auto:
        return [git("diff", "--cached", *flags, base)]
    return [git("diff", "--cached", *flags, "HEAD"),
            git("log", "--diff-merges=remerge", "--format=", *flags, f"{base}..HEAD", "--not", "--remotes")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="auto", help="commit to diff the index against (default: what a push publishes)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):        # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        print("SCAN ERROR: not inside a git work tree", file=sys.stderr)
        return 1
    base = resolve_base(args.base)
    if base is None:
        print("SCAN ERROR: no upstream and no origin default branch to compare with; pass --base <rev>",
              file=sys.stderr)
        return 1
    auto = args.base == "auto"
    patches = publish_reads(base, auto, "-p", *DIFF_FLAGS)
    added = publish_reads(base, auto, "--name-only", "--diff-filter=A")
    for run in patches + added:
        if run.returncode != 0:
            print(f"SCAN ERROR: git read against {base} failed: {run.stderr.strip()}", file=sys.stderr)
            return 1

    findings = list(dict.fromkeys(found for run in patches for found in scan_diff(run.stdout)))
    dotenv = {f for run in added for f in run.stdout.splitlines() if DOTENV.search(f)}
    findings += [(f, 0, "Committed .env file", "(whole file)") for f in sorted(dotenv)]

    short = git("rev-parse", "--short", base).stdout.strip() or base
    if not findings:
        print(f"SECRET SCAN CLEAN (added lines since {short})")
        return 0
    print(f"SECRET SCAN FOUND {len(findings)} possible secret(s) in lines added since {short}:")
    for f, n, rule, masked in findings:
        print(f"  {f}:{n}  {rule}  {masked}")
    print("STOP: do not commit or push. Remove the value (and rotate it if it was ever pushed),")
    print(f"or add '{ALLOW_MARKER}' to a line that is a known false positive, then scan again.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
