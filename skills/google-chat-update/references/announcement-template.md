# Announcing a skill, plugin or process change in Google Chat

Use this when a skill, plugin or process change has landed and its users should hear about it. Post only on the requester's go, and
show the exact text first.

## Where and as whom

- **Space:** the space whose people use the change (a team's own skill goes to that team's space; a
  company-wide change goes to the company-wide space the requester names).
- **Identity:** `--identity self` when the requester asked for the post and has admin DWD (it shows as them);
  otherwise the bot. See "Two write identities" in SKILL.md.
- **Mentions:** no `@all` unless the requester asks. The thread title is enough, and it saves a ping to everyone.

## Shape: an opener, then the body as the first reply

Post a short opener as a new top-level message (it becomes the thread title), then post the body with
`reply` to that thread. A long first message makes a poor thread title in the space list. This shape is
the rule for every new thread the skill posts, not only announcements (SKILL.md Workflow step 5). If
`search` finds a live thread on this same change (SKILL.md Workflow step 2), reply there instead. A later
update to something announced before is a new change, so it gets a new thread.

```
python3 scripts/chat-post.py post  --identity self spaces/<SPACE_ID> "<Skill Name> skill <one emoji>"
python3 scripts/chat-post.py reply --identity self spaces/<SPACE_ID>/threads/<THREAD_ID> --text-file body.txt
```

Then list the space and check that both messages are in the thread.

## Body template

Keep each part to one or two sentences. Write in the requester's voice, in plain words.

```
New in our team Claude skills: *<Skill Name>*, for <what it is for, in one line>.

To get it: run `claude plugin marketplace update <marketplace>`, then `claude plugin install <plugin>@<marketplace>`
(or `claude plugin update <plugin>` if you already have it), and start a new Claude session. Then ask, for
example, _"<example request 1>"_ or _"<example request 2>"_.

It <what it does, in steps the reader recognises>. <Its safety line: what it never does on its own, and
what needs approval.>

<Scope: what it covers. Any one-time setup the reader may need, with the exact command.>

First use: <the real case it was built from, without naming a customer>.
```

For an existing skill that changed, replace the first two parts with "Update to *<Skill Name>*: <what
changed>" and "To get it: run `claude plugin marketplace update <marketplace> && claude plugin update <plugin>`,
then start a new Claude session."

## Announcing a process, SOP or plugin change

The body template above is for a skill. For a process, SOP or plugin change, keep the shape (an opener, then the body as the first reply) and change the content.

- **The opener names the move.** When one system or process replaces another, name both ("Expense claims are moving from the old form to the new portal"). "SOP update: ..." does not tell a reader what changed.
- **The body says** what changed (before and now), what staff do now, and the link to the changed section.
- **A change about access levels lists what each level can do,** one short list per level, each line checked against the product's docs or code. Do not use customer stories as the examples.
- **Screenshots go after the body, as one reply per image,** each with a one-line caption. Readers then see them in the thread. This overrides the "zip many images" line in SKILL.md, for announcement screenshots only. Each reply uses the self-post attachment route in SKILL.md. Show the opener, the body and every image with its caption in one preview, and get one go for the set. Save each message's name to a file as it lands, and skip saved steps on a re-run. Before any re-run, list the thread: a reply that timed out can have landed without being saved. Show what remains and ask again. Take the screenshots from a test workspace, never a customer's.

## Formatting reminders

- Bold is `*single asterisks*`; italics are `_underscores_`; code is backticks. Convert a markdown draft
  before posting.
- Do not name a customer in a team-wide post. Describe the case ("after a customer reported a problem").
- Check dates in the text against today's date before posting ("today" can be wrong a day later).
