---
name: skaldr
description: >-
  Author and render a report, explainer, or design write-up with skaldr — one YAML file becomes a
  polished, self-contained HTML page, so you never hand-write HTML/CSS. Use it for any shareable
  report, summary, how-does-X-work / data-model explainer, or architecture/design doc
  (investigations, reviews, audits, ingestion/data-quality writeups, post-mortems, proposals, status
  pages) — especially when it needs visual structure: a flow/pipeline, fan-in/out, comparison
  table, stat cards, charts, timeline, meters, callouts, or footnoted sources. Reach for it instead
  of hand-building an HTML page, plain prose, or a raw table, without waiting to be asked. NOT for
  content a markdown system renders (PR/issue bodies, README, wiki notes, commit messages) or a
  chat reply. skaldr owns the design; you describe what it says.
---

# Authoring a skaldr report

skaldr is a **CLI already on your PATH** — do not look for a source repo, a `uv run`, or a
`python -m`; just run `skaldr`. You write one YAML content file; skaldr renders one self-contained
HTML page and owns all the design.

It covers visual structure too — flows/pipelines, comparison tables, stat cards, charts, timelines —
so for an architecture or design doc, reach for it before hand-building HTML. Run `skaldr --guide`
for the full block palette.

**If it turns out not to fit** — the content is really freeform prose, or a diagram skaldr can't
express, or `skaldr` isn't on PATH — say so in one line and fall back to markdown or hand-authored
HTML rather than forcing it. (Whether skaldr fits at all is a routing call the description already
makes; this is the render-time bail.)

**Author from real evidence.** Every number, date, and claim must come from the data, files, or
facts in front of you. If you don't have a value, ask for it or leave the block out — never invent
one to fill the template. The `reconcile` check catches totals that don't add up, not confident
fabrication, so honesty is on you.

## Workflow

1. **Load the current contract from the tool itself** (it matches the installed version, so trust
   it over anything you remember):
   - `skaldr --guide` — the authoring guide: every block, the rules, the `table`, and a complete
     example.
   - `skaldr --write-schema /tmp/skaldr.schema.json` — the exact fields/types, when you need them.
2. **Write the YAML** from real evidence, following the guide.
3. **Render:** `skaldr report.yaml -o report.html`.
4. **Confirm it rendered.** A structural mistake fails the build with a precise path
   (`blocks.3.items.2.value: ...`) — read it, fix, re-run. Done = skaldr prints `OK` and the output
   file exists.
5. **Surface it, local-first.** Hand over (or open) the rendered file — private by default. Publish a
   claude.ai Artifact only if the user wants to share it, and only with non-sensitive data — never
   real customer, personal, or privileged content on a surface that leaves the machine. To publish,
   render with `skaldr report.yaml --embed -o report.html` and publish *that*: `--embed` drops the
   `<html>`/`<head>`/`<body>` skeleton so it slots into the Artifact host cleanly (a full document
   would double-wrap). The embedded page carries its own theme + width control and follows the
   reader's OS theme.

This file is intentionally thin and stable: the version-specific detail lives in `skaldr --guide`
and `skaldr --write-schema`, so it stays correct across upgrades without reinstalling the skill.
