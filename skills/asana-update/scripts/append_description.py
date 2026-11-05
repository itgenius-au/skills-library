#!/usr/bin/env python3
"""Safely APPEND to a task's html_notes (never overwrite).

Asana does not store description version history: a PUT with a fresh
html_notes is irreversible. This script reads the current description,
joins it with a separator, and writes the combined value back.

    append_description.py <task> --html-file path/to/body.html
    append_description.py <task> --html-stdin

By default the separator is <hr>. Blank task descriptions are fine: the
script handles that case and writes the new content without a leading rule.
"""

import argparse
import subprocess
import json
import sys

from _asana import (
    add_author_line, add_token_args, extract_task_gid, fetch_token, is_empty_body,
    request, task_url, token_request,
)


def unwrap_body(s: str) -> str:
    s = s.strip()
    if s.startswith("<body>") and s.endswith("</body>"):
        return s[len("<body>"):-len("</body>")]
    return s


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--html-file")
    g.add_argument("--html-stdin", action="store_true")
    p.add_argument("--separator", default="<hr>")
    p.add_argument("--dry-run", action="store_true")
    add_token_args(p)
    args = p.parse_args()
    token_kwargs = token_request(args)

    new_html = (open(args.html_file).read() if args.html_file
                else sys.stdin.read()).strip()
    if is_empty_body(new_html):
        sys.exit("refusing to append: the new section is empty")

    task_gid = extract_task_gid(args.task)
    try:
        token = fetch_token(**token_kwargs)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"nothing written: could not read secret "
                 f"{token_kwargs.get('secret_name', 'default')!r}: "
                 f"{(exc.stderr or '').strip() or exc}")

    current = request("GET", f"/tasks/{task_gid}", token,
                      params={"opt_fields": "html_notes"})
    existing_inner = unwrap_body(current["data"].get("html_notes") or "")
    new_inner = add_author_line(unwrap_body(new_html), token)

    if existing_inner:
        combined = f"<body>{existing_inner}{args.separator}{new_inner}</body>"
    else:
        combined = f"<body>{new_inner}</body>"

    payload = {"data": {"html_notes": combined}}
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        print(f"\n--- combined html_notes preview ---\n{combined}", file=sys.stderr)
        return

    request("PUT", f"/tasks/{task_gid}", token, data=payload)
    print(f"Appended to description: {task_url(task_gid)}")


if __name__ == "__main__":
    main()
