import json
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "SKILL.md"
TRIGGERS = (
    "update Asana",
    "update the Asana status",
    "post status to the tasks",
    "comment on these tasks",
    "Never write your own script",
    "draft an update",
    "post to that task",
    "document this into [task]",
    "add a comment",
    "update the task",
    "mark it complete",
    "create a task",
    "attach this to the task",
    "log time",
    "cross-post this",
)


def _description():
    frontmatter = SKILL.read_text(encoding="utf-8").split("---", 2)[1]
    match = re.search(r"^description: (\".*\")\s*$", frontmatter, re.MULTILINE)
    assert match, "description must be one double-quoted line"
    return json.loads(match.group(1))


def test_description_keeps_all_triggers_within_marketplace_limit():
    description = _description()
    assert len(description) <= 1024
    assert all(trigger in description for trigger in TRIGGERS)


def test_skill_names_only_scripts_that_exist():
    scripts = Path(__file__).resolve().parents[1]
    named = set(re.findall(r"scripts/([a-z_]+\.py)", SKILL.read_text(encoding="utf-8")))
    assert named, "SKILL.md names no scripts"
    assert sorted(n for n in named if not (scripts / n).exists()) == []
