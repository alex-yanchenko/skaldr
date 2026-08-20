---
name: skaldr-reflect
description: >-
  Turn your own experience of authoring with skaldr into a ranked, actionable pain-points report to
  hand to skaldr's maintainer. Use AFTER you've built one or more skaldr reports this session and the
  user asks to "reflect on skaldr", "what did skaldr make hard", "write up skaldr pain points / feedback",
  "what did you fight / work around in skaldr", "what's missing in skaldr", or "feedback for the skaldr
  maintainer". NOT for authoring a report (use skaldr directly) or reviewing skaldr's source code.
---

# Reflecting on skaldr

You've been using skaldr to author reports. This skill turns the friction you actually hit into a
report the maintainer can act on, the same shape that drives skaldr's own improvements. Your output
is **feedback about the tool**, not another report *with* the tool.

## Ground every pain point in a real moment

The one rule: **each pain point must trace to a concrete thing you did this session.** A block that
didn't exist so you faked it with another, a field you wanted that wasn't there, a validation error you
fought, a workaround you typed, a layout you couldn't express, a doc line that was ambiguous. If you
can't point to the moment it bit you, drop it. A reflection built from real friction is worth ten
plausible-sounding wishes.

**Check the guide before you propose anything.** Run `skaldr --guide` (and `skaldr --write-schema` for
exact fields) and confirm the thing you wanted really is missing. Half of "skaldr can't do X" is X
existing under a name you didn't reach for, and proposing a fix for something that already ships wastes
the maintainer's time and erodes trust in the rest of your list. If it exists, that's a
*docs/discoverability* pain point instead (you looked and didn't find it), which is still worth
reporting, just framed honestly.

## What to capture per pain point

- **What you were trying to express:** the intent, in one line.
- **What you did instead:** the workaround, naming the block(s) you abused or the field you faked
  (e.g. "used a `text` with `muted: true` as a caption because a heading has no subtitle slot").
- **Impact:** how often it came up this session and how much it hurt the result (a cosmetic nit vs. a
  wrong/again-drifting number vs. couldn't-express-it-at-all).
- **Proposed fix:** concrete. A new block, a new field, a behavior. Draft the *shape* (a snippet of the
  YAML you wish had worked), not just a wish. If a fix is uncertain, say what you're unsure about.

## Rank by impact, most valuable first

Order by frequency × severity. A small caption nit you hit once ranks below a missing block you worked
around in every report. Put a one-line "why this order" note if the ranking isn't obvious. Don't pad the
list to a round number: three real pain points beat eight with filler.

## Output, a ranked report to hand over

Produce a ranked markdown list the user can paste straight to the maintainer (or into an issue). Lead
with a one-line summary of how skaldr felt overall (what worked, so the list reads as calibrated, not
just complaints), then the ranked items:

```
skaldr felt <one honest line>. Ranked pain points from this session:

1. <title>: <what you wanted>
   Did instead: <workaround, naming the blocks/fields>
   Impact: <frequency + severity, grounded in this session>
   Proposed fix: <concrete: a block/field/behavior, with the YAML shape you wish worked>

2. …
```

Keep each item tight. The maintainer reads the *what* and the *fix*, not a narrative. Technical, plain,
no flattery and no hedging.

**Offer to render it as a skaldr doc.** The list is the deliverable; but since it's for skaldr's
maintainer, offer to also render it *with* skaldr (a `list` or a `table` of items, a `cards` count of
how many are missing-block vs field vs docs). Dogfooding that itself surfaces friction worth adding to
the report. Only if the user wants it; the pasteable markdown comes first.

## Guard against the easy failures

- **No invented friction.** Every item cites a real moment this session. If the session was smooth, say
  so and return a short list (or none): a padded reflection is worse than an honest "little to report".
- **No vague items.** "Clunky" / "awkward" isn't a pain point until it names the block, the workaround,
  and the fix. If you can't get concrete, you haven't found the real issue yet.
- **Stay in scope.** Only skaldr-authoring friction, not the content domain, not the user's data, not
  general AI gripes.
- **Don't fix it yourself.** This skill produces feedback for the maintainer; it doesn't patch skaldr.
