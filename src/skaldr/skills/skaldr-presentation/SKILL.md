---
name: skaldr-presentation
description: >-
  Build a talk-ready presentation with skaldr — slides plus a word-for-word teleprompter
  run-of-show with color-coded live-or-recording cues and a built-in fallback plan. Use whenever
  someone wants to make, build, rework, or tighten a presentation, pitch, deck, demo, board or
  investor slides, a talk track, a keynote, or a live product walkthrough — including "turn this
  into slides" or "make a cheatsheet I can read from." NOT for a written report or document
  (author that with skaldr directly), a single diagram, or an ad-hoc chat answer.
---

# Presentation

Produce **two skaldr documents**, never hand-written HTML, and re-render both after every edit:

1. **`slides.yaml`** — what the audience sees. One `panel` per slide.
2. **`runbook.yaml`** — the presenter's word-for-word run-of-show: a cold-open intro plus one beat per slide.

Run `skaldr --guide` for the block palette. Render after each change:
`skaldr slides.yaml -o slides.html && skaldr runbook.yaml -o runbook.html`.

## Slides — `slides.yaml`

- **4–5 content slides.** Not a stack of ten one-line flash cards; not three thin ones. Each slide is a **punchy headline** plus **a few substantive bullets** — real content, not a single message.
- One `panel` per slide: `title` is the headline, `blocks` is a short `list`.
- **Lead with what this audience prices**, differentiation first, reassurance second. Investors: the wedge, first-to-market, defensibility, market size, execution ("last time we showed X — here's what we built with it"). Customers: the outcome and the hours saved.
- Headlines carry the punch; bullets carry the substance. **No stage directions on a slide** — those live only in the runbook.

## Runbook — `runbook.yaml` — the teleprompter

A cold-open **Intro** beat plus **one beat per slide**. Each beat is a `walkthrough` step whose `detail` is an **ordered list of blocks** alternating cues and reads. Three kinds, styled so a cue can never be read aloud by mistake:

| Kind | Block | Meaning |
|---|---|---|
| **READ** | `{ type: text, body: "…" }` | Plain text — speak it **verbatim** |
| **SCREEN** | `{ type: callout, tone: info, body: "🖥️ **SCREEN** — …" }` | Blue box — advance / what's on screen |
| **SHOW** | `{ type: callout, tone: warning, body: "🎬 **SHOW** — *Live:* … · *Plan B:* play **GIF-N**" }` | Amber box — do the live action (or play the recording) |

**The rule the presenter leans on: read the plain lines, never the colored boxes.** Never put read text in a callout; never put a cue in plain text.

- Give each beat a `sub` with an **honest** time. Verbatim reads run ~2.5 words/second — a four-slide deck is roughly 3–4 minutes of talking; live/recording dwell fills the rest. Don't inflate.
- **Cold open:** presenter's name, a one-line hook or callback, an optional light line (a "demo gods" joke doubles as cover for the recording fallback). No hello/agenda slide.

## Plan A / Plan B — one script, two ways to show

- **Plan A** is live; **Plan B** is pre-recorded clips (GIFs). The **spoken lines are identical either way** — only the *show* differs — so every SHOW cue carries **both**: `*Live:* <action>  ·  *Plan B:* play **GIF-N**`.
- List the clips to pre-record in the runbook's setup. The fallback means a flaky system, network, or nerves never breaks the talk — you're always already on Plan B.
- Never let anything spin on the shared screen. **Pre-warm** anything that takes more than ~2 seconds off-camera; the audience only sees the payoff.

## Placeholders

- Write `{{name}}` for anything unknown until rehearsal (a URL, a demo record, a code). It renders as a loud chip so it can't ship unfilled.
- Gate before "final": `skaldr --check --strict runbook.yaml` fails while any placeholder remains.

## Writing rules — the reads are spoken verbatim

- **Plain, natural, spoken English.** If a real person wouldn't say it that way, rewrite it.
- **No engineer jargon** in reads or slides — say *reads* not "parses", *overnight* not "in a sprint", *shortcut* not "wrapper", *entering it* not "keying it in". The audience isn't engineers.
- **No boardroom jargon unless the audience genuinely trades in it** — prefer "hard to copy" and "they won't want to go back" over "moat", "switching cost", "durable revenue".
- **Correct tense.** Describe the product's *nature* ("once someone runs on it, they won't want to go back"), not a headcount you don't have — present tense implies an installed base, so only use it when it's true.
- **Acronyms:** spell out on **first use, in brackets** — "SIS (Student Information System)". Skip universally-known ones (AI, API).
- Do a **read-aloud pass**: anything stilted, overlong, or that repeats a claim gets cut.

## Honesty

- **Verify every factual and traction claim** before it goes on a slide — check the data, don't assume.
- **Never overclaim** production, partners, or an installed base you don't have.
- **Never lie — and never expose the soft spot.** When traction is thin, frame the **capability and the product's nature**, not counts ("once it's part of how they work…" is true and reveals nothing).
- **Match register to the audience** — sophisticated people aren't children; don't dumb it down, and don't cheapen it with vague puffery either.
- Plant a differentiation claim ("first to market", "no one else can do this") **once**, confidently, no hedge — not three times.

## Export to a slide tool (e.g. Notion)

- One slide per `---` divider (present modes break on dividers). **Clean titles** — drop any "Slide N" working labels.
- **The exported page's title usually shows on screen.** Never leave an internal or throwaway one; use a real cover line or the org's name, or confirm it.

## Iterating without wrecking it

- **Evolve the existing docs — never rebuild from scratch.** They accumulate the presenter's edits; a full rewrite destroys them. Make the smallest change that satisfies the note.
- **Take each note literally:** "reduce X" is not "delete X"; "more slides" means four or five, not ten.
- **Ask before a structural reframe** (the arc, the lead, the audience framing); **apply line-edits directly** and show the result.
- **Re-render after every change** and let the presenter reread. One live click is the goal, not ten.

## Consistency checklist — run every build

Tick all before calling a build done (this is what keeps repeated runs from drifting):

- [ ] Both docs exist (`slides.yaml`, `runbook.yaml`) and are re-rendered after the last edit.
- [ ] 4–5 slides; each a headline plus a few real bullets (not one-liners, not three slides).
- [ ] Runbook = intro + one beat per slide; honest per-beat times.
- [ ] Every cue is a colored callout (🖥️ blue SCREEN / 🎬 amber SHOW); every read is plain `text`; no read is in a box and no cue is plain text.
- [ ] Every SHOW carries **both** `*Live:*` and `*Plan B:* GIF-N`; the clips are listed in setup.
- [ ] Reads are plain spoken English — no engineer jargon, no unearned boardroom jargon, correct tense.
- [ ] Acronyms spelled out on first use; universal ones skipped.
- [ ] Every factual/traction claim verified; nothing overclaimed; thin spots framed as capability, not counts.
- [ ] Differentiation planted once, no hedge.
- [ ] `{{placeholders}}` for unknowns; `skaldr --check --strict` clean (or the open ones are intentional).
- [ ] Export (if any): one slide per divider, clean titles, safe visible page title.
- [ ] This pass evolved the existing docs — no from-scratch rewrite; each note taken literally.
