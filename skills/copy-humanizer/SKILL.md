---
name: copy-humanizer
description: "Remove AI-generated patterns and restore natural human voice to marketing copy, blog posts, and email content. Triggers on: humanize, copy humanizer, de-ai, remove ai patterns, make it human, sounds like ai, too robotic, ai voice."
argument-hint: "[file_path or paste text]"
---

# Copy Humanizer

Strip AI fingerprints from marketing copy, blog posts, and email content. Make it read like a real person on your team wrote it.

**Core principle:** Don't change the message. Strip the AI tells.

**Prevention beats cleanup:** when drafting from scratch, instruct the model to "Use ASD-STE100" (the Simplified Technical English aircraft-manual standard: short words, short sentences, active voice) plus Zinsser's four principles (simplicity, brevity, clarity, humanity). This removes most tells before they are written. Do NOT apply STE to creative or emotive copy - it flattens anything with a heart. Keep your own banned-tells list (a plain checklist file in your project); check drafts against it and add new tells as they appear.

## What Gets Removed

### 1. Overused Transitions

- "Moreover," "Furthermore," "Additionally," "Nevertheless" as sentence starters
- Excessive "However" usage
- "While X, Y" constructions (restructure as two sentences or use "but")

### 2. AI Cliches

- "In today's fast-paced world", "In the ever-evolving landscape of"
- "Let's dive deep", "Unlock your potential", "Harness the power of"
- "Game-changer", "Revolutionary", "Cutting-edge"
- "Seamless", "Robust", "Holistic"
- "Navigate the complexities of"

### 3. Hedging Language

- "It's important to note", "It's worth mentioning", "It's worth noting"
- "At the risk of being hyperbolic"
- Vague quantifiers: "various," "numerous," "myriad," "a plethora of"

### 4. Corporate Buzzwords

- "utilize" -> "use"
- "facilitate" -> "help"
- "optimize" -> "improve"
- "leverage" (non-financial) -> "use"
- "streamline" -> "simplify" or "speed up"
- "empower" -> "help" or "let"
- "elevate" -> "improve"

### 5. Structural AI Tells

- Em-dashes used as inline bullet structures: `term -- definition, term -- definition`
- **Bold text** for random emphasis mid-paragraph (not headers or callouts)
- Exactly three parallel examples or bullet points in a row (classic AI filler pattern)
- Rhetorical question immediately answered by the next sentence
- "Not only does it X, but it also Y" -> Just say both things directly
- "That's not X. That's Y." (two-sentence pivot) -> keep only the second half: "They're stalling."
- Stacked two-word fragments: "Fast. Simple." / "No fluff. Just answers." -> keep one fragment, cut its twin
- Triplet adjectives in prose: "faster, cheaper, smarter" -> real reasons come in twos or fives, never always three
- Double-metaphor with no advice: "less a hammer, more a scalpel" -> say what to do instead
- Vague ranges: "5 to 10 minutes" -> one real, measured number ("7 minutes"); never invent one
- Lists that feel like padding rather than adding value

### 6. Announcement Language

- "Here's why:", "Here's what I learned:", "Let me explain:"
- Warm-up openers: "Here's the thing", "Let me be clear", "The truth is" -> start one sentence later
- "Enter stage left:", theatrical introductions
- Standalone transition sentences that just introduce the next section ("That's where X comes in.")
- Self-applause sentences: "And that matters." / "That's the part everyone misses." / "Which is exactly the point." -> delete them all; nothing is lost
- Recap endings: "In short", "At the end of the day", any close that restates the piece -> stop typing; end on the high note

### 7. Em Dash Overuse

- Replace most em dashes with commas, periods, colons, or parentheses
- An em dash for an aside -> commas or parentheses
- An em dash introducing a conclusion -> colon or period
- A dramatic pause em dash -> period and new sentence
- Two em dashes bracketing a clause -> commas or parentheses
- LLMs massively overuse em dashes. Most sentences read better without them.

## What Gets Added

- Varied sentence lengths (short punchy + longer explanatory)
- Direct statements instead of hedged ones
- Specific examples instead of vague claims
- Conversational connectors that real people use ("Look,", "The thing is,", "Here's the deal:")
- Your brand voice: knowledgeable but approachable, human, not corporate (see the voice guide below)

## What NOT to Do

- Don't change the core message or argument
- Don't remove technical accuracy
- Don't dumb down -- make it natural, not simplistic
- Don't restructure the piece (that's a structural edit, not humanising)
- Don't add new content or examples
- Don't apply to code blocks, quotes, or technical specifications

## Process

### Mode 1: File Edit (when given a file path)

1. Read the file
2. Create a backup copy with "-original" suffix
3. Make all humanising edits in-place
4. Present a summary: "Made X changes across Y categories. Key changes: ..."
5. Offer to show a diff

### Mode 2: Interactive Review (when user says "review" or "interactive")

1. Read the file
2. Build numbered issue list with category tags
3. Present issues one at a time: original -> suggested fix
4. Accept/skip/quit loop (a/s/q)
5. Apply accepted changes
6. Summary of accepted vs skipped

### Mode 3: Inline Text (when text is pasted or no file path)

1. Take the provided text
2. Apply humanising edits
3. Output the cleaned text directly
4. List what was changed

## Your Brand Voice (customize this)

Fill this in for your own brand. The items below are a starter template - swap the examples for your own product names, spelling conventions, and stances:

- Name things specifically: say the actual product (e.g. "Google Workspace") not "the platform"
- Be direct: "This saves you 2 hours a week" not "This can potentially help optimise your workflow"
- Use "you" and "your team" -- talk TO the reader
- Contractions are fine (we're, it's, don't)
- Pick a spelling convention and hold it (e.g. UK/AU: organisation, optimise, colour; or US: organization, optimize, color) based on your audience
- OK to be opinionated -- have a point of view on the choices in your space
- Short paragraphs. Web readers scan, they don't read walls of text.

## Example Transformations

**Before (AI):** "In today's rapidly evolving digital landscape, it's crucial to understand that leveraging Google Workspace effectively isn't just about utilizing cutting-edge technology -- it's about harnessing its transformative potential to unlock unprecedented productivity gains for your organisation."

**After (human):** "Google Workspace works best when you use it for specific things. Focus on what it actually does well: shared drives, collaborative docs, and admin controls that save your IT team hours every week."

**Before (AI):** "Moreover, it's worth noting that our comprehensive suite of managed IT services facilitates seamless integration between your existing infrastructure and cloud-based solutions, thereby empowering your team to achieve optimal operational efficiency."

**After (human):** "Our managed IT service connects your existing setup to the cloud. Your team keeps working the way they do now, just faster and with fewer headaches."

$ARGUMENTS
