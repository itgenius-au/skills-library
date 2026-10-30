#!/usr/bin/env python3
"""redact_doc.py - a redacted copy of one personal or financial document for review-swarm doc mode.

Use it before a document with bank, tax or contact details goes to an external model provider.

usage: redact_doc.py <file> --out <dir> [--patterns <file>] [--extra <literal> ...]
       redact_doc.py <file> --check <dir-or-file> [--patterns <file>] [--extra <literal> ...]

  <file>      the original document (UTF-8 text: a plan, decision, or legal or tax document)
  --out       the subject folder for the legs (in your scratch directory); the copy is <out>/<basename>,
              with the same patterns and extras applied to the basename, because file names reach the legs
  --patterns  a patterns file (default: redact_doc_patterns.txt next to this script). One pattern
              per line, `[PLACEHOLDER] <python regex>`; `#` lines and blank lines are skipped.
              Every pattern runs on the original; overlapping matches merge into one placeholder
              (the longest match's).
  --extra     one or more literals to redact as well (a name, a registry code), case-insensitive,
              written as [extra-<n>]. Repeat the flag or list several after it; put <file> first.
  --check     after the panel: search every file under <dir> (or one file) for the raw values the
              patterns and extras find in the ORIGINAL, case-insensitively. Prints the file and the
              placeholder of each hit, never the value.

Redact mode prints, per placeholder, the count in the original and in the copy. Any count above 0
in the copy is a survivor: the copy is removed and the run exits 1.

Exit: 0 clean, 1 a value survived (copy removed) or a --check hit, 2 usage error.
Stdlib only. Why: a hand-written regex script for this is easy to get wrong. This one is tested,
keeps the patterns as config, and reports any value that survives.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NoReturn

DEFAULT_PATTERNS = Path(__file__).with_name("redact_doc_patterns.txt")
LINE = re.compile(r"^(\[[^\]\s]+\])\s+(\S.*)$")


def fail(msg: str, code: int = 2) -> NoReturn:
    print(f"redact_doc: {msg}", file=sys.stderr)
    sys.exit(code)


def read_text(path: Path, what: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        fail(f"{what} {path} is not UTF-8 text; convert it to text first")
    except OSError as exc:
        fail(f"cannot read {what}: {exc}")


def load_rules(patterns: Path, extras: list[str]) -> list[tuple[str, re.Pattern]]:
    """Return (placeholder, regex): extras first (so they win a tie), then the patterns file."""
    rules = [(f"[extra-{i + 1}]", re.compile(re.escape(value), re.IGNORECASE))
             for i, value in enumerate(extras) if value]
    for n, raw in enumerate(read_text(patterns, "--patterns").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = LINE.match(line)
        if not match:
            fail(f"{patterns} line {n}: expected `[PLACEHOLDER] <regex>`")
        try:
            rules.append((match.group(1), re.compile(match.group(2))))
        except re.error as exc:
            fail(f"{patterns} line {n}: bad regex: {exc}")
    if not rules:
        fail(f"no patterns in {patterns} and no --extra")
    return rules


def redact(text: str, rules) -> tuple[str, dict[str, int], dict[str, str]]:
    """Redact every rule's matches in the ORIGINAL text at once.

    Overlapping matches merge into one span, written as the placeholder of its longest match (the
    earlier rule on a tie), so a value inside another (an NIE inside an email) cannot split it and
    leave a fragment. Returns the text, the match count per placeholder, and raw value -> placeholder
    for every match (the --check needles; a merged span always contains one).
    """
    counts: dict[str, int] = {}
    values: dict[str, str] = {}
    spans = []
    for order, (label, regex) in enumerate(rules):
        counts.setdefault(label, 0)
        for match in regex.finditer(text):
            if match.end() > match.start():
                counts[label] += 1
                values.setdefault(match.group(0), label)
                spans.append((match.start(), match.end(), order, label))
    merged: list[list] = []  # [start, end, label, (-longest match length, its rule order)]
    for start, end, order, label in sorted(spans):
        rank = (start - end, order)
        if merged and start < merged[-1][1]:
            last = merged[-1]
            if rank < last[3]:
                last[2], last[3] = label, rank
            last[1] = max(last[1], end)
        else:
            merged.append([start, end, label, rank])
    pieces, pos = [], 0
    for start, end, label, _ in merged:
        pieces += [text[pos:start], label]
        pos = end
    return "".join(pieces) + text[pos:], counts, values


def survivors(text: str, rules) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label, regex in rules:
        counts[label] = counts.get(label, 0) + sum(1 for m in regex.finditer(text) if m.group(0))
    return counts


def check(original: str, target: Path, rules) -> None:
    _, _, values = redact(original, rules)
    if not target.exists():
        fail(f"--check {target} does not exist")
    needles = [(re.compile(re.escape(value), re.IGNORECASE), label) for value, label in values.items()]
    control = sum(1 for regex, _ in needles if regex.search(original))
    print(f"control: values={len(values)} found_in_original={control}")
    if not values:
        print("redact_doc: warning: the patterns and extras find no value in the original; nothing to check")
    files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
    hits = 0
    for path in files:
        text = path.read_bytes().decode("utf-8", errors="replace")
        for regex, label in needles:
            found = len(regex.findall(text)) + len(regex.findall(path.name))
            if found:
                hits += found
                print(f"HIT {path}: {label} x{found}")
    print(f"checked files={len(files)} hits={hits}")
    sys.exit(1 if hits else 0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--check", type=Path)
    ap.add_argument("--patterns", type=Path, default=DEFAULT_PATTERNS)
    ap.add_argument("--extra", action="extend", nargs="+", default=[])
    args = ap.parse_args()

    original = read_text(args.file, "input")
    rules = load_rules(args.patterns, args.extra)
    if args.check:
        check(original, args.check, rules)
    if not args.out:
        fail("--out <dir> is required (or --check <dir> after the panel)")

    # samefile also catches a symlink or hard link to the original sitting at <out>/<basename>.
    # The name is redacted too: review packets print each file's path, so a name in it would leak.
    dest = args.out.resolve() / redact(args.file.name, rules)[0]
    if dest == args.file.resolve() or (dest.exists() and dest.samefile(args.file)):
        fail(f"--out {args.out} would overwrite the original; pick a scratch subject folder")

    copy, before, _ = redact(original, rules)
    after = survivors(copy, rules)
    args.out.mkdir(parents=True, exist_ok=True)
    dest.write_text(copy, encoding="utf-8")

    width = max(len(label) for label in before)
    print(f"{'placeholder':<{width}}  original  copy")
    for label in before:
        print(f"{label:<{width}}  {before[label]:>8}  {after[label]:>4}")
    left = {label: n for label, n in after.items() if n}
    if left:
        dest.unlink()
        for label, n in left.items():
            print(f"redact_doc: {label} survived {n} time(s) in the copy", file=sys.stderr)
        fail(f"{sum(left.values())} survivor(s); copy removed. Fix the patterns or redact by hand.", code=1)
    print(f"redacted copy: {dest} replaced={sum(before.values())} survivors=0")


if __name__ == "__main__":
    main()
