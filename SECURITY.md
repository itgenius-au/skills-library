# Security

Some skills in this library ship scripts and hooks that run on your machine, so we take
reports seriously.

## Report a vulnerability

Please use GitHub's private reporting: open the **Security** tab of this repository and choose
**Report a vulnerability**. Do not open a public issue.

Include the skill name, the version, what happens, and how to reproduce it.

## What counts

- A script or hook that can leak a secret, run unintended commands, or write outside its scope.
- A skill whose instructions lead an agent to bypass a stated safety gate.
- A leaked secret or private detail in this repository.

## Supported versions

We fix the latest release only. To update, run `claude plugin marketplace update skills-library`,
then `claude plugin update skills-library`.

## Before you run a skill

Read what a skill does before you run it, as you would with any script. A skill runs with
the permissions of your Claude Code session. Keys come from your own environment or secret
manager. Nothing in this repository hard-codes a key.
