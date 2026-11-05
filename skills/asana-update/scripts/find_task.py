#!/usr/bin/env python3
"""Search Asana tasks by text across your workspace.

    find_task.py --query "quarterly report"
    find_task.py --query "welcome email" --project <project_gid>

Useful when the user asks for a task they can't remember the exact name of, or
before creating a new task (to avoid duplicates). Results include a clickable
URL per hit.

A miss is NOT proof the task does not exist. Asana search ranks by most recently
modified and returns at most 100 hits, with no paging. A common name ("Weekly
check-in | X") can match 100+ tasks, so an old task drops off the list. Exact
name matches are listed first, and a capped result prints a warning. If you
know the GID, fetch it directly (read_task.py <gid>) instead. Also, --project
only searches that project: a task with no project never matches it.

Asana's search endpoint needs a paid (Premium or higher) workspace.
"""

import argparse
import subprocess
import sys
from _asana import (
    add_token_args, fetch_token, request, require_workspace, task_url, token_request,
)

MAX_LIMIT = 100  # Asana's hard cap for /tasks/search (no offset paging)


def exact_first(results, query):
    """Stable sort: tasks whose name equals the query (trimmed, case-insensitive) first."""
    target = " ".join(query.split()).lower()
    return sorted(
        results, key=lambda t: " ".join((t.get("name") or "").split()).lower() != target
    )


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--query", required=True)
    p.add_argument("--project", help="Limit to a project GID (tasks in no project never match)")
    p.add_argument("--limit", type=int, default=MAX_LIMIT, help=f"Max hits (Asana cap {MAX_LIMIT})")
    p.add_argument("--workspace", help="Workspace GID to search (default: workspace_gid "
                   "in the config)")
    add_token_args(p)
    args = p.parse_args(argv)
    token_kwargs = token_request(args)
    workspace = require_workspace(args.workspace)
    limit = max(1, min(args.limit, MAX_LIMIT))

    try:
        token = fetch_token(**token_kwargs)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"nothing read: could not read secret "
                 f"{token_kwargs.get('secret_name', 'default')!r}: "
                 f"{(exc.stderr or '').strip() or exc}")
    params = {
        "text": args.query,
        "limit": limit,
        "opt_fields": "name,gid,completed,projects.name,assignee.name",
    }
    if args.project:
        params["projects.any"] = args.project

    resp = request("GET", f"/workspaces/{workspace}/tasks/search", token, params=params)
    results = exact_first(resp.get("data", []), args.query)
    if not results:
        print("no matches (not proof of absence: see --help)")
        return
    if len(results) >= limit:
        print(
            f"WARNING: {len(results)} hits = the cap, so older matches are hidden. "
            "A miss here is not proof of absence: narrow the query or fetch by GID.",
            file=sys.stderr,
        )
    for t in results:
        flag = "x" if t.get("completed") else " "
        projects = ", ".join(p["name"] for p in (t.get("projects") or []))
        assignee = (t.get("assignee") or {}).get("name") or "unassigned"
        print(f"[{flag}] {task_url(t['gid'])}")
        print(f"      {t['name']}")
        print(f"      {assignee} | {projects}")


if __name__ == "__main__":
    main()
