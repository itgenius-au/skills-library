#!/usr/bin/env python3
"""Update fields on an existing Asana task. Refuses to rename by default.

Why: task titles belong to the people who manage the board, and an agent that
rewrites them breaks their search and trust. This script blocks `name`
updates unless --allow-rename is passed. Even then, ask before using it in an
agent flow.

    update_task.py <task> --assignee <user_gid>
    update_task.py <task> --unassign                 # clears the assignee
    update_task.py <task> --due 2026-05-01
    update_task.py <task> --complete
    update_task.py <task> --custom-field <field_gid>=<value_or_option_gid>
    update_task.py <task> --custom-field <field_gid>=2026-05-01    # date fields
    update_task.py <task> --multi-field <field_gid>=<option_gid>,<option_gid>
    update_task.py <task> --status-option <option_gid>   # custom-type status (a custom task type)
    update_task.py <task> --add-project <project_gid>=<section_gid>   # cross-post (repeatable)

Enum fields take the option GID as value. Date fields take YYYY-MM-DD (the
script wraps them in {"date": "..."} as Asana requires). Multi-enum fields
need --multi-field: Asana only accepts a LIST of option GIDs there, and the
list REPLACES every value the field held before.

A custom-type task (resource_subtype custom, a task type your workspace
defines) keeps its status in `custom_type_status_option`, not in a custom
field. --status-option sets it; take the option GID from the task's own
`custom_type.status_options.gid` (never hardcode it: an Asana rule can change
the type after a task is created).

--add-project adds the task to another project and keeps it in its current
ones. It reads the task first and leaves a project the task is already in
alone, whatever its section, because addProject on a project that holds the
task moves it. It reads the task again afterwards: a lost response can still
have landed, so the read-back decides, and a miss prints PARTIAL and exits 1.
Running the line again is safe.
"""

import argparse
import subprocess
import json
import sys

from _asana import add_token_args, fetch_token, request, task_url, extract_task_gid, token_request


def parse_custom_field(pair: str):
    if "=" not in pair:
        raise ValueError(f"bad --custom-field: {pair!r} (want gid=value)")
    gid, value = pair.split("=", 1)
    # YYYY-MM-DD -> date object form
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        return gid, {"date": value}
    return gid, value


def parse_multi_field(pair: str):
    if "=" not in pair:
        raise ValueError(f"bad --multi-field: {pair!r} (want gid=option_gid,option_gid)")
    gid, value = pair.split("=", 1)
    options = [o.strip() for o in value.split(",") if o.strip()]
    if not options:
        raise ValueError(f"bad --multi-field: {pair!r} (no option gids)")
    return gid, options


def parse_add_project(value: str):
    project, has_section, section = value.partition("=")
    gids = [project, section] if has_section else [project]
    if not all(gid.isascii() and gid.isdigit() for gid in gids):
        raise ValueError(f"bad --add-project: {value!r} (want project_gid or project_gid=section_gid)")
    return {"project": project, "section": section} if has_section else {"project": project}


def memberships(task_gid, token):
    fields = "memberships.project.gid,memberships.project.name,memberships.section.gid,memberships.section.name"
    task = request("GET", f"/tasks/{task_gid}", token, params={"opt_fields": fields})["data"]
    return {m["project"]["gid"]: m for m in task.get("memberships", []) if m.get("project")}


def landed(current, placement):
    membership = current.get(placement["project"])
    if membership is None:
        return False
    return "section" not in placement or (membership.get("section") or {}).get("gid") == placement["section"]


def place_label(membership):
    return f"{membership['project'].get('name')} / {(membership.get('section') or {}).get('name')}"


def cross_post(task_gid, token, placements):
    try:
        before = memberships(task_gid, token)
    except Exception as exc:
        sys.exit(f"nothing cross-posted: could not read {task_url(task_gid)}: {exc}")

    new = [p for p in placements if p["project"] not in before]
    for placement in new:
        try:
            request("POST", f"/tasks/{task_gid}/addProject", token, data={"data": placement})
        except Exception as exc:
            print(f"NOTE: addProject {placement['project']}: {exc}; reading the task to check", file=sys.stderr)

    try:
        after = memberships(task_gid, token)
    except Exception as exc:
        sys.exit(f"UNCERTAIN: could not read {task_url(task_gid)} back: {exc}; "
                 "read the task, then run the same line again, it leaves alone any board the task is on")

    for placement in placements:
        if placement in new:
            continue
        print(f"Already on: {place_label(before[placement['project']])}")
    for placement in new:
        if landed(after, placement):
            print(f"Cross-posted: {place_label(after[placement['project']])}")
    missing = [p["project"] for p in new if not landed(after, p)]
    if missing:
        sys.exit(f"PARTIAL: {task_url(task_gid)} did not land in {', '.join(missing)}; "
                 "fix the cause, then run the same line again, it leaves alone any board the task is on")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task")
    p.add_argument("--assignee")
    p.add_argument("--unassign", action="store_true",
                   help="Clear the assignee (sends assignee: null). Cannot be combined with --assignee.")
    p.add_argument("--due", help="YYYY-MM-DD")
    p.add_argument("--complete", action="store_true")
    p.add_argument("--incomplete", action="store_true")
    p.add_argument("--custom-field", action="append", default=[],
                   help="field_gid=value (repeatable)")
    p.add_argument("--multi-field", action="append", default=[],
                   help="multi-enum field: field_gid=option_gid,option_gid (repeatable; replaces the field's values)")
    p.add_argument("--status-option",
                   help="custom-type status option gid (sets custom_type_status_option)")
    p.add_argument("--add-project", action="append", default=[],
                   help="cross-post: project_gid=section_gid, or project_gid for the project's default section (repeatable)")
    p.add_argument("--name", help="RENAME: blocked without --allow-rename")
    p.add_argument("--allow-rename", action="store_true",
                   help="Override the rename block. Think twice before using this.")
    p.add_argument("--dry-run", action="store_true")
    add_token_args(p)
    args = p.parse_args()
    token_kwargs = token_request(args)

    if args.name and not args.allow_rename:
        print("REFUSING to rename task: task titles belong to the board's people.",
              file=sys.stderr)
        print("If truly needed, re-run with --allow-rename.", file=sys.stderr)
        sys.exit(2)

    if args.unassign and args.assignee is not None:
        p.error("--unassign cannot be combined with --assignee")

    data = {}
    if args.assignee:
        data["assignee"] = args.assignee
    if args.unassign:
        data["assignee"] = None
    if args.due:
        data["due_on"] = args.due
    if args.complete:
        data["completed"] = True
    if args.incomplete:
        data["completed"] = False
    if args.custom_field or args.multi_field:
        cf = {}
        try:
            for pair in args.custom_field:
                gid, value = parse_custom_field(pair)
                cf[gid] = value
            for pair in args.multi_field:
                gid, options = parse_multi_field(pair)
                if gid in cf:
                    raise ValueError(f"field {gid} given in both --custom-field and --multi-field")
                cf[gid] = options
        except ValueError as e:
            p.error(str(e))
        data["custom_fields"] = cf
    if args.status_option is not None:
        if not (args.status_option.isascii() and args.status_option.isdigit()):
            p.error(f"bad --status-option: {args.status_option!r} (want a numeric option gid)")
        data["custom_type_status_option"] = args.status_option
    if args.name and args.allow_rename:
        data["name"] = args.name

    try:
        placements = [parse_add_project(value) for value in args.add_project]
    except ValueError as e:
        p.error(str(e))

    if not data and not placements:
        p.error("nothing to update (provide at least one field)")

    payload = {"data": data}
    if args.dry_run:
        print(json.dumps({**payload, "add_project": placements} if placements else payload, indent=2))
        return

    task_gid = extract_task_gid(args.task)
    try:
        token = fetch_token(**token_kwargs)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"nothing written: could not read secret "
                 f"{token_kwargs.get('secret_name', 'default')!r}: "
                 f"{(exc.stderr or '').strip() or exc}")
    if data:
        resp = request("PUT", f"/tasks/{task_gid}", token, data=payload)
        print(f"Updated {task_url(task_gid)}")
        name = (resp or {}).get("data", {}).get("name")
        if name:
            print(f"Task: [{name}]({task_url(task_gid)})")
    if placements:
        cross_post(task_gid, token, placements)


if __name__ == "__main__":
    main()
