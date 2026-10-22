---
name: exec-summary
description: "Turn complex content into a short plain-language executive summary in Simplified Technical English: 3-5 key points, numbered decisions each with a recommendation, next steps, then the bottom line and a 'go' reply line. Use it WHENEVER the user asks for a summary or recap, asks where the current work stands, asks for a simpler or shorter version, or says they are confused, even mid-task after a long plan, audit, or table of numbers. Not for session wraps or hand-offs (session-wrap), status across many sessions (session-status-sweep), marketing copy (copy-humanizer), or shortening code. Triggers on: executive summary, exec summary, exact summary, summarize, summarise, summary please, recap, catch me up, where are we, where are we now, where are we at, where are we on this, what are we doing, what's left, where did we leave off, status update, what's happening here, simpler, too technical, too long, I don't understand, I'm confused, plain english, bottom line, tl;dr, in bullets, what does this mean."
argument-hint: "[blank = the current conversation, or a file / link / pasted text]"
---

# Executive Summary

Give the reader the answer and the decision in 30 seconds, in plain words.

**Core principle:** compress, never invent. A summary says less than the source. It never says something the source does not. The one exception is a recommendation: it is a judgment, labeled **Recommend:**, never a new fact.

## When it fires

The typical moment: Claude just produced a long technical turn (a diagnosis, a plan, a spec, an audit, a table of numbers). The user must now approve, pick an option, or sign off. They ask for "an executive summary", "simpler", or say "I don't understand".

A status check also fires it: "where are we?", "what are we doing?", "what's left?". Then the source is the current state of the task: what is done, what is in progress, and what waits on the reader.

## Step 1: Pick the source

- **Argument given** (file, link, pasted text): summarize that.
- **No argument**: summarize the most recent substantial content in the conversation, plus the current state of the task.
- Do not ask which source to use. Pick the most likely one. The user redirects you if it is wrong.

## Step 2: Find the four things

Before you write, find these in the source:

1. **The bottom line.** The answer, the state, or the recommendation, in 1-3 short sentences.
2. **The facts that matter to the decision.** Numbers, dates, names, cost, risk.
3. **The decision the reader owns,** and the recommendation for each. A real choice (product, money, risk, trust). Not "may I proceed?".
4. **What happens next,** and who does it.

Then check four honesty points. These go first in Key points, in bold, if they apply:

- **Anything done without approval**, or anything irreversible (a deploy, a send, a delete, a charge). If something was done without approval, the decision section also asks: keep it or undo it?
- **Any risk, cost, or bad news.** State it plainly. Do not soften it.
- **Anything not verified.** Say "not yet verified". Do not present a guess as a fact.
- **Corrections.** An earlier message to the reader may have stated something that is now known to be wrong. Say so first in Key points, before the other honesty points: "**Correction:** I said X. The right answer is Y." If the reader's decision rested on the wrong claim (for example a "go"), also say whether the decision still stands. Do not fix it silently or only in passing.

Keep **done** and **proposed** apart. Use the past tense for what already happened ("We refunded 3"). Use "will" or "plan to" for what is only proposed.

## Step 3: Write it

Use this shape by default:

```markdown
**Key points**
- <3-5 bullets, one fact each, most important first>

**Decision needed**
1. <a plain question the reader can answer yes/no or A/B> **Recommend:** <the option, and why in a few words>

**Next steps**
- <what happens next, and who does it>

**Bottom line:** <1-3 short sentences, 30 words at most: the answer, state, or recommendation>

Reply "go" to accept every recommendation, or answer by number.
```

- **The bottom line goes last,** just above the reply line, every time. The reader sees it as they answer and does not scroll back up.
- **Number every decision** (1, 2, 3), even when there is only one. Label named options A and B. The reader can then reply by number, for example "1: yes, 2: B".
- **Give a recommendation for every decision,** so the reader can accept them all at once. Use the source's recommendation where it has one. If the source gives none, recommend from the facts in the summary. If there is no basis for one, write "**No recommendation:** <why>" instead of inventing one, and name that item in the reply line (for example: Reply "go" to accept the recommendations, then answer 3).
- **"go" is the approve-all reply.** It accepts every recommendation in that summary, and nothing outside it. "yes to all" means the same. "go" with named items (for example "go, 2: B") accepts every recommendation except the items named, which take the answer given. An item marked **No recommendation** still needs its own answer.
- Most summaries have one decision. Never list more than three. If there is no decision, write `**Decision needed:** none.` The reader then knows you checked.
- Aim for **100-200 words**. Go up to 300 only for a large plan or spec. Never make it longer than the source.
- Write it in chat. Do not write a file unless the user asks.
- If a full document exists, link it once at the end, as a reference. The reader must be able to decide without opening it.

### Writing rules (Simplified Technical English + Zinsser)

These rules apply whatever output style the session uses.

- **End with the bottom line,** just above the reply line. Start with the key points. No opener ("Great question", "Here is the plain-English version").
- **One idea per sentence.** Keep sentences to 20 words or fewer.
- **Active voice, present tense.** "The job sends the charge twice", not "The charge was being sent twice".
- **One term per concept.** Do not swap in synonyms.
- **Translate jargon.** Keep a technical term only if the reader needs it to act (for example, the name of the thing they approve). Define it in plain words the first time. Once you translate a term, use only the plain word after that. Use one plain analogy for the hardest concept, if it helps.
- **Spell out an abbreviation on first use,** even a well-known one: "Business Associate Agreement (BAA)", not a bare "BAA". The short form is fine after that.
- **Cite the source in a few words, not a link:** "per the signed scope doc", "checked live today". A bare claim then does not read as a guess. Save the link for the one reference line at the end.
- **Group a long list under bold headers.** When a section runs past 5 bullets, split it into groups. A header can be a full descriptive phrase ("**The vendor's HIPAA coverage for this product**"); trim the bullets, not the headers.
- **Bold the load-bearing words:** numbers, dates, names, and the decision.
- **Round numbers** to what the decision needs: "12.4k", not "12,387.52", unless the exact figure matters.
- **Tables only to compare options or items side by side.** One value per cell. Three or four columns at most.
- **No hedging, no filler.** Cut "it's worth noting", "basically", "I think".
- **Stay human.** Write like a colleague who respects the reader's time, not a manual.

## Step 4: Check it against the source

Simplifying is where errors get in. Before you send, re-read the source and check:

- **Every number** matches the source (rounding is fine, a changed figure is not).
- **Every "because" and "mainly".** The cause you give must be the main cause in the source. If the source splits a change into parts (for example more hours versus a higher rate), name the biggest part first.
- **Nothing important is dropped** to make it shorter: a risk, a deadline, or an action already taken.
- **The analogy does not change the facts.** If it implies something the source does not say, cut it.

## When the user says "still too technical" or "simpler"

Shorter is not enough. Cut **concepts**, not only words:

- Drop to 3 key points.
- Replace each technical term with what it does for the reader.
- Add one analogy for the hardest idea.
- Split any table cell that holds more than one number.
- Check if "simpler" hides a real objection. The reader may mean "you buried something I did not approve". If so, name that issue first, plainly.

If the user corrects you, one short line of acknowledgement is fine ("Fair, too complex."). This line is not an opener. Then give the new version. Do not apologise at length.

**Jargon example:**

- Before: "The idempotency key was not set on the PaymentIntent retry path."
- After: "The system had no check to stop the same charge going out twice."

## When another skill calls this one

The calling skill owns **when** to summarize and **which sections** matter. This skill owns **how it reads**.

- If the caller names its own sections, use them in that order instead of Key points / Decision needed / Next steps. Keep the bottom line last. (Example: "What gets built / Why / Decisions they still own".)
- **The bottom line stays last in the whole message,** whatever the caller adds. If the caller shows more after the summary (a plan, a draft, a table), put the bottom line after that content, just above the closing reply line (the "go" line or the caller's own closing line). A caller's one-line notice or stop line that must come first stays first.
- The caller's sections win over this skill's defaults. The word range, the 3-5 key points, and "link once" apply only to the default shape.
- Never drop content a caller section requires in full: every name, every link, the evidence. Compress the prose around each item, not the list.
- If the caller sets a bullet or word limit, obey it.
- Number the decisions, each with a recommendation, in any section that asks the reader to decide, including a caller's own (for example "Decisions they still own").
- The caller keeps its own gates. If the caller says "wait for approval", wait. If it says "hand straight off", do not add an approval question. Leave out the "go" reply line when the caller says "hand straight off" or supplies its own closing line (for example "Approve, or tell me what to change."). Still state any honesty point from Step 2 as a fact.

## Example

Context: Claude just gave a 900-word diagnosis of a billing fault. The user says "I don't understand, give me an executive summary."

```markdown
**Key points**
- A retry job ran twice after a timeout, so the same charge went out again.
- **7 customers**, **USD 1,260** in total. No other month is affected.
- The fix (a check that blocks duplicate charges) went live on **14 Mar**. No repeats since.
- **Nothing is refunded yet.**

**Decision needed**
1. Refund all 7 now (A), or wait for each customer to contact us (B)? **Recommend A:** the fault is ours, and refunds close it today.
2. Send each affected customer a short apology email? **Recommend yes:** they will see two charges on their statement.

**Next steps**
- On your answers: refunds and emails go out today.

**Bottom line:** 7 customers were charged twice on 12 Mar. The cause is fixed. Refunds need your approval.

Reply "go" to accept every recommendation, or answer by number.
```

## What this skill does not do

- **Session wraps and hand-off prompts:** use `session-wrap`.
- **Posting the summary somewhere** (your task tracker, team chat, email): write it here, then post it with the tool for that system. Posting externally still needs the owner's approval.
- **Marketing or customer-facing copy:** use `copy-humanizer`. Simplified Technical English flattens emotive copy.
