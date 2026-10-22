#!/usr/bin/env python3
"""Tests for tag_trigger_check.py. Runs under pytest, or directly: python3 test_tag_trigger_check.py"""
import os
import subprocess
import sys
import tempfile
import textwrap

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tag_trigger_check.py")
ENV = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True, env=ENV).stdout.strip()


def run(workflows, *extra):
    """workflows: {filename: yaml text} or None for a repo with no workflow dir. -> (rc, stdout)"""
    with tempfile.TemporaryDirectory() as d:
        git(d, "init", "-q")
        open(os.path.join(d, "README"), "w").write("x\n")
        if workflows:
            os.makedirs(os.path.join(d, ".github", "workflows"))
            for name, text in workflows.items():
                os.makedirs(os.path.dirname(os.path.join(d, ".github", "workflows", name)), exist_ok=True)
                open(os.path.join(d, ".github", "workflows", name), "w").write(textwrap.dedent(text))
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "c")
        sha = git(d, "rev-parse", "HEAD")
        p = subprocess.run([sys.executable, "-I", SCRIPT, d, sha, *extra], capture_output=True, text=True, env=ENV)
        return p.returncode, p.stdout, p.stderr


def verdict(yaml_text, *extra):
    rc, out, _ = run({"w.yml": yaml_text}, *extra)
    word = out.split("\t")[0]
    assert (rc == 0) == (word == "SAFE"), (rc, out)
    return word


def test_no_workflows_is_safe():
    rc, out, _ = run(None)
    assert rc == 0 and out.startswith("SAFE")


def test_scalar_push_triggers():
    assert verdict("on: push\njobs: {}\n") == "TRIGGERS"


def test_list_push_triggers():
    assert verdict("on: [pull_request, push]\njobs: {}\n") == "TRIGGERS"


def test_list_without_push_is_safe():
    assert verdict("on: [pull_request, workflow_dispatch]\njobs: {}\n") == "SAFE"


def test_unfiltered_push_triggers():
    assert verdict("on:\n  push:\njobs: {}\n") == "TRIGGERS"


def test_push_with_only_paths_triggers():
    assert verdict("on:\n  push:\n    paths: ['src/**']\njobs: {}\n") == "TRIGGERS"


def test_push_with_only_paths_ignore_triggers():
    assert verdict("on:\n  push:\n    paths-ignore: ['docs/**']\njobs: {}\n") == "TRIGGERS"


def test_branches_only_is_safe():
    assert verdict("on:\n  push:\n    branches: [main]\njobs: {}\n") == "SAFE"


def test_branches_ignore_only_is_safe():
    assert verdict("on:\n  push:\n    branches-ignore: ['wip/**']\njobs: {}\n") == "SAFE"


def test_branches_and_paths_is_safe():
    assert verdict("on:\n  push:\n    branches: [main]\n    paths: ['src/**']\njobs: {}\n") == "SAFE"


def test_create_triggers():
    assert verdict("on:\n  create:\njobs: {}\n") == "TRIGGERS"


def test_create_in_list_triggers():
    assert verdict("on: [create]\njobs: {}\n") == "TRIGGERS"


def test_tags_single_star_does_not_cross_slash():
    # archive/<date>/x has two slashes after archive/, so archive/* does not match it.
    assert verdict("on:\n  push:\n    tags: ['archive/*']\njobs: {}\n") == "SAFE"


def test_tags_double_star_crosses_slash():
    assert verdict("on:\n  push:\n    tags: ['archive/**']\njobs: {}\n") == "TRIGGERS"


def test_tags_star_star_segments():
    assert verdict("on:\n  push:\n    tags: ['archive/*/*']\njobs: {}\n") == "TRIGGERS"


def test_tags_version_filter_is_safe():
    assert verdict("on:\n  push:\n    tags: ['v*']\njobs: {}\n") == "SAFE"


def test_tags_as_plain_string():
    assert verdict("on:\n  push:\n    tags: 'archive/**'\njobs: {}\n") == "TRIGGERS"


def test_dot_in_pattern_is_literal():
    assert verdict("on:\n  push:\n    tags: ['archive/2026-10-1x/**']\njobs: {}\n") == "SAFE"


def test_tags_ignore_excluding_archive_is_safe():
    assert verdict("on:\n  push:\n    tags-ignore: ['archive/**']\njobs: {}\n") == "SAFE"


def test_tags_ignore_not_matching_triggers():
    assert verdict("on:\n  push:\n    tags-ignore: ['v*']\njobs: {}\n") == "TRIGGERS"


def test_custom_tag_prefix():
    y = "on:\n  push:\n    tags: ['bk/**']\njobs: {}\n"
    assert verdict(y, "--tag-prefix", "bk/") == "TRIGGERS"
    assert verdict(y) == "SAFE"


def test_complex_glob_is_unsure():
    assert verdict("on:\n  push:\n    tags: ['archive/[a-z]*']\njobs: {}\n") == "UNSURE"


def test_negated_pattern_is_unsure():
    assert verdict("on:\n  push:\n    tags: ['archive/**', '!archive/keep']\njobs: {}\n") == "UNSURE"


def test_broken_yaml_is_unsure():
    assert verdict("on: [unclosed\n") == "UNSURE"


def test_no_on_block_is_unsure():
    assert verdict("name: x\njobs: {}\n") == "UNSURE"


def test_one_bad_file_fails_the_commit():
    rc, out, _ = run({"a.yml": "on: [pull_request]\njobs: {}\n", "b.yaml": "on: push\njobs: {}\n"})
    assert rc == 1 and "SAFE\t.github/workflows/a.yml" in out and "TRIGGERS\t.github/workflows/b.yaml" in out


def test_non_yaml_files_are_ignored():
    rc, out, _ = run({"notes.txt": "on: push\n", "a.yml": "on: [pull_request]\njobs: {}\n"})
    assert rc == 0, out


def test_real_tag_name_is_judged_not_a_sample():
    y = "on:\n  push:\n    tags: ['archive/*/feature/*']\njobs: {}\n"
    assert verdict(y, "--tag", "archive/2026-10-14/feature/payments") == "TRIGGERS"
    assert verdict(y, "--tag", "archive/2026-10-14/hotfix") == "SAFE"
    # The made-up flat sample cannot see this filter: that is why the real names are passed.
    assert verdict(y) == "SAFE"


def test_any_of_several_real_tags_can_trigger():
    y = "on:\n  push:\n    tags: ['archive/*/feature/**']\njobs: {}\n"
    assert verdict(y, "--tag", "archive/2026-10-14/a", "--tag", "archive/2026-10-14/feature/b") == "TRIGGERS"


def test_unreadable_workflow_tree_is_an_error_not_no_workflows():
    with tempfile.TemporaryDirectory() as d:
        git(d, "init", "-q")
        os.makedirs(os.path.join(d, ".github", "workflows"))
        open(os.path.join(d, ".github", "workflows", "w.yml"), "w").write("on: push\n")
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "c")
        sha = git(d, "rev-parse", "HEAD")
        tree = git(d, "rev-parse", f"{sha}:.github")
        os.remove(os.path.join(d, ".git", "objects", tree[:2], tree[2:]))  # the .github tree object is gone
        p = subprocess.run([sys.executable, "-I", SCRIPT, d, sha], capture_output=True, text=True, env=ENV)
        assert p.returncode == 2 and "SAFE" not in p.stdout, (p.returncode, p.stdout, p.stderr)


def test_unreadable_workflow_blob_is_an_error_exit_2():
    with tempfile.TemporaryDirectory() as d:
        git(d, "init", "-q")
        os.makedirs(os.path.join(d, ".github", "workflows"))
        open(os.path.join(d, ".github", "workflows", "w.yml"), "w").write("on: push\n")
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "c")
        sha = git(d, "rev-parse", "HEAD")
        blob = git(d, "rev-parse", f"{sha}:.github/workflows/w.yml")
        os.remove(os.path.join(d, ".git", "objects", blob[:2], blob[2:]))  # listed in the tree, unreadable
        p = subprocess.run([sys.executable, "-I", SCRIPT, d, sha], capture_output=True, text=True, env=ENV)
        assert p.returncode == 2 and "SAFE" not in p.stdout and "cannot read" in p.stderr, (p.returncode, p.stdout, p.stderr)


def test_subdirectory_of_the_repo_still_reads_the_root_workflows():
    with tempfile.TemporaryDirectory() as d:
        git(d, "init", "-q")
        os.makedirs(os.path.join(d, ".github", "workflows"))
        os.makedirs(os.path.join(d, "sub", "deeper"))
        open(os.path.join(d, ".github", "workflows", "w.yml"), "w").write("on: push\n")
        open(os.path.join(d, "sub", "deeper", "f.txt"), "w").write("x\n")
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "c")
        sha = git(d, "rev-parse", "HEAD")
        for sub in ("sub", "sub/deeper"):
            p = subprocess.run([sys.executable, "-I", SCRIPT, os.path.join(d, sub), sha], capture_output=True, text=True, env=ENV)
            assert p.returncode == 1 and p.stdout.startswith("TRIGGERS"), (sub, p.returncode, p.stdout, p.stderr)


def test_tags_ignore_is_judged_per_tag():
    y = "on:\n  push:\n    tags-ignore: ['archive/*/keep']\njobs: {}\n"
    # one supplied tag is ignored, the other is not: the second would start the workflow
    assert verdict(y, "--tag", "archive/2026-10-14/keep", "--tag", "archive/2026-10-14/other") == "TRIGGERS"
    assert verdict(y, "--tag", "archive/2026-10-14/keep") == "SAFE"


def test_tags_filter_is_judged_per_tag():
    y = "on:\n  push:\n    tags: ['archive/*/keep']\njobs: {}\n"
    assert verdict(y, "--tag", "archive/2026-10-14/other", "--tag", "archive/2026-10-14/keep") == "TRIGGERS"
    assert verdict(y, "--tag", "archive/2026-10-14/other") == "SAFE"


def test_absent_workflow_dir_is_safe_even_with_other_dirs():
    rc, out, _ = run({})  # no workflows written: only README
    assert rc == 0 and out.startswith("SAFE")


def test_quoted_and_non_ascii_file_names_are_reviewed():
    rc, out, _ = run({'we"ird \u00e9 deploy.yml': "on: push\njobs: {}\n", "caf\u00e9.yaml": "on: [pull_request]\njobs: {}\n"})
    assert rc == 1 and "TRIGGERS" in out and "SAFE" in out and "deploy.yml" in out, out


def test_nested_workflow_file_is_reviewed():
    rc, out, _ = run({"sub/x.yml": "on: push\njobs: {}\n"})
    assert rc == 1 and "TRIGGERS" in out, out


def test_double_star_only_trusted_as_the_last_segment():
    for pat in ("**/archive/**", "archive/**/feature/**", "archive/**/x", "**/x", "a**b"):
        y = f"on:\n  push:\n    tags: ['{pat}']\njobs: {{}}\n"
        assert verdict(y, "--tag", "archive/2026-10-14/feature/x") == "UNSURE", pat
        y = f"on:\n  push:\n    tags-ignore: ['{pat}']\njobs: {{}}\n"
        assert verdict(y, "--tag", "archive/2026-10-14/feature/x") == "UNSURE", pat


def test_trailing_double_star_and_bare_double_star_still_work():
    assert verdict("on:\n  push:\n    tags: ['**']\njobs: {}\n", "--tag", "archive/2026-10-14/x") == "TRIGGERS"
    assert verdict("on:\n  push:\n    tags: ['archive/**']\njobs: {}\n", "--tag", "archive/2026-10-14/x") == "TRIGGERS"
    assert verdict("on:\n  push:\n    tags: ['v**']\njobs: {}\n", "--tag", "archive/2026-10-14/x") == "UNSURE"


def test_bad_sha_is_an_error():
    with tempfile.TemporaryDirectory() as d:
        git(d, "init", "-q")
        p = subprocess.run([sys.executable, "-I", SCRIPT, d, "0" * 40], capture_output=True, text=True, env=ENV)
        assert p.returncode == 2


if __name__ == "__main__":
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("SKIP - PyYAML not installed (pip install pyyaml)")
        sys.exit(0)
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    bad = 0
    for n, f in tests:
        try:
            f()
            print(f"ok   - {n}")
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"FAIL - {n}: {e!r}", file=sys.stderr)
    if bad:
        print(f"{bad} test(s) failed", file=sys.stderr)
        sys.exit(1)
    print(f"all {len(tests)} tag_trigger_check tests passed")
