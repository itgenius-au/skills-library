---
name: morning-brief
description: Use when the user runs /morning-brief or asks for their morning brief, daily briefing, "what's on today", "brief me", "catch me up on my day", or a rundown of calendar + tasks + email + chats. Pulls today's Google Calendar schedule first, then Asana, unread Gmail, and Google Chat; triages signal from noise, renders an ADHD-friendly mission-control HUD artifact with a palette that reseeds every day, and posts a text digest (schedule + email together) to the user's Google Chat space. Keywords - morning brief, daily briefing, brief me, my day, what's on today, standup, catch me up.
---

# Morning Brief

Produce the user's **Morning Brief** across **today's Google Calendar schedule, Asana tasks, unread Gmail (last day), and Google Chat**, then render it as a vibrant, **ADHD-optimised mission-control HUD** published as a private Artifact. Everything here is **read-only** on your data sources (with two narrow, approval-gated write exceptions - see Notes).

Design intent (do not water down): **one glowing focal point** (NEXT UP), a **checkable FOCUS 3**, **color-coded urgency with consistent meaning** (red = urgent/overdue, amber = soon, green = done/clear), collapsible noise, and a **palette that changes every day** so it never feels stale. The look must feel exciting, not like a report.

## Setup - fill these in before first run

This skill is portable. Replace the placeholders below with your own values (store them here, or in your project memory):

| Placeholder | What it is | Example |
|---|---|---|
| `YOUR_TIMEZONE` | Your IANA timezone + short label for display | `Australia/Sydney` (AEST) |
| `YOUR_CHAT_SPACE` | Google Chat space id the digest posts to | `spaces/XXXXXXXXXXX` |
| `YOUR_WEBHOOK_SECRET` | Secret **name** in your secret manager holding the Chat incoming-webhook URL | `morning-brief-chat-webhook` |
| `YOUR_SECRET_PROJECT` | Your cloud project / vault that holds the secret | `your-gcp-project` |
| **Leadership roster** | Names + emails/domains of your leaders/exec team (used by triage) | _empty - infer from role until filled_ |

The Chat post is **opt-in**: it only works once you've created an incoming webhook for your space and stored its URL as a secret. If you don't want the Chat post, run in show-me mode (Step 4) and the skill just renders the HUD.

## Step 1 - Gather (run in parallel)

First load the connector tools with `ToolSearch` (server IDs vary per machine/account, so search by keyword rather than hardcoding):
- `gmail search_threads` · `calendar list_events` · `asana search_tasks` + `asana get_my_tasks`

Determine **today's date** and the user's **timezone**. The calendar's primary timezone is returned as `timeZone` on the `list_events` response - use it (or `YOUR_TIMEZONE`). Present **all times in that zone** and label it. If the user's team runs across timezones (e.g. meetings landing overnight/early-morning their time), call that out in the subline.

Then pull, concurrently (the calls run in parallel, but **Calendar leads** - it anchors the brief and is gathered *before* Gmail so the schedule frames everything else):
1. **Calendar (first)** - `list_events` for today only (`startTime`=today 00:00, `endTime`=tomorrow 00:00, `orderBy=startTime`). Capture each event's time, title, and `htmlLink`; this is the top of the brief.
2. **Gmail** - `search_threads` with `query: "is:unread newer_than:1d in:inbox"`, `pageSize:50`. Note the `resultCountEstimate` for the total.
3. **Asana due today** - `search_tasks` `assignee_any=me, completed=false, due_on=<today>`.
4. **Asana this week** - `search_tasks` … `due_on_after=<today>, due_on_before=<today+8d>`, sort `due_date` asc (shows if anything else is scheduled).
5. **Asana fresh overdue** - `search_tasks` … `due_on_before=<today>, due_on_after=<today-75d>`, sort `due_date` **desc**, limit 30 (surfaces recently-lapsed real work, not ancient backlog).
6. **Backlog size** - from `get_my_tasks` (`completed_since=now`), note the rough count for the overdue stat.
7. **Google Chat** - check for a Chat connector. If none exists, render the "not connected" tile (don't fake it). If one is connected, pull recent/unread spaces & DMs and add a signal list.

## Step 2 - Triage (this is the value)

**Signal vs noise.** Most unread is noise. Bucket into a collapsed "noise" summary:
- Out-of-office auto-replies, ticket-system / vendor auto-acknowledgements, and routine platform notifications (e.g. Cloudflare, UptimeRobot, YouTube, ad platforms, calendar/meeting auto-notes, Asana digest emails).
- Note when a bounce-storm traces to one of the user's own sends (e.g. a marketing broadcast) - say broadcast/send.

**Surface as signal** (≤10): real humans, security alerts, billing/budget thresholds, [ACTION REQUIRED] items, financial movements, support escalations, anything tying to today's meetings.

**Email triage - don't list unread flat; rank it.** Within the signal, actively pull out and badge two priority classes, and sort them to the top of the inbox list:
- **👤 Leadership** - mail from the user's leadership/exec team. Match on sender: names in the leadership roster (Setup), plus anyone whose role/signature marks them as a founder, C-level, GM, director, or board/investor. When unsure whether a sender is leadership, badge it and say why ("GM?") rather than dropping it. Leadership mail is signal even if it looks routine.
- **⏰ Same-day reply** - mail that needs a response *today*. Infer from the ask, not just keywords: explicit deadlines ("by EOD/COB", "today", "end of day", "before the call"), time-boxed requests, a direct question awaiting the user's answer, anything tied to a meeting on today's calendar, or a hard external cutoff (payment due today, suspension/expiry today). A genuine [ACTION REQUIRED] with a today deadline earns both badges.
- Present each flagged item with its badge(s), one-line why, and a deep link. An item can carry both badges - surface those first. Everything else stays in the ranked signal list; true noise stays collapsed.

**Asana:** most of the backlog is auto-generated nudges ("Final Content Approval", "Consider updating your project progress", "It's time to update your goal(s)", "Today", "Script Approval"). Down-rank these. Surface real decisions/approvals/payables/escalations.

**FOCUS 3** - pick the three highest-leverage things for today by combining all sources. Bias toward: overdue *decisions* that unblock others, items *due today*, money/approvals, and anything a teammate is waiting on. Each gets a severity (crit/warn) and a direct Asana/email link.

**Meeting conflicts:** flag overlapping calendar slots explicitly (mark both with a "clash" badge).

## Step 3 - Render the HUD artifact

Start from `template.html` in this skill folder (a known-good build). Copy it, then **replace only the data** - keep the CSS + JS engine (theme rotation, live clock, canvas, focus-mode, timeline/next-up/focus3 logic) intact.

Update these regions:
- `<title>` and the footer snapshot date.
- **`BRIEF_DATE`** in the script → `new Date(YEAR, MONTH0, DAY)` (month is 0-indexed). This seeds the daily palette - do not hardcode a theme; let `dayOfYear % THEMES.length` pick it so **every day differs**.
- **Timezone**: the topbar `chip.tz` label and the `Intl.DateTimeFormat` `timeZone` in the clock (and the `+HH:00` offsets in the events array) - set to the user's zone.
- **`EV` array** - today's events: `{t:"HH:MM", s/e: ISO with offset, title, tags:["clash"|"ext"|"host"], note}`. `note` may contain a Meet/Zoom `<a>` link.
- **`#focus3`** - the three FOCUS items (`data-sev`, title, `sevtag`, links).
- **stat strip** - meetings / due-today / overdue / inbox-signal numbers + sublabels.
- **Asana rail** - due-today `.due` links, "clear the decks" `.mini` overdue list, backlog callout count.
- **Inbox rail** - signal `.mini` list (pip colors: crit/warn/info/good), **leadership (👤) and same-day-reply (⏰) items badged and sorted to the top** per Step 2, + the collapsed noise summary text.
- **Google Chat tile** - connected list or the "not connected" state.

Then publish with the **Artifact** tool (private by default - this is the user's own data, safe to publish for themselves):
- `favicon: "🛰️"` (keep stable across days - same page identity).
- `title: "Morning Brief - <Day DD Mon YYYY>"`, a one-line `description`.
- **Same artifact, updated in place:** the first run creates the artifact; to keep one stable URL, save its URL and pass it as `url` on later runs. If the user prefers a fresh card each day, publish without `url`. Default: update in place (a fresh artifact per day is also fine - ask if unsure).

Keep the palette committed-dark (single-theme by design - it's a mission-control screen); every color is already painted from a token so it holds on any host ground.

## Step 4 - Post the Morning Brief to Google Chat

The brief is also posted to the user's Google Chat space (`YOUR_CHAT_SPACE`) via an incoming webhook. Treat this as a **standing part of the skill - post it each run by default** once configured; skip only if the user says "don't post" / "just show me".

**This chat message is the full Morning Brief, not just email** - it must **lead with today's calendar schedule, then email**, so the user gets both together in one post.

**Always post - even on a zero day.** A quiet day is not a reason to go silent: **every run posts something.** When the calendar is empty, the inbox is all-noise, and nothing is due, still send a short **"all clear"** digest (e.g. `✅ *Morning Brief - <date>*\n• Clear calendar\n• Inbox: 0 need action (N noise)\n• Nothing due today` + the HUD link). The point is that silence must never be ambiguous - an all-clear post says the brief *ran and there's genuinely nothing*, versus no post meaning it didn't run. Only skip the post if the user explicitly says "don't post" / "just show me", or a real error blocks it (then say so). Never suppress the post just because a section is empty.

**The webhook is a secret - never hardcode it or write it to any file.** Read it at run time from your secret manager, e.g. with Google Secret Manager:
```bash
WEBHOOK=$(gcloud secrets versions access latest --secret=YOUR_WEBHOOK_SECRET --project=YOUR_SECRET_PROJECT)
```

Build a concise **text digest** and POST it (write the JSON to a file - `{"text":"…"}` - rather than inlining, to avoid shell-escaping):
```bash
curl -sS -X POST -H "Content-Type: application/json; charset=UTF-8" -d @payload.json "$WEBHOOK"
# expect HTTP 200 + the created message name
```

**Always include clickable hyperlinks** so the user can jump straight to each item. Google Chat text markup for links is `<URL|label>` (angle brackets, pipe). Build them from the data already pulled:
- **Asana task** → the task's `permalink_url`, e.g. `<https://app.asana.com/…/task/123|Payment Approval>`.
- **Calendar event** → the event's `htmlLink` from `list_events`, e.g. `<https://www.google.com/calendar/event?eid=…|Team Retro>`.
- **Email** → deep-link the thread: `https://mail.google.com/mail/u/0/#all/<threadId>` (thread `id` from `search_threads`), e.g. `<https://mail.google.com/mail/u/0/#all/19ffd…|Vendor - recording>`.

**Digest content, in this order** (schedule leads, email follows - both in every post):

1. **`*🗓️ Today's schedule*`** - each of today's calendar events as its own bullet: `• *HH:MM* <htmlLink|Title>` in the user's timezone, in start-time order. Mark clashes with a `⚠️ clash` tag on both overlapping events, and external/host meetings if useful. If there are no events, say `• Clear calendar - no meetings today`.
2. **`*📥 Inbox*`** - signal vs noise counts. **Lead with the flagged items from Step 2** - 👤 leadership and ⏰ same-day-reply - each linked (`<https://mail.google.com/mail/u/0/#all/<threadId>|subject>`) with a 3–5 word why; then any other 2–3 that need action; fold the rest into a one-line noise summary. If nothing is flagged, say so (`• No leadership / same-day items`).
3. **`*🎯 Focus & tasks*`** - top priority (FOCUS #1, linked), the due-today Asana tasks (linked), and the overdue count.
4. The private **HUD artifact** link.

Other Google Chat markup: `*bold*`, `_italic_`, `\n` for newlines, `•` for bullets. Keep it room-appropriate (soften personal/health details - others may be in the space). The graphic (Artifact) stays a **private** link - the space gets the linked text digest, not the HUD itself; note the user must share the artifact from its page for others to open it.

**If the POST fails, retry once, then never go silent.** On a non-200 (or a webhook/network error), wait ~2s and retry the POST once. If it still fails, surface an **explicit error to the user** - what failed and the exact error/HTTP code - and still hand off the rest of the brief; don't drop it quietly. If the failure is the *secret fetch* (e.g. auth expired), don't burn the retry on an identical auth failure: say plainly that the digest couldn't post, give the fix (re-auth), and confirm the payload is ready to resend. When Chat itself is the thing that's down, the explicit error goes to the user directly (the webhook is the only channel to that space).

## Step 5 - Draft replies for urgent items (approval-gated, NEVER send)

For anything **urgent that a reply email actually answers**, compose a proposed reply and **leave it for the user to approve - never send**. Scope it to the flagged emails from Step 2: **⏰ same-day-reply** and **👤 leadership** items where a real person is waiting on the user's response. Skip items where email isn't the action (a payment/suspension needs paying, an `[ACTION REQUIRED]` config needs fixing) - for those, name the action in the hand-off instead of drafting a reply.

**Default = present the draft in chat** (safest reading of "draft"). For each: the recipient, a one-line subject/context, and the proposed reply body, so the user can eyeball and edit. Match the user's plain-text, on-brand voice (point this at your house style/copy guide if you have one); keep replies short.

**Optional - save into Gmail Drafts (still unsent):** only if the user says so, and only with the Gmail **`create_draft`** tool (an unsent draft in their mailbox). **Never** call `reply`, `send_message`, or `forward` from this skill - those transmit. Even saving a draft is per-run: ask first unless the user has already said "save them as drafts" this session. Report each draft you create with its draft link; create nothing on a source error.

**Hard rule:** this step produces *unsent* drafts only. Sending is always the user's action. No auto-send, no "I'll just fire off the quick ones."

## Step 6 - Hand off

Give the user the artifact link, confirm the Chat post went out (HTTP 200), a 1–2 line text summary of the single most important thing (usually FOCUS #1), and **surface any drafted replies from Step 5 for approval**. Then offer concrete next actions: send/edit the approved drafts, draft meeting declines for conflicts, triage/clear the email noise, or break down the Asana backlog. Do not perform any write action beyond the authorized Chat post (and, if approved, unsent Gmail drafts) without explicit approval.

## Step 7 - Good-result check (definition of done)

Before declaring the run finished, verify the outcome against this bar. **A good result is exactly ONE Chat post that covers both Calendar and Gmail - or, when both are genuinely empty, one explicit "nothing to report" post.** Concretely:

1. **Exactly one post** - the run posts once. Not zero (going silent is a fail), not two (no partial-then-correction; build the full digest, then post once).
2. **Both dimensions present** - that single post contains a **🗓️ Calendar/schedule** line *and* a **📥 Gmail/inbox** line. "Covered" means each dimension is represented one of three ways: real content, an explicit *clear* state (`Clear calendar` / `0 need action`), or an explicit *couldn't-reach* state (`Calendar offline`, `Gmail search failed`). A dimension that's simply missing from the post = **fail**.
3. **Nothing-to-report is still a post** - if Calendar and Gmail both come back empty (zero meetings, zero signal), send the short **"nothing to report"** all-clear (per Step 4) - that counts as a good result. Silence never does.
4. **Verify, don't assume** - confirm the POST returned **HTTP 200** and that the payload you sent actually included both lines. If the post failed (after the one retry), or a dimension was dropped, the run **did not pass** - say so explicitly rather than reporting success.

State the check result in the hand-off: ✅ one post, Calendar + Gmail both covered - or ❌ with exactly what's missing and why.

## Notes
- **Read-only on every source, with two narrow exceptions.** No Asana writes via MCP (if your org ever needs Asana writes, route them through your own service account/token per your org's rules). No calendar edits. **Never send, reply, or forward mail** - Step 5 may only *draft* (present in chat, or an unsent `create_draft` if the user approves). **The one standing outbound action is the Google Chat digest post** (Step 4) - a webhook to the user's own space; do not post anywhere else. Unsent Gmail drafts (Step 5) are the only other write, and only on the user's approval.
- The Chat webhook lives only in your secret manager (secret **name** `YOUR_WEBHOOK_SECRET`); the repo holds the name, never the URL value. Never print it, echo it, or copy it into a file.
- Reading Google Chat needs a read connector; the webhook only *posts*. If no read connector is installed, say so plainly - don't invent messages.
- **On any failure, retry once, then report explicitly - never go silent.** This applies to every moving part: Calendar `list_events`, Gmail `search_threads`, Asana queries, and the Chat webhook post. First retry the failing call once (after a short pause). If it still fails, render/hand off everything that *did* work and show an explicit "couldn't reach X - <error>" note for the part that failed (in the HUD tile for that source, and to the user in the hand-off). Never fail the whole brief because one source broke, and never omit a broken source without saying so - a silent gap is the one outcome to avoid. A missing connector (e.g. Calendar not authorized this session) is a "couldn't reach" state too: show it, don't hide it.
