#!/usr/bin/env python3
"""Log a time entry on a task, for the user's OWN time.

Asana time entries are creator-locked: an entry shows its creator's name and
only that creator can change it. So the user's time must be logged with the
user's own token. This script uses personal_token_secret (config) or
ASANA_PERSONAL_TOKEN when set, else the normal token (see _asana.py).

    log_time.py <task> --minutes 30 [--date 2026-04-22]

Another workspace: --token-secret <secret> [--token-project <GCP project>].
Use the token of YOUR login in that workspace: the entry shows that login's
name. Time tracking needs a paid Asana plan that includes it.
"""

import argparse
import json
import subprocess
import sys
from datetime import date as date_cls

from _asana import add_token_args, fetch_token, request, task_url, extract_task_gid, token_request


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task")
    p.add_argument("--minutes", type=int, required=True)
    p.add_argument("--date", default=date_cls.today().isoformat(),
                   help="YYYY-MM-DD (default: today)")
    p.add_argument("--dry-run", action="store_true")
    add_token_args(p)
    args = p.parse_args()
    token_kwargs = token_request(args)

    payload = {"data": {"duration_minutes": args.minutes, "entered_on": args.date}}
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return

    task_gid = extract_task_gid(args.task)
    try:
        token = fetch_token(personal=True, **token_kwargs)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"nothing logged: could not read secret "
                 f"{token_kwargs.get('secret_name', 'default')!r}: "
                 f"{(exc.stderr or '').strip() or exc}")
    resp = request("POST", f"/tasks/{task_gid}/time_tracking_entries", token, data=payload)
    entry_gid = resp["data"]["gid"]
    print(f"Logged {args.minutes}m on {args.date} to {task_url(task_gid)} (entry {entry_gid})")


if __name__ == "__main__":
    main()
