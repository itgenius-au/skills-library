#!/usr/bin/env python3
"""Build the inline prompt packet for the GLM leg of a review swarm.

GLM has no shell and no repository access, so everything it reviews must be
inside its prompt file. Hand-built packets fail quietly: an empty diff, a
missing file, or a packet past GLM's size limit all produce a review of
nothing, and GLM answers anyway with plausible, invented citations. This
script refuses those cases instead.

usage:
  glm_packet.py --body <prompt-body-file> --inline <file> [--inline <file> ...]
                --out <file> [--max-bytes 60000] [--number-lines] [--repo-leg]

The output is: the body, a fixed "no shell, no repository" note (or, with
--repo-leg, a note telling a repo-capable leg to also read the repo), then each
inlined file under a `=== <path> ===` header (with `--number-lines`, each line
is prefixed `N: ` so GLM can cite a line number that means something).

It exits non-zero, writes no packet, and removes any stale file at --out when:
  - the body is empty, or an inlined file is missing, unreadable or empty
  - the packet is over --max-bytes (GLM silently truncates above ~60 KB, so
    split the review into passes instead of raising the limit)
  - the body promises content ("included below", "attached", "see the diff
    below", "full text follows") and no non-empty file is inlined

Exit codes: 0 packet written, 1 refused, 2 bad usage or unreadable input.
Python 3 standard library only.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_MAX_BYTES = 60000

NOTE = (
    "YOU HAVE NO SHELL AND NO REPOSITORY ACCESS. Report `DIR: inlined`. "
    "The material below is the ONLY code you can see; cite only its line numbers."
)

# --repo-leg: the same packet for a leg that DOES run in a repo snapshot (Codex,
# Gemini, Fable). The no-shell note made those legs skip reading the repo
# (the no-shell note made those legs skip reading the repo and report `DIR: inlined`).
REPO_NOTE = (
    "The material below is inlined for reference. You ALSO have a shell and the repository "
    "in your working directory: read and grep it to verify every claim, and report the "
    "directory you read as `DIR:`."
)

# Phrases that tell the reviewer "the material is below". Matched
# case-insensitively as whole words in the BODY only.
PROMISE_PHRASES = (
    "included below",
    "inlined below",
    "attached",
    "see the diff below",
    "full text follows",
)
PROMISE_RE = re.compile(
    "|".join(r"\b" + re.escape(p) + r"\b" for p in PROMISE_PHRASES), re.IGNORECASE
)


class Refused(Exception):
    """The packet would send GLM nothing, or too much, to review."""


class BadInput(Exception):
    """A file could not be read."""


def read_text(path: Path, what: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BadInput(f"cannot read {what} {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise BadInput(f"{what} {path} is not valid UTF-8: {exc}") from exc


def number_lines(text: str) -> str:
    return "\n".join(f"{n}: {line}" for n, line in enumerate(text.splitlines(), 1))


def build_packet(body: str, inlined: list[tuple[str, str]], max_bytes: int, numbered: bool,
                 note: str = NOTE) -> str:
    """Return the packet text, or raise Refused."""
    if not body.strip():
        raise Refused("the prompt body is empty")
    for label, text in inlined:
        if not text.strip():
            raise Refused(f"inlined file is empty: {label}")
    promised = PROMISE_RE.search(body)
    if promised and not inlined:
        raise Refused(
            f"the body promises content ('{promised.group(0)}') but no file is inlined; "
            "GLM would review nothing and invent citations"
        )

    parts = [body.rstrip("\n"), "", note, ""]
    for label, text in inlined:
        content = number_lines(text) if numbered else text.rstrip("\n")
        parts += [f"=== {label} ===", content, ""]
    packet = "\n".join(parts)

    size = len(packet.encode("utf-8"))
    if size > max_bytes:
        raise Refused(
            f"packet is {size} bytes, over the {max_bytes} byte limit (GLM silently truncates "
            "large prompts); trim the inlined files or split the review into passes"
        )
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a GLM inline packet: prompt body + no-shell note + inlined files.",
    )
    parser.add_argument("--body", required=True, type=Path, help="file holding the prompt body")
    parser.add_argument("--inline", action="append", default=[], type=Path, metavar="FILE",
                        help="file to inline under a `=== path ===` header (repeatable)")
    parser.add_argument("--out", required=True, type=Path, help="packet file to write")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                        help=f"refuse a packet larger than this (default {DEFAULT_MAX_BYTES})")
    parser.add_argument("--number-lines", action="store_true",
                        help="prefix each inlined line with its line number")
    parser.add_argument("--repo-leg", action="store_true",
                        help="for a leg that runs in a repo snapshot (Codex, Gemini, Fable): "
                             "use the repo note instead of the no-shell note")
    args = parser.parse_args(argv)
    if args.max_bytes <= 0:
        parser.error("--max-bytes must be positive")

    try:
        body = read_text(args.body, "body file")
        inlined = [(str(p), read_text(p, "inlined file")) for p in args.inline]
    except BadInput as exc:
        print(f"glm_packet: {exc}", file=sys.stderr)
        return 2

    try:
        packet = build_packet(body, inlined, args.max_bytes, args.number_lines,
                              REPO_NOTE if args.repo_leg else NOTE)
    except Refused as exc:
        # A stale packet from an earlier run must not be sent by mistake.
        args.out.unlink(missing_ok=True)
        print(f"glm_packet: REFUSED: {exc}", file=sys.stderr)
        return 1

    args.out.write_text(packet, encoding="utf-8")
    print(f"glm_packet: {len(packet.encode('utf-8'))} bytes (limit {args.max_bytes}), "
          f"{len(inlined)} inlined file(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
