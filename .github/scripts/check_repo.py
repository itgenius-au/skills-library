#!/usr/bin/env python3
"""Repo checks for skills-library. Stdlib only. Exit 0 = clean, 1 = findings, 2 = cannot run.

Usage: check_repo.py [repo-root]

Checks:
  1. Both manifests parse and carry the same version.
  2. The marketplace plugin entry has no `skills` list. Beside a plugin.json, that list
     makes the plugin fail to load ("conflicting manifests").
  3. Every skills/<name>/SKILL.md has frontmatter, a `name` equal to its folder, and a
     description.
  4. Every relative link in the root *.md files and docs/*.md resolves. Same-file anchors
     match a heading.
  5. Every skill that is not an alias has a row in the README, and every skill named in
     a README table exists.
"""
import json
import pathlib
import re
import sys


def fail(findings, text):
    findings.append(text)


def frontmatter(text):
    """Return the frontmatter block as text, or None when the file has none."""
    match = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    return match.group(1) if match else None


def field(block, key):
    """Return a top-level scalar field, without its quotes. Empty string when absent."""
    match = re.search(rf"^{key}:[ \t]*(.*)$", block, re.M)
    if not match:
        return ""
    return match.group(1).strip().strip("'\"")


def slug(heading):
    """GitHub's anchor for a heading."""
    text = re.sub(r"`", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(text):
    without_code = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    return {slug(m) for m in re.findall(r"^#{1,6} +(.+?)\s*$", without_code, re.M)}


def check_manifests(root, findings):
    versions = {}
    for name in ("marketplace.json", "plugin.json"):
        path = root / ".claude-plugin" / name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            fail(findings, f"{path}: cannot read as JSON ({type(ex).__name__})")
            continue
        if name == "marketplace.json":
            versions[name] = data.get("metadata", {}).get("version")
            for plugin in data.get("plugins", []):
                if "skills" in plugin:
                    fail(findings, f"{name}: plugin '{plugin.get('name')}' must not list skills")
        else:
            versions[name] = data.get("version")
    values = set(versions.values())
    if len(versions) == 2 and (len(values) != 1 or None in values):
        fail(findings, f"manifest versions differ or are missing: {versions}")


def check_skills(root, findings):
    """Return (all skill names, non-alias skill names)."""
    names, real = set(), set()
    folders = sorted(p for p in (root / "skills").iterdir() if p.is_dir())
    if not folders:
        fail(findings, "skills/: no skill folders found")
    for folder in folders:
        path = folder / "SKILL.md"
        names.add(folder.name)
        if not path.is_file():
            fail(findings, f"{folder.name}: no SKILL.md")
            continue
        block = frontmatter(path.read_text(encoding="utf-8"))
        if block is None:
            fail(findings, f"{folder.name}: SKILL.md has no frontmatter")
            continue
        if field(block, "name") != folder.name:
            fail(findings, f"{folder.name}: frontmatter name is '{field(block, 'name')}'")
        description = field(block, "description")
        if not description:
            fail(findings, f"{folder.name}: no description")
        if not description.startswith("ALIAS"):
            real.add(folder.name)
    return names, real


def check_links(root, findings):
    pages = sorted(root.glob("*.md")) + sorted((root / "docs").glob("*.md"))
    for page in pages:
        text = page.read_text(encoding="utf-8")
        body = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
        known = anchors(text)
        for target in re.findall(r"\]\(([^)\s]+)\)", body):
            if re.match(r"[a-z][a-z0-9+.-]*:", target):
                continue
            path, _, anchor = target.partition("#")
            label = f"{page.relative_to(root)}: link {target}"
            if not path:
                if anchor not in known:
                    fail(findings, f"{label} matches no heading")
                continue
            resolved = (page.parent / path).resolve()
            if not resolved.exists():
                fail(findings, f"{label} does not resolve")
            elif anchor and resolved.suffix == ".md":
                if anchor not in anchors(resolved.read_text(encoding="utf-8")):
                    fail(findings, f"{label} matches no heading")


def check_readme(root, names, real, findings):
    text = (root / "README.md").read_text(encoding="utf-8")
    rows = set(re.findall(r"^\| `([a-z0-9-]+)`", text, re.M))
    for name in sorted(real - rows):
        fail(findings, f"README: skill '{name}' has no table row")
    for name in sorted(rows - names):
        fail(findings, f"README: table row names '{name}', which has no skill folder")


def main():
    if len(sys.argv) > 2:
        print(__doc__)
        return 2
    root = pathlib.Path(sys.argv[1] if len(sys.argv) == 2 else ".").resolve()
    if not (root / ".claude-plugin").is_dir() or not (root / "skills").is_dir():
        print(f"STOP: {root} is not the repo root")
        return 2
    findings = []
    check_manifests(root, findings)
    names, real = check_skills(root, findings)
    check_links(root, findings)
    check_readme(root, names, real, findings)
    for line in findings:
        print(line)
    print(f"{len(findings)} finding(s), {len(names)} skill folders, {len(real)} skills")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
