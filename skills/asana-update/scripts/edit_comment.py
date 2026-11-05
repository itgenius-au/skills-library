#!/usr/bin/env python3
"""Correct a comment (story) in place, instead of deleting it and posting again.

    edit_comment.py <story_gid> --html-file body.html --dry-run
    edit_comment.py <story_gid> --html-file body.html
    edit_comment.py <story_gid> --text "plain text"

Use it to fix a comment that is wrong or badly shaped: a wrong fact, a missing
author line, a wall of text that needs a summary and an <hr>. The new body
REPLACES the old text. Asana marks the comment "(edited)" and shows no old
version, so the dry run prints the old text for the record. A delete and a
repost would lose the comment's place in the thread and notify everyone twice.

Before it writes, it reads the story and refuses unless the story is a comment
(not a system story such as "changed the due date") and was written by the
token's own Asana user: Asana lets only the author edit a comment. Find the
story gid with GET /tasks/{task}/stories, or in the "Posted story <gid>" line
that post_comment.py prints.

The new body gets the same checks as post_comment.py: the rich-text tags, the
shape check and the author line. Every @mention in it becomes a follower. The
dry run makes GETs only (the story and the token's owner) and writes nothing.
After the PUT it reads the comment back and prints the task link.

Another workspace: --token-secret <secret> [--token-project <GCP project>],
as in post_comment.py.
"""

import argparse
import json
import subprocess
import sys

from _asana import (
    add_author_line, add_author_line_text, add_token_args, fetch_token,
    follow_mentions, is_empty_body, mentioned_user_gids, request, shape_problems,
    task_url, token_request, wrap_body,
)

STORY_FIELDS = "resource_subtype,type,created_by.gid,created_by.name,target.gid,target.name,text,html_text"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("story", help="Story (comment) GID")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--text", help="New plain-text body")
    g.add_argument("--html-file", help="Path to the new HTML fragment")
    g.add_argument("--html-stdin", action="store_true", help="Read the new HTML from stdin")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the old text and the new payload; write nothing")
    p.add_argument("--no-follow", action="store_true",
                   help="Do not add the @mentioned users as followers. Only for the "
                        "subject of a private or sensitive task.")
    p.add_argument("--skip-shape-check", action="store_true",
                   help="Write a body the shape check refuses. Only when the user asks.")
    add_token_args(p)
    args = p.parse_args(argv)
    token_kwargs = token_request(args)
    story_gid = args.story.strip()
    if not story_gid.isdigit():
        sys.exit(f"refusing to edit: {args.story!r} is not a story gid")

    if args.html_file:
        html = open(args.html_file).read()
    elif args.html_stdin:
        html = sys.stdin.read()
    else:
        html = None
    if is_empty_body(html) if html is not None else not args.text.strip():
        sys.exit("refusing to edit: the new body is empty (a comment cannot be blanked)")

    payload = {"data": {}}
    if html is not None:
        try:
            payload["data"]["html_text"] = wrap_body(html)
        except ValueError as exc:
            sys.exit(f"refusing to edit: {exc}")
    else:
        payload["data"]["text"] = args.text
    blocking, warnings = shape_problems(html if html is not None else args.text,
                                        is_html=html is not None)
    for msg in warnings:
        print(f"SHAPE WARNING: {msg}", file=sys.stderr)
    if blocking and not args.skip_shape_check and not args.dry_run:
        sys.exit("refusing to edit: " + "; ".join(blocking))

    try:
        token = fetch_token(**token_kwargs)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"nothing edited: could not read secret "
                 f"{token_kwargs.get('secret_name', 'default')!r}: "
                 f"{(exc.stderr or '').strip() or exc}")

    story = request("GET", f"/stories/{story_gid}", token,
                    params={"opt_fields": STORY_FIELDS})["data"]
    if story.get("resource_subtype") != "comment_added":
        sys.exit(f"refusing to edit: story {story_gid} is a "
                 f"{story.get('resource_subtype') or story.get('type')!r} story, not a comment")
    me = request("GET", "/users/me", token, params={"opt_fields": "gid,name"})["data"]
    author = story.get("created_by") or {}
    if author.get("gid") != me.get("gid"):
        sys.exit(f"refusing to edit: story {story_gid} was written by "
                 f"{author.get('name') or author.get('gid')}, and this token is "
                 f"{me.get('name') or me.get('gid')}. Asana lets only the author edit a "
                 "comment: use that login's token (--token-secret).")
    target = story.get("target") or {}
    task_gid = target.get("gid") or ""

    if "html_text" in payload["data"]:
        payload["data"]["html_text"] = add_author_line(payload["data"]["html_text"], token)
    else:
        payload["data"]["text"] = add_author_line_text(payload["data"]["text"], token)
    mentions = mentioned_user_gids(payload["data"].get("html_text"))

    if args.dry_run:
        print(f"Story {story_gid} on [{target.get('name') or task_gid}]({task_url(task_gid)})")
        print("--- old body (keep it if the record matters) ---")
        print(story.get("html_text") or story.get("text") or "")
        print("--- new payload ---")
        print(json.dumps(payload, indent=2))
        for msg in blocking:
            print(f"SHAPE: refused when written live: {msg}")
        if mentions and not args.no_follow:
            print("Will add as followers (after the edit, users only): " + ", ".join(mentions))
        print("DRY RUN - nothing written")
        return

    request("PUT", f"/stories/{story_gid}", token, data=payload)
    # The edit has landed: say so before any read-back that could fail.
    print(f"Edited story {story_gid} on {task_url(task_gid)}")
    print(f"Task: [{target.get('name') or task_gid}]({task_url(task_gid)})")
    print(task_url(task_gid))
    try:
        back = request("GET", f"/stories/{story_gid}", token,
                       params={"opt_fields": "text,html_text"})["data"]
        stored = back.get("html_text") or ""
        if ("html_text" in payload["data"] and "&lt;" in stored
                and "&lt;" not in payload["data"]["html_text"]):
            print(f"PARTIAL: story {story_gid} was edited but Asana stored it as escaped "
                  "text. Fix the tags and run edit_comment.py again.", file=sys.stderr)
    except Exception as exc:
        print(f"NOTE: the edit landed but the read-back failed ({exc}); check the comment "
              "on the task. Do not run the edit again to check it.", file=sys.stderr)
    if mentions and not args.no_follow and task_gid:
        follow_mentions(task_gid, story_gid, payload["data"]["html_text"], token,
                        request_fn=request)


if __name__ == "__main__":
    main()
