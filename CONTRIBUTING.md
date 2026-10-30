# Contributing

Issues and pull requests are welcome.

## Report a problem

Open an issue with the skill name, your Claude Code version (`claude --version`), and what
you saw. For an install problem, paste the output of `claude plugin list`. For a security
problem, follow [SECURITY.md](./SECURITY.md) instead.

## Add or change a skill

Each skill lives in `skills/<name>/`, with a `SKILL.md` and any `scripts/` or `references/` it
needs.

- The frontmatter `name` must equal the folder name.
- The `description` says what the skill does and when to use it, and ends with its trigger
  phrases.
- A stranger with none of our other tools must be able to follow every step.
- Do not hard-code secrets, private paths, or account details.
- Keep model names in one place for each skill, so they are easy to change.
- Keep `SKILL.md` under about 500 lines. Move detail into `references/`, with a pointer that
  says when to read it.
- If you adapt third-party work, follow its license and add it to
  [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).
- Add a row for a new skill to the README, with its prerequisites.

## Check your change

```bash
python3 .github/scripts/check_repo.py
bash .github/scripts/install_test.sh .
```

The install test needs the `claude` CLI, but no login. Run both before you open a pull request.

Also run the tests of any skill you change, for example `python3 -m pytest skills/<name>`. Some
skills use a `run-tests.sh` script instead.

## Versions and releases

We use semantic versions. A new or renamed skill is a minor bump. A fix or a docs change is
a patch. Bump the version in both `.claude-plugin/marketplace.json` and
`.claude-plugin/plugin.json`, and add an entry to [CHANGELOG.md](./CHANGELOG.md). Tag each
release with `claude plugin tag --push`, which creates a tag such as `skills-library--v1.3.0`.

## Renamed skills

An old skill name stays as a small alias for 30 days after a rename, then it goes.

## Writing style

Use short sentences and plain words. Do not use em dashes in customer-facing text.
