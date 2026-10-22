# Execution blocks

Copy these into the Markdown source as raw HTML. pandoc (gfm) and python-markdown pass the HTML through unchanged. The CSS lives in `assets/house-print.css`.

> The capacity wording below is what past documents used. It is a starting point, not legal advice. Confirm the execution rules for each entity and jurisdiction in the review step (see "Review" in signing-documents.md), and confirm who holds the office today.

## Building blocks

One signer:

```html
<div class="sigblock">
<p class="siglabel">Full Name, Director, for and on behalf of Entity Pty Ltd</p>
<p class="sigtag">[sig|req|signer1]</p>
<p class="sigline">Signature</p>
<p class="datetag">[date|req|signer1]</p>
<p class="sigline">Date</p>
</div>
```

Two signers side by side. Use a **table**, never flex: Chrome's print engine pushes a flex row onto a new page.

```html
<div class="keep">
<table class="sigtable">
<tr>
<td> ...block for signer1 (the p.siglabel / p.sigtag / p.sigline / p.datetag / p.sigline lines)... </td>
<td> ...block for signer2... </td>
</tr>
</table>
</div>
```

The boxes are as tall as their content, so with one-line labels the signature lines line up. When the two
labels differ in length (for example an s127 execution label beside "Name, Director"), write
`<table class="sigtable uneven">`: it reserves five label lines in both cells so the signature lines stay
level. A two-up block needs about 55 mm free at the page foot by default, and about 75 mm with `uneven`.

- The `.keep` wrapper stops the boxes splitting across pages. Put the last clause inside the same wrapper when the boxes keep falling onto a page of their own.
- A two-up table needs about 60 mm free at the foot of the page.
- The white text tags (`[sig|req|signerN]`, `[date|req|signerN]`) are field anchors for the e-sign tool. The `type|req|signerN` syntax is this skill's own convention. Many e-sign tools find fields by text anchors, but each has its own syntax, so map these tags to your tool's format (and adjust the `ESIGN_TAG` pattern in `scripts/verify_pdf.py` to match), or place fields by coordinates instead. Signers must run 1..N with no gap, and every signer in the tags must be in the e-sign request. Decide and state the mapping when you draft ("signer1 = approver, signer2 = counterparty").
- Other tag types: `initial`, `text`, `check`. Use `noreq` for an optional field.
- Keep tags short (no label or ID unless the e-sign tool needs them). A long tag wraps, and its white text paints over the rule below it.
- When the two labels in a `sigtable` differ in length, use `sigtable uneven`, and keep each label to 5 lines or fewer, so the two signature lines stay level.
- Some e-sign tools stamp the signer's name and a timestamp under the signature. The 20 mm `.sigtag` height leaves room for it. Do not shrink it.

## Capacity wording used before

| Signer | Label wording | Notes |
|---|---|---|
| Australian company, two officers | "Executed by <Company> ACN <n> in accordance with s127(1) of the Corporations Act 2001 (Cth) by:" then two blocks, "Director" and "Director/Secretary" | Two signers. For a deed, add "as a deed" (s127(3)). |
| Australian proprietary company, sole director | "Executed by <Company> ACN <n> in accordance with s127(1)(c) of the Corporations Act 2001 (Cth) by its sole director and sole company secretary" (or "...by its sole director, the company having no company secretary") | s127(1)(c) needs one director who is also the sole secretary, OR no secretary at all. Check the ASIC extract and use the wording that matches. |
| US LLC | "<LLC name>, a <State> limited liability company, by: <Name>, its <Manager/Authorized Member/Officer>" | Check the operating agreement for who may sign. |
| Hong Kong company | "Executed by <Company> in accordance with the Companies Ordinance (Cap. 622) by:" then two blocks (two directors, or a director and the secretary) | |
| Individual, agreement | "Signed by <Full Name>" | |
| Individual, deed | "Signed, sealed and delivered by <Full Name> in the presence of:" then a witness block | Witness must not be a party. Add `<div class="witness">` with witness name, signature line and address. |
| Sworn statement (affidavit) before a notary | End with the jurat your notary's jurisdiction requires. A sworn statement uses a jurat ("sworn before me this ___ day of ________ 20__ at ____________"); other notarised documents use an acknowledgement, which has different wording | Wet ink before a notary. Leave the notary lines blank (they are fill-by-hand, so run the gate with `--allow-brackets` only if you used brackets for them). |

## Witness block

```html
<div class="witness">
<p class="sigtag">[sig|req|signer3]</p>
<p class="sigline">Signature of witness</p>
<p class="datetag">[text|req|signer3]</p>
<p class="sigline">Name of witness (print)</p>
<p class="datetag">[text|req|signer3]</p>
<p class="sigline">Address of witness</p>
</div>
```

- The witness must see the signer sign. An e-sign request to the witness does not by itself prove that.
- Remote witnessing (for example by video link in NSW) has its own rules: the witness watches the signing in real time and adds a written endorsement saying how they witnessed it. Check the rules of the place of signing before you plan a remote witness.
- If the witness signs after the parties, send a second e-sign request to the witness only, on the completed PDF, and include the endorsement text if the witnessing was remote.
