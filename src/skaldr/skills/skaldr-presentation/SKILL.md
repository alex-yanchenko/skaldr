---
name: skaldr-presentation
description: >-
  Author the presenter's runbook (a verbatim, color-cued teleprompter) for a talk, and drive the
  audience deck into the org's real brand template, for pitches, demos, board/investor decks,
  keynotes, or a live product walkthrough. Use on "make/rework/tighten a deck", "build a talk
  track", "a cheatsheet I can read from", "turn this into slides". NOT for a written report/doc
  (author that with skaldr directly), a single diagram, or an ad-hoc answer.
---

# Presentation

Split the work by tool, because each is good at a different half:

- **The deck (what the audience sees) → the org's real presentation template** (Google Slides /
  PowerPoint). Brand, logo, and layout ARE the credibility, and a generic or skaldr-rendered deck
  reads as off-brand in a high-stakes room. skaldr does **not** render this deck.
- **The runbook (what the presenter says) → skaldr.** This is skaldr's job and where it's best: a
  word-for-word teleprompter with cues that can't be misread. skaldr also emits the **build-sheet**
  (per-slide headline + bullets + speaker notes + which clip) so filling the template is copy-paste.

Exception: for a quick internal/no-brand talk, a skaldr `slides.yaml` (one `panel` per slide) is a
fine deck. For anything brand-critical, use the template.

Run `skaldr --guide` for blocks. Re-render the runbook after every edit:
`skaldr runbook.yaml -o runbook.html`.

## The runbook, `runbook.yaml` (skaldr's real deliverable)

A cold-open **intro** beat plus **one beat per surface** (each slide, and each clip). Every beat is
a `walkthrough` step whose `detail` is an ordered list alternating cues and reads. Three kinds,
styled so a cue can never be read aloud:

| Kind | Block | Meaning |
|---|---|---|
| **READ** | `{ type: text, body: "…" }` | Plain text, speak **verbatim** |
| **SCREEN** | `{ type: callout, tone: info, body: "🖥️ **SLIDE n**: …" }` | Blue: advance / what's on screen |
| **SHOW/CLIP** | `{ type: callout, tone: warning, body: "🎬 **CLIP n plays**, … narrate over it:" }` | Amber: the demo action or clip |

**The rule the presenter leans on: read the plain lines, never the colored boxes.** Never put a
read in a callout; never put a cue in plain text.

- Give each beat a `sub` with an **honest** time (~2.5 words/sec; don't inflate).
- **Cold open:** name + a one-line hook/callback. No hello/agenda slide.
- The runbook is the **single source of truth** for the words. The deck's speaker notes are copied
  from it, never the other way around.

## The deck, in the brand template

- **Get the real template file** (export the org's deck to `.pptx`) and build the content into its
  layouts, so it inherits theme, fonts, logo, and footer. Don't hand-pick colors; match the brand.
- **4 to 5 content slides.** Punchy headline + a few substantive bullets, not one-liners, not three
  thin slides. Lead with what the audience prices; substance in the bullets, punch in the headline.
- **Constant deck title** + a **section-nav that highlights the current section** beats repeating
  the section as the slide title (that repetition is noise). Highlight one thing per slide.
- **No stage directions on a slide.** Those live only in the runbook.
- Put speaker notes in the tool's **Presenter view** (or keep the runbook on a phone / 2nd screen).

## Demos: recorded-by-default, live as the fallback

For remote or high-stakes demos, **record the clips and present those by default**, since nothing
breaks live, and keep a live environment ready for Q&A.

- **Interleave** content slide → clip → content slide. Each clip is its own full-bleed slide.
- **mp4, muted, autoplay, ~30 fps**, NOT GIF (GIFs balloon to tens of MB and can't do smooth
  motion). For a remote screen-share, clips must be **local files** (never streamed from Drive or
  YouTube, which adds a second network hop that stalls), and **pre-advance once** to cache them.
- **Honest, non-defensive disclosure** in the opener: say it's recorded so it runs smoothly and a
  live environment is ready for questions. State it and move on. Don't protest that "it's real."
- Never let anything spin on the shared screen; the audience sees only the payoff.

## Placeholders

- Write `{{name}}` for anything unknown until rehearsal (a URL, a demo record, a code). It renders
  as a loud chip. `skaldr --check --strict runbook.yaml` fails while any remain; run it before
  "final."

## Writing rules, since the reads are spoken verbatim

- **Plain, natural, spoken English.** If a real person wouldn't say it, rewrite it.
- **No engineer jargon** (say *reads* not "parses", *overnight* not "in a sprint", *enter* not
  "key in") and **no boardroom jargon** unless the audience trades in it ("hard to copy", not "moat").
- **Technical substance, grounded and verified.** For a sophisticated audience don't dumb down.
  Read the actual code/architecture and say what's true, not a vague gesture. Precise beats big.
- **Correct tense.** Describe the product's nature, not a headcount you don't have.
- **Acronyms** spelled out on first use in brackets; skip universal ones (AI, API).
- **No idea said more than twice.** Do a read-aloud pass and cut the third occurrence of any phrase
  or point. Three times reads as strange.

## Honesty

- **Verify every factual/traction claim against real data or code** before it ships.
- **Never claim "first / only / nobody else" unless it's verified.** If you can't prove primacy,
  frame the gap and the difficulty instead, which lands without the risk.
- **Never overclaim** production, partners, or an installed base you don't have; frame thin traction
  as capability and nature, not counts.
- **No defensiveness.** Don't answer a doubt nobody raised ("it's all real"). State it, move on.

## Iterating without wrecking it

- **The runbook is the source of truth. Edit there, re-render, let the presenter reread.**
- **Apply each line-edit exactly, and never silently reintroduce a phrase already fixed.** Copying
  stale text back in is the cardinal sin: it makes the presenter re-catch the same bug.
- **Take each note literally:** "reduce X" is not "delete X"; "more slides" means 4 to 5, not 10.
- **Evolve; never rebuild from scratch.** Ask before a structural reframe; apply line-edits directly.

## Consistency checklist, run every build

- [ ] Deck is in the org's real template (or a skaldr deck only if it's a quick internal talk).
- [ ] Runbook exists and is re-rendered after the last edit; it's the source of truth for the words.
- [ ] 4 to 5 content slides: headline + real bullets. Constant title + section-nav highlight; no
      section repeated as its own title.
- [ ] Runbook = intro + one beat per surface (slide and clip); honest per-beat times.
- [ ] Every cue is a colored callout (🖥️ blue / 🎬 amber); every read is plain `text`; no read in a
      box, no cue in plain text.
- [ ] Demos: mp4 (not GIF), local, muted-autoplay, interleaved, pre-cached; honest non-defensive
      disclosure; live env ready for Q&A.
- [ ] Plain spoken English; no jargon; correct tense; acronyms on first use.
- [ ] Every claim verified; no "first/only" unless proven; thin traction framed as capability.
- [ ] No idea said 3+ times; no defensive lines.
- [ ] `{{placeholders}}` for unknowns; `--check --strict` clean (or open ones are intentional).
- [ ] This pass evolved the docs, with no from-scratch rewrite; each note applied exactly, no fixed
      phrase reintroduced.
