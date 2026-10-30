# Changelog

This project uses semantic versions. A new or renamed skill is a minor bump. A fix or a docs
change is a patch.

## 1.3.1 - 2026-10-30

- Fixed `redact_doc.py --check`: it no longer prints a sensitive value found in a file name.

## 1.3.0 - 2026-10-30

- Added two skills for VM operators: `claude-vm-ops` and `session-recovery`.
- Added a secret scanner to `session-dsp`. `session-wrap` runs it before each push.
- Refreshed the review and dev skills, `session-wrap`, and `exec-summary` to the current versions.
- Split `review-swarm`, `dev-quick-build`, and `session-wrap` into a short `SKILL.md` plus
  reference files.
- Moved model names out of skill text, into each skill's wrapper script or one reference file.
- Added repo and install check scripts, plus `CONTRIBUTING.md`, `SECURITY.md`, and this changelog.

## 1.2.1 - 2026-10-30

- Added the [Claude Code on a VM](./docs/claude-code-vm-setup-spec.md) setup guide.

## 1.2.0 - 2026-10-22

- Fixed the plugin load failure by removing the `skills` list from `marketplace.json`.
- Refreshed 18 skills to the current versions.
- Renamed 8 skills. The old names stay as aliases until 2026-11-21.
- Added 7 skills.

## 1.1.0 - 2026-09-16

- Published the full dev process: the `dev-*` skills and the build and ship playbook.

## 1.0.0 - 2026-09-04

- First single-plugin release.
