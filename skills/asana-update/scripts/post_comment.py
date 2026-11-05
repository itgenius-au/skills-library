#!/usr/bin/env python3
"""Post a comment (story) to an Asana task.

    post_comment.py <task_url_or_gid> --text "plain text"
    post_comment.py <task_url_or_gid> --html-file body.html
    post_comment.py <task_url_or_gid> --html-stdin  (reads from stdin)

HTML mode wraps the body in <body>...</body> automatically. Newlines render
as line breaks. Unsupported tags (<p>, <br>, <th>, <img>, <div>) are refused
before posting, because Asana would silently store the comment as escaped text. Pinning is OFF by
default and should stay that way unless the user explicitly asks.

The shape check refuses a wall of text: a comment over 500 characters with no
<hr> (lead with a plain-English summary, put details below an <hr>). It warns
when the summary is long or a file is named with no link. --skip-shape-check
overrides the refusal; use it only when the user asks for that shape.

Everyone @mentioned in the comment is added as a follower of the task after the
post, then read back, so they see later replies. --no-follow skips this; use it
only for the subject of a private or sensitive task.

Another workspace (HTTP 403 with the default token): --token-secret <secret>
[--token-project <GCP project>] reads another token from Google Secret Manager.
Every other step is the same, including the author line and the follower step.

--dry-run writes nothing. It reads the token and the token's owner (GETs only)
so the payload it prints carries the author line; if the token cannot be read,
it says so and prints the body without the line.
"""

import argparse
import json
import subprocess
import sys

from _asana import (
    add_author_line, add_author_line_text, add_token_args, extract_task_gid,
    fetch_token, follow_mentions, is_empty_body, mentioned_user_gids, request,
    shape_problems, starts_with_author_line, task_url, token_request, wrap_body,
)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task", help="Task GID or URL")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--text", help="Plain text comment")
    g.add_argument("--html-file", help="Path to an HTML fragment")
    g.add_argument("--html-stdin", action="store_true", help="Read HTML from stdin")
    p.add_argument("--pin", action="store_true",
                   help="Pin the comment. Rare: only when the user explicitly asks.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the payload and exit without posting")
    p.add_argument("--no-follow", action="store_true",
                   help="Do not add the @mentioned users as followers. Only for the "
                        "subject of a private or sensitive task.")
    p.add_argument("--skip-shape-check", action="store_true",
                   help="Post a body the shape check refuses. Only when the user asks.")
    add_token_args(p)
    args = p.parse_args()
    token_kwargs = token_request(args)

    if args.html_file:
        html = open(args.html_file).read()
    elif args.html_stdin:
        html = sys.stdin.read()
    else:
        html = None
    # Refuse here: with your own PAT, an empty body would post the author line alone.
    if is_empty_body(html) if html is not None else not args.text.strip():
        sys.exit("refusing to post: the comment is empty")

    payload = {"data": {}}
    if html is not None:
        try:
            payload["data"]["html_text"] = wrap_body(html)
        except ValueError as exc:
            sys.exit(f"refusing to post: {exc}")
    else:
        payload["data"]["text"] = args.text
    if args.pin:
        payload["data"]["is_pinned"] = True

    blocking, warnings = shape_problems(html if html is not None else args.text,
                                        is_html=html is not None)
    for msg in warnings:
        print(f"SHAPE WARNING: {msg}", file=sys.stderr)

    mentions = mentioned_user_gids(payload["data"].get("html_text"))
    if args.dry_run:
        try:
            token = fetch_token(**token_kwargs)
        except (subprocess.CalledProcessError, SystemExit, OSError) as exc:
            token = None
            print(f"Author line: unknown (could not read the token: {exc})")
        if token is not None:
            _mark(payload, token)
            print(f"Author line: {_line_state(payload)}")
        print(json.dumps(payload, indent=2))
        for msg in blocking:
            print(f"SHAPE: refused when posted live: {msg}")
        if mentions and args.no_follow:
            print("Followers: not changed (--no-follow)")
        elif mentions:
            print("Will add as followers (after the post, users only): "
                  + ", ".join(mentions))
        return
    if blocking and not args.skip_shape_check:
        sys.exit("refusing to post: " + "; ".join(blocking))

    task_gid = extract_task_gid(args.task)
    try:
        token = fetch_token(**token_kwargs)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"nothing posted: could not read secret "
                 f"{token_kwargs.get('secret_name', 'default')!r}: "
                 f"{(exc.stderr or '').strip() or exc}")
    # Your own PAT shows you as the author: say an agent wrote it.
    _mark(payload, token)
    resp = request("POST", f"/tasks/{task_gid}/stories", token, data=payload)
    story_gid = resp["data"]["gid"]
    print(f"Posted story {story_gid} to {task_url(task_gid)}")
    # Hand callers a paste-ready link. The post already landed, so a failed
    # name lookup must never fail the script.
    try:
        name = request("GET", f"/tasks/{task_gid}", token,
                       params={"opt_fields": "name"})["data"]["name"]
        print(f"Task: [{name}]({task_url(task_gid)})")
    except Exception:
        print("Task: (name lookup failed)")
    print(task_url(task_gid))
    # A mention notifies once; following keeps them on the thread. Never fatal.
    if mentions and not args.no_follow:
        follow_mentions(task_gid, story_gid, payload["data"]["html_text"], token,
                        request_fn=request)


def _mark(payload, token):
    if "html_text" in payload["data"]:
        payload["data"]["html_text"] = add_author_line(payload["data"]["html_text"], token)
    else:
        payload["data"]["text"] = add_author_line_text(payload["data"]["text"], token)


def _line_state(payload) -> str:
    body = payload["data"].get("html_text") or payload["data"].get("text") or ""
    return "added" if starts_with_author_line(body) else "none (agent account)"


if __name__ == "__main__":
    main()
