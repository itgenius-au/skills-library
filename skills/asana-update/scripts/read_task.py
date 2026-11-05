#!/usr/bin/env python3
"""Read one Asana task, read-only: parent chain, fields, notes, every story, subtasks.

    read_task.py <task_url_or_gid>
    read_task.py <task> --depth 2            # subtasks two levels down, each in full
    read_task.py <task> --comments-only      # leave out system stories (assigned, moved, ...)
    read_task.py <task> --json               # one JSON document instead of text
    read_task.py <task> --token-secret other-ws-token   # a task in another workspace

What it reads:
- the task: its fields, html_notes, and every page of its stories (Asana pages until no
  next_page);
- its parents, up to the root: name, assignee and html_notes (not their stories);
- its subtasks: in full (fields, notes, stories) down to --depth levels (default 1); the
  level below that is listed by name only, marked "not expanded".

It makes GET requests only and writes nothing. A parent the token cannot read is marked
"cannot read" and the task still prints. Any other failed request stops the read with no
output: an HTTP error names the request that failed; a network failure (retries used up)
names the task.

A 403 or 404 on the task means no task with that gid is visible to the token: check the
gid, or for a task in another workspace pass --token-secret/--token-project
(see "Another workspace" in SKILL.md).
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse

from _asana import (
    BASE_URL, add_token_args, extract_task_gid, fetch_token, request, task_url, token_request,
)

TASK_FIELDS = (
    "name,html_notes,completed,completed_at,due_on,start_on,created_at,created_by.name,"
    "assignee.name,parent.gid,parent.name,permalink_url,"
    "memberships.project.name,memberships.section.name,followers.name,"
    "custom_fields.name,custom_fields.display_value"
)
PARENT_FIELDS = "name,html_notes,assignee.name,completed,parent.gid,parent.name"
STORY_FIELDS = "created_at,created_by.name,type,resource_subtype,html_text,text"
SUBTASK_FIELDS = "name,completed,assignee.name"
MAX_PARENT_HOPS = 25  # Asana nests subtasks at most a few levels; this only stops a loop


def get_task(gid, token, fields=TASK_FIELDS):
    return request("GET", f"/tasks/{gid}", token, params={"opt_fields": fields})["data"]


def get_all(path, token, fields):
    """Every row of a paged collection: follow next_page until Asana returns none."""
    params = {"limit": 100, "opt_fields": fields}
    rows = []
    while True:
        resp = request("GET", path, token, params=dict(params))
        rows.extend(resp.get("data") or [])
        next_page = resp.get("next_page")
        if not next_page or not next_page.get("offset"):
            return rows
        params["offset"] = next_page["offset"]


def parent_chain(task, token):
    """Parents from the direct parent up to the root. Stops on a repeated gid."""
    chain, seen = [], {task.get("gid")}
    parent = task.get("parent")
    while parent and parent.get("gid") and len(chain) < MAX_PARENT_HOPS:
        if parent["gid"] in seen:
            break
        seen.add(parent["gid"])
        try:
            row = get_task(parent["gid"], token, PARENT_FIELDS)
        except urllib.error.HTTPError as exc:
            # The task itself was readable; a parent in a project this token cannot see
            # should not hide it. Record the gap and stop walking.
            chain.append({"gid": parent["gid"], "name": parent.get("name"),
                          "unreadable": f"HTTP {exc.code}"})
            break
        row.setdefault("gid", parent["gid"])
        chain.append(row)
        parent = row.get("parent")
    return chain


def is_comment(story):
    return story.get("type") == "comment" or story.get("resource_subtype") == "comment_added"


def collect(gid, token, depth, comments_only):
    """The task, its stories and its subtasks (in full down to `depth` levels)."""
    task = get_task(gid, token)
    task.setdefault("gid", gid)
    stories = get_all(f"/tasks/{gid}/stories", token, STORY_FIELDS)
    if comments_only:
        stories = [s for s in stories if is_comment(s)]
    subs = get_all(f"/tasks/{gid}/subtasks", token, SUBTASK_FIELDS)
    node = {"task": task, "stories": stories, "subtasks": []}
    for sub in subs:
        if depth > 0:
            node["subtasks"].append(collect(sub["gid"], token, depth - 1, comments_only))
        else:
            node["subtasks"].append({"task": sub, "stories": None, "subtasks": None})
    return node


def _name(obj):
    return (obj or {}).get("name") or "-"


def print_task(node, comments_only, indent=0, label="TASK"):
    pad = "  " * indent
    t = node["task"]
    out = []
    out.append(f"{pad}=== {label} {t.get('gid')}: {t.get('name')}")
    out.append(f"{pad}url: {task_url(t.get('gid'))}")
    if node["stories"] is None:  # listed only (beyond --depth)
        done = "done" if t.get("completed") else "open"
        out.append(f"{pad}{done} · {_name(t.get('assignee'))} (not expanded: raise --depth)")
        print("\n".join(out))
        return
    out.append(
        f"{pad}assignee: {_name(t.get('assignee'))} | completed: {bool(t.get('completed'))}"
        f" | start: {t.get('start_on') or '-'} | due: {t.get('due_on') or '-'}"
        f" | created: {t.get('created_at') or '-'} by {_name(t.get('created_by'))}"
        f" | completed at: {t.get('completed_at') or '-'}"
    )
    homes = [
        f"{_name(m.get('project'))} / {_name(m.get('section'))}" for m in t.get("memberships") or []
    ]
    out.append(f"{pad}projects: {'; '.join(homes) or '-'}")
    out.append(f"{pad}followers: {', '.join(_name(f) for f in t.get('followers') or []) or '-'}")
    fields = [
        f"{c.get('name')}={c.get('display_value')}"
        for c in t.get("custom_fields") or []
        if c.get("display_value") not in (None, "")
    ]
    out.append(f"{pad}fields: {'; '.join(fields) or '-'}")
    out.append(f"{pad}notes:")
    out.append(t.get("html_notes") or "<body></body>")
    kind = "comments" if comments_only else "stories"
    out.append(f"{pad}--- {kind} ({len(node['stories'])}):")
    for s in node["stories"]:
        body = s.get("html_text") or s.get("text") or ""
        out.append(
            f"{pad}[{s.get('created_at')}] {_name(s.get('created_by'))}"
            f" ({s.get('resource_subtype') or s.get('type')}): {body}"
        )
    out.append(f"{pad}--- subtasks ({len(node['subtasks'])}):")
    print("\n".join(out))
    for sub in node["subtasks"]:
        print_task(sub, comments_only, indent + 1, "SUBTASK")


def failed_path(exc):
    """The API path of a failed request ("/tasks/123/stories"), without host or query."""
    url = getattr(exc, "url", None) or getattr(exc, "filename", None) or ""
    path = urllib.parse.urlparse(url).path
    prefix = urllib.parse.urlparse(BASE_URL).path
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task", help="Task GID or any Asana task URL")
    p.add_argument("--depth", type=int, default=1,
                   help="Subtask levels to read in full (default 1; 0 lists subtasks only)")
    p.add_argument("--comments-only", action="store_true",
                   help="Leave out system stories (assignments, moves, field changes)")
    p.add_argument("--json", action="store_true", help="Print one JSON document")
    add_token_args(p)
    args = p.parse_args(argv)
    if args.depth < 0:
        p.error("--depth must be 0 or more")
    try:
        gid = extract_task_gid(args.task)
    except ValueError as exc:
        p.error(str(exc))
    token_kwargs = token_request(args)

    try:
        token = fetch_token(**token_kwargs)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"nothing read: could not read secret "
                 f"{token_kwargs.get('secret_name', 'default')!r}: "
                 f"{(exc.stderr or '').strip() or exc}")

    try:
        node = collect(gid, token, args.depth, args.comments_only)
        parents = parent_chain(node["task"], token)
    except urllib.error.HTTPError as exc:
        path = failed_path(exc) or f"/tasks/{gid}"
        hint = ""
        if exc.code in (403, 404) and path == f"/tasks/{gid}":
            hint = (" No task with this gid is visible to this token: check the gid, or for "
                    "another workspace pass --token-secret/--token-project.")
        sys.exit(f"read failed, nothing printed: HTTP {exc.code} on GET {path}.{hint}")
    except RuntimeError as exc:  # retries used up (network or 5xx)
        sys.exit(f"read failed, nothing printed (task {gid}): {exc}")

    if args.json:
        print(json.dumps({"parents": parents, **node}, indent=2, ensure_ascii=False))
        return

    for i, par in enumerate(parents, 1):
        if par.get("unreadable"):
            where = "unreadable"
        elif i == 1:
            where = "direct parent"
        else:
            where = "root" if i == len(parents) else f"level {i}"
        print(f"=== PARENT {i} ({where}) {par.get('gid')}: {par.get('name')}")
        if par.get("unreadable"):
            print(f"url: {task_url(par.get('gid'))} | cannot read ({par['unreadable']}): "
                  "this token cannot see it, so the chain stops here")
            continue
        print(f"url: {task_url(par.get('gid'))} | assignee: {_name(par.get('assignee'))}"
              f" | completed: {bool(par.get('completed'))}")
        print("notes:")
        print(par.get("html_notes") or "<body></body>")
    print_task(node, args.comments_only)


if __name__ == "__main__":
    main()
