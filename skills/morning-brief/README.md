# Morning Brief (portable skill)

A Claude Code skill that builds a daily "morning brief" from **Google Calendar + Gmail + Asana** (and optionally Google Chat), triages email signal from noise, renders an ADHD-friendly **mission-control HUD** as a private Artifact, and posts a text digest to your Google Chat space.

## What's in here
- `SKILL.md` - the skill (workflow, triage rules, draft-reply checkpoint, always-post + failure handling, and a good-result check).
- `template.html` - the known-good HUD build the skill renders into. **All data in it is generic sample data** - the skill replaces it each run.

## Install
Drop the `morning-brief/` folder into your skills directory:
- Project-scoped: `<your-repo>/.claude/skills/morning-brief/`
- Or global: `~/.claude/skills/morning-brief/`

Then invoke with `/morning-brief` (or "brief me" / "what's on today").

## Configure (see the "Setup" table at the top of SKILL.md)
Fill in your own values - nothing org-specific is baked in:
- **Timezone** - your IANA zone + label.
- **Connectors** - Google Calendar, Gmail, Asana (and optionally a Google Chat read connector). The skill discovers connector tool IDs by keyword at runtime.
- **Chat post (optional)** - create an incoming webhook for your Google Chat space, store its URL as a secret in your secret manager, and set the secret **name** + project + space id in Setup. The repo/skill holds the secret *name* only, never the URL.
- **Leadership roster (optional)** - names + emails/domains of your leaders so triage flags their mail exactly (otherwise it infers from role).

## Safety model (unchanged from the original)
- **Read-only** on Calendar/Gmail/Asana. Never sends, replies to, or forwards mail.
- Two narrow, approval-gated writes only: the **Chat digest post** (to your own space) and **unsent Gmail drafts** (only if you say so).
- On any failure it retries once, then reports explicitly - it never goes silent.
