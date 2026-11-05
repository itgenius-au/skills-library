---
name: asana-update
description: "Every Asana write: a comment (new or edited), a task create or close, a field change, a description append, a file attachment or a time entry. Use it BEFORE any Asana write, even unprompted. Never write your own script that calls the Asana API. Triggers: 'update Asana', 'update the Asana status', 'post status to the tasks', 'comment on these tasks', 'draft an update', 'post to that task', 'document this into [task]', 'add a comment', 'update the task', 'mark it complete', 'close the task', 'create a task', 'add a subtask', 'attach this to the task', 'log time', 'cross-post this', an Asana URL with write intent."
---

# Asana Update: a safe write layer for Asana

Every Asana write goes through this skill, so that formatting, auth and
duplicate mistakes do not repeat. The bundled Python scripts handle the parts
that go wrong when an agent writes to Asana by hand: duplicate tasks, shell
escaping, overwritten descriptions, comments that Asana silently stores as
escaped text, and agent text that reads as if a person typed it.

## Setup

You need Python 3.9 or later. The scripts use only the standard library.

1. **A token.** Use one of these (the scripts try them in this order):
   - `--token-secret <secret> [--token-project <project>]` on the command line:
     a secret in Google Secret Manager, read with `gcloud`.
   - `token_secret` and `gcp_project` in the config file: the same, as a default.
   - The `ASANA_TOKEN` environment variable: an Asana personal access token
     (Asana: My settings > Apps > Developer apps > Create new token).

   With none of these, a script stops with exit 2 and says what to set.
2. **The config file.** Copy `templates/asana-update.config.example.json` to
   `~/.claude/asana-update.config.json` and fill in what you use. Set
   `ASANA_UPDATE_CONFIG` to read a file from another place.

| Key | Use |
|---|---|
| `workspace_gid` | Your Asana workspace. `find_task.py` needs it; `create_task.py` sends it with a `--project` create. |
| `user_gid`, `user_name`, `user_email` | Who you are (optional). The [author line](#author-line) uses `user_name` when the token lookup fails, and warns when a token is not yours. |
| `token_secret`, `gcp_project`, `gcloud_account` | The default token from Secret Manager. `gcloud_account` pins the gcloud login used for the read. |
| `personal_token_secret` | Your own token for time entries, when the default token is a shared account. `ASANA_PERSONAL_TOKEN` does the same. Set it only with `gcp_project`: a personal secret that cannot be read stops the entry (exit 2) rather than log it under another login. |
| `agent_user_gids` | Asana users that are agents or service accounts. Their writes get no author line. |
| `author_label` | The name in the author line (default `Claude`). |
| `default_sections` | `{"<project_gid>": "<section_gid>"}`: the section a new task lands in, for example each board's Inbox. |

Values still set to the template placeholders (`your_...`, `you@example.com`,
`Your Name`) count as unset. To find a gid, see
[`references/finding-gids.md`](references/finding-gids.md).

## The rules

1. **Write through these scripts only.** Do not write your own `curl`,
   `urllib` or `requests` call to `app.asana.com` for a write. The scripts add
   the author line, check the body, guard against duplicates and read the
   result back. A connector or MCP tool that writes as whoever is logged in
   skips all of that. Reads can use any tool.
2. **"Draft" means show it for review.** If the user says "draft a
   comment/update/reply", write it in the chat for them to approve. Do not post
   it. Post only on a clear go: send, post, publish, go, do it.
3. **Never rename a task.** Task titles belong to the people who run the
   board. `update_task.py` blocks `--name` unless you pass `--allow-rename`;
   use it only when the user asks for that rename.
4. **Never pin a comment unless the user asks.** `post_comment.py` does not
   pin by default.
5. **New tasks land in an intake section.** A new task in an active column
   tells everyone that someone is working on it. Pass `--section`, or set
   `default_sections` for the boards you use.
6. **Descriptions are append-only.** Asana keeps no description history: a
   PUT of `html_notes` cannot be undone. Use `append_description.py`. Progress
   notes belong in comments, not in the description.
7. **A person's time entries use that person's token.** Asana locks a time
   entry to its creator. `log_time.py` uses your personal token.
8. **Link every task you touched.** Format:
   `https://app.asana.com/0/0/<gid>/f`. List all the links at the end of your
   reply.

## Decide before you type

- **Draft or post?** If the user said "draft", stop and show the content.
- **Which task, exactly?** For a parent with subtasks, confirm whether the
  update belongs on the parent or on one subtask.
- **Create, or update an existing task?** Search first with `find_task.py`. If
  something close exists, update it.
- **Which project(s)?** Cross-post only when asked. Do not infer it.
- **Who is the assignee?** Every new task gets one. If the context names an
  owner, pass `--assignee`. If not, suggest one and ask in the same message as
  the draft. Pass a user gid you read from a source (your `user_gid`, or
  `_asana.resolve_user_gid(<email>, token)`), never one typed from memory.
- **Who is involved?** Add the people in the task's context as collaborators
  with `--follower` (repeatable). **Never add the subject of a private or
  sensitive task** (for example the person a performance note is about).

## The scripts

All scripts live in `scripts/` and share `_asana.py` for the token, HTTP and
URL helpers. They take a bare task gid or any Asana task URL (including a
`focus=true` permalink). Every write script has `--dry-run`, which prints the
payload and writes nothing.

### Post a comment: `post_comment.py`

```bash
python3 scripts/post_comment.py <task_url_or_gid> --text "Plain-text comment"

# Rich text: write the body to a file first
cat > /tmp/comment.html <<'HTML'
<strong>Blocked on:</strong> the staging dry run.
<ul><li>Staging secrets checked</li><li>Access grant pending</li></ul>
HTML
python3 scripts/post_comment.py <task> --html-file /tmp/comment.html --dry-run
python3 scripts/post_comment.py <task> --html-file /tmp/comment.html
```

It takes exactly one of `--text`, `--html-file` or `--html-stdin`.

**Rich text.** Asana accepts only some tags. `<p>`, `<br>`, `<th>`, `<img>`
and `<div>` are refused: on a comment, one of them makes Asana store the WHOLE
comment as escaped text; on a description, Asana answers `400 XML is invalid`.
The scripts refuse those tags before posting. Use real newlines for line
breaks. Full table and an example:
[`references/rich-text.md`](references/rich-text.md).

**The shape check.** `post_comment.py` and `edit_comment.py` refuse a comment
over 500 characters with no `<hr>` (or a plain `--text` over 500 characters).
They warn when the summary above the `<hr>` is over 400 characters, or when a
file is named with no link. `--skip-shape-check` overrides the refusal; use it
only when the user asks for that shape.

**Mentions.** `<a data-asana-gid="USER_GID"/>` is an @-mention and notifies
that person. A mention does not subscribe them, so the scripts add every
mentioned user as a follower after the post and read the followers back. A
miss prints `PARTIAL ... Do not post the comment again` and never fails the
run. `--no-follow` skips this; use it only for the subject of a private task.

### Write style inside a comment

- Lead with a plain-English summary. Put technical details (commits, logs,
  payloads) below an `<hr>`, so a person skimming the task sees the point first.
- One idea per sentence. Use the active voice.
- **Name every file, doc or task as an inline link:** `<a href="...">name</a>`.
- Cut AI phrasing: openers ("Great question"), hedges ("It seems like"),
  sign-offs ("Hope this helps"), filler adjectives ("robust", "seamless").

```html
We reproduced the sync lag: it is the 30-minute scheduler drift, not an API issue. We pause the fix for the scheduler rewrite that is already in progress.
<hr>
<strong>Evidence</strong>
<ul><li>Scheduler last run: 11:47 UTC, expected 11:30</li><li>Commit <code>abc1234</code> hid the drift</li></ul>
```

### Author line

Asana shows the token's owner as the author. With your own token, an agent's
comment reads as if you typed it. So every comment and description the scripts
write with a person's token starts with an italic line:
`Written by Claude for <first name>.` (`author_label` replaces "Claude").

- **The scripts add it.** Do not type it into a body. A body that already
  starts with "written by Claude" (or your `author_label`) is left as it is.
- **How it decides:** one `GET /users/me` per token, whatever the config
  holds. A user in `agent_user_gids` gets no line. Every other login gets the
  line with its own first name. If the lookup fails, the scripts print a
  `WARNING` on stderr and add the line. So a shared automation account must be
  listed in `agent_user_gids`, or its posts carry the line too.
- **`NOTE: this token posts as ...`** on stderr means the token belongs to a
  login other than `user_gid`. The line still names that login. If it is an
  automation account, add its gid to `agent_user_gids`.
- **No text, no line.** Field changes and time entries carry no text. The
  scripts refuse an empty body, so the line never posts alone.
- **Drafts:** show the line at the top of the draft. The `post_comment.py`,
  `edit_comment.py` and `append_description.py` dry runs show it.

### Fix a comment in place: `edit_comment.py`

When a comment is wrong, edit it. Do not delete it and post again: a repost
loses its place in the thread and notifies everyone twice.

```bash
python3 scripts/edit_comment.py <story_gid> --html-file /tmp/fixed.html --dry-run
python3 scripts/edit_comment.py <story_gid> --html-file /tmp/fixed.html
```

- The story gid is in the `Posted story <gid>` line that `post_comment.py`
  prints.
- It refuses unless the story is a comment written by the token's own user
  (Asana lets only the author edit a comment).
- The new body REPLACES the old one, and Asana keeps no old version. The dry
  run prints the old text: keep it if the record matters.

### Attach files: `attach_file.py`

Attaches files and posts the comment that goes with them, in one step.

| `--comment` | files | the comment | use it for |
|---|---|---|---|
| `link` | exactly one | your body, then a link to the file | evidence: a screenshot that goes with what the comment says |
| `name` | one or more | your body, the `--mention` tags, then each file's name; nothing linked | handing documents to the people tagged |
| `none` | one or more | no comment | the mention is somewhere else |

```bash
python3 scripts/attach_file.py <task> --file /tmp/handover.md --file /tmp/results.txt \
  --comment name --body-file /tmp/body.html --mention <user_gid> --dry-run
```

- `--name` sends a file under another name: one `--name` per `--file`, in order.
- **When it stops** after sending has started, it prints a `STOPPED` block:
  what landed, what did not, and a `Resume with:` command. `--resume
  <attachment gid>` checks a file that already landed and does not upload it
  again.
- **A lost response is checked, not assumed:** the task is read again, and
  only a clear match counts as done. Anything else is `Uncertain` or `UNKNOWN`:
  look at the task before you resume.
- **Never rename a file to get past the duplicate check.** A name already on
  the task stops the run (exit 3).
- Refused before anything is sent: names that look like credentials (`.env`,
  `*.pem`, `*key*.json`, "secret", "token", "credential"), files over 100 MB,
  and body tags Asana rejects. Exit codes: 0 done, 2 verify failed, 3 name
  already on the task, 4 bad input or API error.

### Create a task: `create_task.py`

```bash
# In a project (the duplicate check runs first)
python3 scripts/create_task.py --project <project_gid> --section <section_gid> \
  --name "Audit Checkout Triggers" --assignee <user_gid> \
  --notes "Plain-text description, or use --html-notes-file"

# A subtask, with the people involved as collaborators
python3 scripts/create_task.py --parent <parent_gid> --name "Subtask Name" \
  --assignee <user_gid> --follower you@example.com --follower peer@example.com

# Cross-posted into an extra project at creation time
python3 scripts/create_task.py --project <project_gid> --name "..." --multi-home <other_project_gid>
```

- **Duplicates:** it refuses when a task with the same name (open or done)
  is already in the project or under the parent. `--allow-duplicates` is for
  the rare case that really needs two.
- **A lost create is resumed, not repeated:** if the create fails with no
  clear answer, it looks for a NEW task with that name and adopts it. It never
  adopts a task that existed before the run.
- **Placement is checked:** it reads the task back, repairs a missing
  project or section once, and prints `PARTIAL` (exit 1) if it still did not
  land.
- `--insert-after <sibling_gid>` puts a new subtask after that sibling.
- `--start-on YYYY-MM-DD` (with `--due`) sets a start date.
- It sets no custom fields. Follow it with
  `update_task.py <new gid> --custom-field <field_gid>=<value>`.
- **Naming:** a short Title Case noun phrase that names the thing, 3 to 8
  words. Scope detail goes in the description.

### Update fields: `update_task.py`

```bash
python3 scripts/update_task.py <task> --assignee <user_gid>
python3 scripts/update_task.py <task> --unassign
python3 scripts/update_task.py <task> --due 2026-05-01
python3 scripts/update_task.py <task> --complete
python3 scripts/update_task.py <task> --custom-field <field_gid>=<option_gid>   # enum
python3 scripts/update_task.py <task> --custom-field <field_gid>=2026-04-22     # date
python3 scripts/update_task.py <task> --multi-field <field_gid>=<option_gid>,<option_gid>
python3 scripts/update_task.py <task> --status-option <option_gid>  # a custom task type's status
python3 scripts/update_task.py <task> --add-project <project_gid>=<section_gid>
```

Enum fields take the option gid, not the display name. Date fields take
`YYYY-MM-DD`. A multi-enum field needs `--multi-field`, and the list REPLACES
the field's values, so pass the full new set. `--add-project` keeps the task in
its other projects and leaves a project it is already in alone.

### Complete a task when the work is done

When the session finishes what a task asks for, offer to mark it complete.

- Put one line in the same draft as your closing comment:
  `Mark complete: [Task name](https://app.asana.com/0/0/<gid>/f)`. On the go,
  post the comment, then run `update_task.py <task> --complete`.
- Do not offer when the task waits on someone else, or is a parent with open
  subtasks.
- Never complete a task to hide it.

### Append to a description: `append_description.py`

```bash
python3 scripts/append_description.py <task> --html-file /tmp/new-section.html
```

It reads the current description, joins the new block after an `<hr>`, and
writes the result. Before you run it again, check that the block is not
already there.

### Search: `find_task.py`

```bash
python3 scripts/find_task.py --query "quarterly report"
python3 scripts/find_task.py --query "welcome email" --project <project_gid>
```

**A miss is not proof the task does not exist.** Asana search returns at most
100 hits, newest first, with no paging, so an old task can drop off. The script
lists exact name matches first and warns at the cap. `--project` never matches
a task that is in no project. If you know the gid, read it with
`read_task.py`. Asana's search endpoint needs a paid workspace.

### Log time: `log_time.py`

```bash
python3 scripts/log_time.py <task> --minutes 30
python3 scripts/log_time.py <task> --minutes 45 --date 2026-04-20
```

For the user's own time only. It uses `personal_token_secret` or
`ASANA_PERSONAL_TOKEN` when set, else the normal token. An entry made with a
shared account shows the wrong name, and the user cannot edit it later.

### Read a task: `read_task.py`

```bash
python3 scripts/read_task.py <task>               # parents, fields, notes, every story, subtasks
python3 scripts/read_task.py <task> --depth 2     # subtasks two levels down, in full
python3 scripts/read_task.py <task> --comments-only
python3 scripts/read_task.py <task> --json
```

It sends GET requests only. A parent the token cannot read shows as
`cannot read`, and the task still prints.

## Another workspace

A write to a workspace the default token cannot reach fails with HTTP 403. Do
not write an ad-hoc script. Pass the token options to the same scripts:

```bash
python3 scripts/post_comment.py <task> --html-file /tmp/comment.html --dry-run \
  --token-secret <secret> --token-project <gcp project>
```

- Every script takes `--token-secret` and `--token-project`.
  `find_task.py` and `create_task.py` also take `--workspace <gid>`.
- With a token option and no `--workspace`, `create_task.py` leaves the
  workspace out of the request (`--project` or `--parent` sets it).
- `--workspace` alone does not change the token. Pair it with `--token-secret`.
- Every check stays: the body checks, the shape check, the author line, the
  follower step and the read-back.
- If the secret cannot be read, the script stops before the write. A retry
  after that failure cannot post twice.

## Status updates vs comments

- **A comment on a task** (`POST /tasks/{gid}/stories`) is what people usually
  mean by "an update". Use `post_comment.py`.
- **A project status update** (`POST /projects/{gid}/project_statuses`) is a
  separate Asana feature. Use it only when the user says *project* status.
  There is no script for it: confirm the intent first.
- **"Post status to the tasks"** means a comment on each task.

## After writing

- One line per task touched: `[Task name](https://app.asana.com/0/0/<gid>/f)`.
  `post_comment.py` prints this line for you.
- Nine comments means nine task links in the reply.
- If something partly succeeded, say exactly what landed and what did not.

## When things go wrong

- **A write seems to fail.** Before you retry, check whether it landed:
  `find_task.py`, or `read_task.py` for comments. A client can misread a reply
  that Asana accepted, and a blind retry makes a duplicate.
- **You find a duplicate you created.** Do not delete it, and do not complete
  and rename it. Give the user both links, marked "these two need merging".
  Asana has no merge API.
- **A comment you posted is wrong.** Fix it with `edit_comment.py`. Do not
  delete and repost.
- **You posted to the wrong task.** Say so, and post to the right task.
  Deleting the stray comment needs the user's go.
- **A field you set at create time reverts.** Board rules run a few seconds
  after a task lands in a project, and can overwrite a field you just wrote.
  On a board with rules, read the fields again about a minute later, and set
  the field again if a rule changed it.
- **A one-off write through `_asana.request` returns 400 "did not wrap object
  properties in a data object".** Pass `data={"data": {...}}`.
- **You need to clear an enum custom field.** The scripts cannot set an enum
  field to empty. Say so in your report, name the field and the task, and ask
  the user to clear it in Asana. Do not clear it with a hand-written call.

## Tests

```bash
python3 -m pytest scripts/tests
```

The tests need `pytest` and make no network calls.
