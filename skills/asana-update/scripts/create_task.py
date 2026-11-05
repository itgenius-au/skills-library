#!/usr/bin/env python3
"""Create an Asana task, with a duplicate check first and a read-back after.

    create_task.py --project <gid> --name "..." [options]
    create_task.py --parent <gid> --name "..." [options]   # subtask

Options:
    --section <gid>         Section in --project (else default_sections from the
                            config, else Asana's default section)
    --assignee <user_gid>
    --follower <email|gid>  Someone involved; added as a collaborator (repeatable)
    --notes <text>          Plain-text description
    --notes-file <path>     Plain-text description from a file
    --html-notes-file <p>   HTML fragment for a rich-text description
    --due <YYYY-MM-DD>
    --start-on <YYYY-MM-DD> Start date (needs --due)
    --multi-home <gid>      Add the new task to an extra project (repeatable)
    --insert-after <gid>    Place the new subtask right after this sibling (needs --parent)
    --workspace <gid>       Workspace for a --project create (default: workspace_gid,
                            or none with a token option: --project already sets it)
    --allow-duplicates      Skip the name-match check
    --dry-run               Print the payload without posting

By default the script refuses to create when a task with the same name already
exists in the target project or under the target parent. Pass
--allow-duplicates only when two tasks with the same name are really wanted.

If the create request fails with no clear answer (a timeout, a cut-off reply),
the script looks for a NEW task with that name before giving up, so a create
that did land is adopted rather than made twice. It never adopts a task that
existed before the run.

Another workspace: --token-secret <secret> [--token-project <GCP project>].
With a token option, --dry-run reads the token and GET /users/me so the
payload it prints carries the author line.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date

import _asana
from _asana import task_url

TASK_OPT_FIELDS = (
    "name,parent.gid,projects.gid,memberships.project.gid,"
    "memberships.section.gid"
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--project", help="Target project GID (omit for subtask)")
    parser.add_argument("--parent", help="Parent task GID or URL (creates a subtask)")
    parser.add_argument("--name", required=True)
    parser.add_argument("--section")
    parser.add_argument("--assignee")
    parser.add_argument(
        "--follower", action="append", default=[],
        help="Email or gid of someone involved in the task (repeatable). Added as a "
        "collaborator after create. Never the subject of a private/sensitive task.",
    )
    parser.add_argument("--notes")
    parser.add_argument("--notes-file", help="Plain-text description file")
    parser.add_argument("--html-notes-file")
    parser.add_argument("--due")
    parser.add_argument("--start-on", help="Start date YYYY-MM-DD (needs --due)")
    parser.add_argument("--multi-home", action="append", default=[])
    parser.add_argument(
        "--insert-after",
        help="Sibling task GID: place the new subtask right after it (needs --parent)",
    )
    parser.add_argument("--workspace", help="Workspace GID (default: workspace_gid in the config)")
    parser.add_argument("--allow-duplicates", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    _asana.add_token_args(parser)
    args = parser.parse_args(argv)

    args.token_kwargs = _asana.token_request(args)
    if not args.project and not args.parent:
        parser.error("--project or --parent is required")
    if sum(bool(x) for x in (args.notes, args.notes_file, args.html_notes_file)) > 1:
        parser.error("use one of --notes, --notes-file and --html-notes-file")
    if args.section and not args.project:
        parser.error("--section needs --project")
    validate_dates(parser, args)
    validate_insert_after_flag(parser, args)
    if args.workspace is not None and not args.workspace.strip().isdigit():
        parser.error("--workspace must be a workspace GID (digits only)")
    # A token option usually means another workspace: with no --workspace, leave
    # it out of the request (--project or --parent already sets it).
    args.workspace_gid = (args.workspace or "").strip() or (
        "" if args.token_kwargs else _asana.WORKSPACE)
    # A pasted task URL becomes its bare GID, so API paths and parent checks match.
    if args.parent and "/" in args.parent:
        try:
            args.parent = _asana.extract_task_gid(args.parent)
        except ValueError as exc:
            parser.error(str(exc))
    return args


def strict_date(value):
    """A YYYY-MM-DD date, or None. fromisoformat alone also takes 20261029."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_dates(parser, args):
    """Refuse a bad date here: Asana answers one with HTTP 400 after the
    duplicate check has already run."""
    if args.due and strict_date(args.due) is None:
        parser.error("--due must be YYYY-MM-DD")
    if args.start_on:
        if not args.due:
            parser.error("--start-on needs --due (Asana sets a start date only with a due date)")
        start, due = strict_date(args.start_on), strict_date(args.due)
        if start is None:
            parser.error("--start-on must be YYYY-MM-DD")
        if start > due:
            parser.error(f"--start-on {args.start_on} is after --due {args.due}")


def validate_insert_after_flag(parser, args):
    """--insert-after places a subtask only. Refuse every other use before
    anything is written, so the flag never silently does nothing."""
    if args.insert_after is None:
        return
    if not re.fullmatch(r"[0-9]+", args.insert_after):
        parser.error("--insert-after must be a task GID (digits only)")
    if not args.parent:
        parser.error("--insert-after needs --parent (it places a subtask)")
    if args.project:
        parser.error("--insert-after works only with a subtask create (--parent alone)")


def read_file_body_or_exit(path, flag_label):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError as exc:
        print(f"REFUSING: cannot read {flag_label} {path!r}: {exc}", file=sys.stderr)
        raise SystemExit(2)


def build_payload(args):
    data = {"name": args.name}
    if args.assignee:
        data["assignee"] = args.assignee
    if args.notes:
        data["notes"] = args.notes
    elif args.notes_file:
        body = read_file_body_or_exit(args.notes_file, "--notes-file")
        if not body:
            print(f"REFUSING: --notes-file {args.notes_file!r} is empty", file=sys.stderr)
            raise SystemExit(2)
        data["notes"] = body
    elif args.html_notes_file:
        body = read_file_body_or_exit(args.html_notes_file, "--html-notes-file")
        try:
            data["html_notes"] = _asana.wrap_body(body)
        except ValueError as exc:
            print(f"REFUSING: --html-notes-file body is invalid: {exc}", file=sys.stderr)
            raise SystemExit(2)
    if args.due:
        data["due_on"] = args.due
    if args.start_on:
        data["start_on"] = args.start_on

    if not args.parent:
        if args.workspace_gid:
            data["workspace"] = args.workspace_gid
        data["projects"] = [args.project]
    return {"data": data}


def find_duplicates(token, project_gid, name, parent_gid=None):
    if parent_gid:
        path = f"/tasks/{parent_gid}/subtasks"
    else:
        path = f"/projects/{project_gid}/tasks"
    tasks = _asana.paginate(
        path,
        token,
        params={"opt_fields": "name,gid,completed"},
    )
    target = name.strip().lower()
    return [
        task for task in tasks
        if task.get("name", "").strip().lower() == target
    ]


def refuse_duplicates(args, duplicates):
    if args.parent:
        location = f"under parent {args.parent}"
    else:
        location = f"in project {args.project}"
    print(
        f"REFUSING: {len(duplicates)} task(s) named '{args.name}' already exist "
        f"{location}:",
        file=sys.stderr,
    )
    for task in duplicates:
        state = "done" if task.get("completed") else "open"
        print(f"  - [{state}] {task_url(task['gid'])}", file=sys.stderr)
    print(
        "Pass --allow-duplicates to create anyway, or update an existing task instead.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def create_path(args):
    if args.parent:
        return f"/tasks/{args.parent}/subtasks"
    return "/tasks"


def response_gid(response):
    if not isinstance(response, dict):
        return None
    data = response.get("data")
    if not isinstance(data, dict):
        return None
    return data.get("gid")


def create_or_resume(args, token, payload, preexisting_gids):
    def find_new_gid():
        duplicates = find_duplicates(
            token, args.project, args.name, parent_gid=args.parent
        )
        return next(
            (
                task.get("gid")
                for task in duplicates
                if task.get("gid") and task.get("gid") not in preexisting_gids
            ),
            None,
        )

    def raise_uncertainty():
        raise SystemExit(
            "UNCERTAIN: Asana create may have landed, but no new same-name "
            "task could be identified; refusing to adopt a pre-existing task"
        )

    def resume_new_task_or_exit():
        try:
            gid = find_new_gid()
        except Exception:
            raise_uncertainty()
        if gid:
            print("resumed: create had already landed", file=sys.stderr)
            return gid
        raise_uncertainty()

    try:
        response = _asana.request(
            "POST", create_path(args), token, data=payload
        )
    except Exception:
        return resume_new_task_or_exit()

    gid = response_gid(response)
    if gid:
        return gid

    return resume_new_task_or_exit()


def intended_placements(args):
    placements = []
    if args.project:
        section = args.section or _asana.DEFAULT_SECTIONS.get(args.project)
        placements.append(
            {
                "project": args.project,
                "section": section,
                "add_initially": bool(section),
            }
        )
    for project_gid in args.multi_home:
        placements.append(
            {
                "project": project_gid,
                "section": _asana.DEFAULT_SECTIONS.get(project_gid),
                "add_initially": True,
            }
        )
    return placements


def add_project(task_gid, token, placement):
    body = {"project": placement["project"]}
    if placement["section"]:
        body["section"] = placement["section"]
    return _asana.request(
        "POST",
        f"/tasks/{task_gid}/addProject",
        token,
        data={"data": body},
    )


def apply_initial_placements(task_gid, token, placements):
    for placement in placements:
        if not placement["add_initially"]:
            continue
        try:
            add_project(task_gid, token, placement)
        except Exception:
            # The write may have landed even if its response was lost. The
            # verification below decides whether a repair is needed.
            pass


def get_task(task_gid, token):
    return _asana.request(
        "GET",
        f"/tasks/{task_gid}",
        token,
        params={"opt_fields": TASK_OPT_FIELDS},
    )["data"]


def missing_placements(task, parent_gid, placements):
    missing = []
    if parent_gid and (task.get("parent") or {}).get("gid") != parent_gid:
        missing.append({"kind": "parent", "gid": parent_gid})

    projects = {
        project.get("gid") for project in task.get("projects", []) if project
    }
    memberships = {
        (
            (membership.get("project") or {}).get("gid"),
            (membership.get("section") or {}).get("gid"),
        )
        for membership in task.get("memberships", [])
    }
    seen = set()
    for placement in placements:
        project_gid = placement["project"]
        section_gid = placement["section"]
        key = (project_gid, section_gid)
        if key in seen:
            continue
        seen.add(key)
        if project_gid not in projects:
            missing.append({"kind": "project", "placement": placement})
        elif section_gid and (project_gid, section_gid) not in memberships:
            missing.append({"kind": "section", "placement": placement})
    return missing


def verify_and_repair(task_gid, token, parent_gid, placements):
    missing = missing_placements(get_task(task_gid, token), parent_gid, placements)
    repairs = [item for item in missing if item["kind"] != "parent"]
    if repairs:
        for repair in repairs:
            try:
                add_project(task_gid, token, repair["placement"])
            except Exception:
                pass
        missing = missing_placements(
            get_task(task_gid, token), parent_gid, placements
        )
    return missing


def describe_missing(item):
    if item["kind"] == "parent":
        return f"parent {item['gid']}"
    placement = item["placement"]
    if item["kind"] == "section":
        return (
            f"section {placement['section']} membership in project "
            f"{placement['project']}"
        )
    return f"project {placement['project']} membership"


def people_workspace(args, token):
    """The workspace to look up --follower emails in: --workspace or the
    config, else read from the parent or the project (a GET)."""
    workspace = getattr(args, "workspace_gid", "")
    if workspace:
        return workspace
    path = f"/tasks/{args.parent}" if args.parent else f"/projects/{args.project}"
    try:
        data = _asana.request("GET", path, token, params={"opt_fields": "workspace.gid"})["data"]
        workspace = (data.get("workspace") or {}).get("gid")
    except Exception as exc:
        raise SystemExit(f"nothing created: could not read the workspace of {path} ({exc}); "
                         "pass --workspace <gid> or follower gids")
    if not workspace:
        raise SystemExit(f"nothing created: {path} names no workspace; pass --workspace <gid>")
    return workspace


def create_with_duplicate_guard(args, token, payload):
    # Resolve followers BEFORE the create, so a bad email fails with nothing written.
    followers = getattr(args, "follower", None) or []
    follower_gids = []
    if followers:
        workspace = ""
        if any(not str(f).strip().isdigit() for f in followers):
            workspace = people_workspace(args, token)
        follower_gids = [
            _asana.resolve_user_gid(f, token, workspace=workspace) for f in followers
        ]
    duplicates = find_duplicates(
        token, args.project, args.name, parent_gid=args.parent
    )
    if duplicates and not args.allow_duplicates:
        refuse_duplicates(args, duplicates)
    preexisting_gids = {
        task.get("gid") for task in duplicates if task.get("gid")
    }
    _asana.mark_task_data(payload["data"], token)
    task_gid = create_or_resume(args, token, payload, preexisting_gids)
    add_followers_or_warn(task_gid, token, follower_gids)
    return task_gid


def add_followers_or_warn(task_gid, token, follower_gids):
    """Add everyone involved as collaborators (idempotent; also covers a resumed create).

    A follower miss never fails the create: the task exists, so report PARTIAL and go on.
    """
    if not follower_gids:
        return
    try:
        _asana.request(
            "POST",
            f"/tasks/{task_gid}/addFollowers",
            token,
            data={"data": {"followers": follower_gids}},
        )
    except Exception as exc:
        print(
            f"PARTIAL: created {task_url(task_gid)} but addFollowers failed ({exc}); "
            f"add them by hand: {', '.join(follower_gids)}",
            file=sys.stderr,
        )


def verify_or_exit(task_gid, token, parent_gid, placements):
    missing = verify_and_repair(task_gid, token, parent_gid, placements)
    if not missing:
        return
    details = "; ".join(describe_missing(item) for item in missing)
    print(
        f"PARTIAL: created {task_url(task_gid)} but {details} did not land",
        file=sys.stderr,
    )
    raise SystemExit(1)


def set_parent_body(args):
    return {"data": {"parent": args.parent, "insert_after": args.insert_after}}


def place_after_or_warn(new_gid, token, args):
    """Move the new subtask after --insert-after, then read the order back.

    The task already exists, so a miss only warns (exit 0): never delete, never
    retry the create.
    """
    try:
        _asana.request("POST", f"/tasks/{new_gid}/setParent", token, data=set_parent_body(args))
        siblings = _asana.paginate(
            f"/tasks/{args.parent}/subtasks", token, params={"opt_fields": "gid"}
        )
        order = [row.get("gid") for row in siblings]
        at = order.index(new_gid) if new_gid in order else 0
        if at == 0 or order[at - 1] != args.insert_after:
            raise RuntimeError("the read-back shows a different position")
    except Exception as exc:
        print(
            f"WARNING: created {new_gid} but could not place it after {args.insert_after}: "
            f"{exc}. Move it in Asana.",
            file=sys.stderr,
        )
        return
    print(f"Placed after {args.insert_after}")


def dry_run_author_line(args, payload):
    """A token option usually means a person's token, so show the description
    as it would post: read the token and its owner (GETs only), then mark it."""
    data = payload["data"]
    if not (data.get("html_notes") or data.get("notes")):
        print("Author line: none (the task has no description)")
        return
    try:
        token = _asana.fetch_token(**args.token_kwargs)
    except (subprocess.CalledProcessError, SystemExit, OSError) as exc:
        print(f"Author line: unknown (could not read the token: {exc})")
        return
    _asana.mark_task_data(data, token)
    body = data.get("html_notes") or data.get("notes") or ""
    added = _asana.starts_with_author_line(body)
    print("Author line: " + ("added" if added else "none (agent account)"))


def main(argv=None):
    args = parse_args(argv)
    payload = build_payload(args)
    if args.dry_run:
        if args.token_kwargs:
            dry_run_author_line(args, payload)
        print(json.dumps(payload, indent=2))
        if args.insert_after:
            print("Then: POST /tasks/<new-task-gid>/setParent")
            print(json.dumps(set_parent_body(args), indent=2))
        return

    try:
        token = _asana.fetch_token(**args.token_kwargs)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"nothing created: could not read secret "
                 f"{args.token_kwargs.get('secret_name', 'default')!r}: "
                 f"{(exc.stderr or '').strip() or exc}")
    new_gid = create_with_duplicate_guard(args, token, payload)
    placements = intended_placements(args)
    apply_initial_placements(new_gid, token, placements)
    verify_or_exit(new_gid, token, args.parent, placements)

    print(f"Created: {task_url(new_gid)}")
    if args.insert_after:
        place_after_or_warn(new_gid, token, args)
    if not args.assignee:
        print(
            "NOTE: unassigned. Suggest an assignee to the user (or ask) unless they "
            "chose to leave it unassigned."
        )


if __name__ == "__main__":
    main()
