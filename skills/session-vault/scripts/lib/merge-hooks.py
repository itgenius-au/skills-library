#!/usr/bin/env python3
"""Idempotently add or remove the session-vault hooks in a Claude Code settings.json.

Adds a UserPromptSubmit -> bq-log-prompt.sh and a Stop -> bq-log-response.sh command
hook, preserving any existing hooks (e.g. an auto-commit hook) and never duplicating.
--remove takes exactly our two commands back out again. Backs up settings.json to
settings.json.bak before writing. Stdlib only.
"""

import argparse
import json
import os
import shutil
import sys


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError as e:
        print("settings.json is not valid JSON: %s" % e, file=sys.stderr)
        sys.exit(1)


def _has_command(groups, command):
    for g in groups:
        for h in g.get("hooks", []):
            if h.get("command") == command:
                return True
    return False


def add(settings, event, command):
    hooks = settings.setdefault("hooks", {})
    groups = hooks.setdefault(event, [])
    if _has_command(groups, command):
        return False
    groups.append({"hooks": [{"type": "command", "command": command}]})
    return True


def remove(settings, event, command):
    hooks = settings.get("hooks", {})
    groups = hooks.get(event, [])
    new_groups = []
    changed = False
    for g in groups:
        orig = g.get("hooks", [])
        kept = [h for h in orig if h.get("command") != command]
        if len(kept) != len(orig):
            changed = True
        if kept:
            ng = dict(g)
            ng["hooks"] = kept
            new_groups.append(ng)
        elif not orig:
            new_groups.append(g)  # unrelated empty group; leave it
    if changed:
        if new_groups:
            hooks[event] = new_groups
        else:
            hooks.pop(event, None)
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", required=True)
    ap.add_argument("--prompt-hook", required=True)
    ap.add_argument("--response-hook", required=True)
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    settings = load(a.settings)
    op = remove if a.remove else add
    changed = False
    if op(settings, "UserPromptSubmit", a.prompt_hook):
        changed = True
    if op(settings, "Stop", a.response_hook):
        changed = True

    if not changed:
        print("no change")
        return 0
    if a.dry_run:
        print("[dry-run] would update %s" % a.settings)
        print(json.dumps(settings.get("hooks", {}), indent=2))
        return 0

    if os.path.exists(a.settings):
        shutil.copy2(a.settings, a.settings + ".bak")
    parent = os.path.dirname(a.settings)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(a.settings, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("updated %s" % a.settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
