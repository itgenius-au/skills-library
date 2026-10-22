#!/usr/bin/env python3
"""Would pushing an archive tag start a GitHub Actions workflow at this commit?

Usage: tag_trigger_check.py <repo-dir> <sha> [--tag NAME ...] [--tag-prefix archive/]

--tag NAME (repeatable) is a tag that WILL be pushed; each filter is tested against exactly
those names. Without --tag it falls back to two made-up samples under --tag-prefix, which can
miss a filter such as `archive/**/feature/**`: always pass the real names when you have them.

GitHub runs the workflow files of the TAGGED commit, so the files at <sha> decide.
Prints one line per workflow file: SAFE / TRIGGERS / UNSURE, with the reason.
Exit 0 only if every file is SAFE (or there are no workflows); 1 if any file is
TRIGGERS or UNSURE; 2 on a usage or environment error (bad repo, bad sha, no PyYAML, or
a workflow directory or file could not be read, which is not the same as having none).

Rules (repo-cleanup references/stale-work.md, 3a). A tag push starts the workflow when:
  - `on: push` (scalar or list), a `push:` with no filters, or a `push:` with only
    paths / paths-ignore (path filters are not applied to tag pushes);
  - `push.tags` matches the tag, or `push.tags-ignore` does not exclude it
    (`*` stops at `/`, `**` does not);
  - the workflow listens to `create`.
`push:` with branches / branches-ignore and no tags filter does not run on tags.
Anything it cannot parse or classify is UNSURE: conservative on purpose.
"""
import datetime
import os
import re
import subprocess
import sys


def git(repo, *args):
    """Run git with bytes-safe arguments (file names are bytes, not always valid UTF-8)."""
    cmd = [os.fsencode(x) for x in ("git", "-C", repo, *args)]
    return subprocess.run(cmd, capture_output=True)


def sample_tags(prefix):
    # Branch names may contain slashes, so test a flat and a nested tag name; a filter
    # that matches either one counts as matching (conservative).
    d = datetime.date.today().isoformat()
    return [f"{prefix}{d}/x", f"{prefix}{d}/a/b"]


def glob_match(pattern, name):
    """GitHub filter glob -> True/False, or None when the pattern is too exotic to trust."""
    if not isinstance(pattern, str) or pattern.startswith("!") or any(c in pattern for c in "[]?+"):
        return None
    # `**` is only trusted as the last segment (`.../**` or a bare `**`): in the middle of a
    # pattern GitHub's matching is subtle, so say UNSURE rather than guess either way.
    if "**" in pattern and not (pattern == "**" or (pattern.endswith("/**") and pattern.count("**") == 1)):
        return None
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.fullmatch("".join(out), name) is not None


def as_list(v):
    if v is None:
        return []
    return [v] if isinstance(v, str) else v


def any_match(patterns, tags):
    """True/False, or None if any pattern is unreadable."""
    hits = [glob_match(p, t) for p in patterns for t in tags]
    if None in hits:
        return None
    return any(hits)


def push_fires_on_tag(cfg, tags):
    if cfg is None:
        return True, "push with no filters"
    if not isinstance(cfg, dict):
        return None, "unreadable push block"
    if "tags" in cfg and "tags-ignore" in cfg:
        return None, "push has both tags and tags-ignore"
    # Each supplied tag is judged on its own; the file triggers if any one of them would.
    if "tags" in cfg:
        pats = as_list(cfg["tags"])
        ms = [any_match(pats, [t]) for t in tags]
        if None in ms:
            return None, "tags filter with complex glob"
        return any(ms), f"tags filter {pats}"
    if "tags-ignore" in cfg:
        pats = as_list(cfg["tags-ignore"])
        ms = [any_match(pats, [t]) for t in tags]
        if None in ms:
            return None, "tags-ignore with complex glob"
        return any(not m for m in ms), f"tags-ignore {pats}"
    if "branches" in cfg or "branches-ignore" in cfg:
        return False, "push limited to branches"
    return True, "push with only paths/other filters"


def check(text, tags):
    import yaml

    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return "UNSURE", f"yaml error: {str(e).splitlines()[0]}"
    if not isinstance(doc, dict):
        return "UNSURE", "not a mapping"
    on = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on` key as True
    if on is None:
        return "UNSURE", "no on: block"
    if isinstance(on, str):
        on = [on]
    if isinstance(on, list):
        if "push" in on or "create" in on:
            return "TRIGGERS", f"on: {on}"
        return "SAFE", f"on: {on}"
    if isinstance(on, dict):
        if "create" in on:
            return "TRIGGERS", "create event"
        if "push" in on:
            fires, why = push_fires_on_tag(on["push"], tags)
            if fires is None:
                return "UNSURE", why
            return ("TRIGGERS" if fires else "SAFE"), why
        return "SAFE", "no push/create: " + ",".join(map(str, on.keys()))
    return "UNSURE", "unreadable on: block"


def main(argv):
    args, prefix, tags = [], "archive/", []
    it = iter(argv)
    for a in it:
        if a in ("--tag-prefix", "--tag"):
            val = next(it, None)
            if not val:
                print(f"{a} needs a value", file=sys.stderr)
                return 2
            if a == "--tag":
                tags.append(val)
            else:
                prefix = val
        else:
            args.append(a)
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    repo, sha = args
    try:
        import yaml  # noqa: F401  (imported here so a usage error does not need it)
    except ImportError:
        print("tag_trigger_check.py needs PyYAML: pip install pyyaml", file=sys.stderr)
        return 2
    if git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        print(f"cannot read commit {sha} in {repo}", file=sys.stderr)
        return 2
    tags = tags or sample_tags(prefix)
    # ls-tree exits 0 with no output when the directory is absent, and non-zero when git
    # cannot read the tree. Only the first means "no workflows"; the second must not pass.
    # -z -r: raw names, so quoted or non-ASCII files are still listed; nested files included.
    # --full-tree: the path is relative to the repo root even when <repo-dir> is a subdirectory.
    ls = git(repo, "ls-tree", "--full-tree", "-z", "-r", "--name-only", sha, "--", ".github/workflows/")
    if ls.returncode != 0:
        print(f"cannot read .github/workflows at {sha}: {ls.stderr.decode(errors='replace').strip()}", file=sys.stderr)
        return 2
    names = [n for n in ls.stdout.split(b"\0") if n]
    if not names:
        print("SAFE\t(no workflows)")
        return 0
    bad = 0
    for name in names:
        shown = name.decode("utf-8", "backslashreplace")
        if not name.lower().endswith((b".yml", b".yaml")):
            continue
        show = git(repo, "show", os.fsencode(sha) + b":" + name)
        if show.returncode != 0:
            # Listed but unreadable: git cannot be trusted here, so this is an error, not a verdict.
            print(f"cannot read {shown} at {sha}: {show.stderr.decode(errors='replace').strip()}", file=sys.stderr)
            return 2
        verdict, why = check(show.stdout, tags)
        print(f"{verdict}\t{shown}\t{why}")
        bad += verdict != "SAFE"
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
