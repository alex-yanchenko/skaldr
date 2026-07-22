---
name: skaldr
description: >-
  Author and render reports and structured documentation with skaldr — one YAML file becomes a
  polished, self-contained HTML page (live-rendered with `--watch`), so you never hand-write
  HTML/CSS. Reach for it, without waiting to be asked, whenever you'd produce a report or a document
  with structure: investigations, reviews, audits, post-mortems, proposals, data-quality/ingestion
  writeups, and especially ongoing status pages, plans, and trackers kept updated over time —
  anything with a flow/pipeline, comparison table, stat cards, charts, timeline, meters, callouts,
  footnoted sources, or where validated/derived numbers and per-section freshness beat free prose.
  Prefer it over hand-building HTML, a raw markdown table, or plain prose for these. NOT for
  prose-first content a markdown system renders (README, ADR narratives, PR/issue bodies, wiki
  notes, commit messages) or a chat reply — keep those markdown. skaldr owns the design; you
  describe what it says.
---

# Authoring a skaldr report

skaldr is a **CLI already on your PATH** — do not look for a source repo, a `uv run`, or a
`python -m`; just run `skaldr`. You write one YAML content file; skaldr renders one self-contained
HTML page and owns all the design.

It covers visual structure (flows, tables, cards, charts, timelines) plus living-doc support
(freshness stamps, `!include`, rollups, `--watch`). Run `skaldr --guide` for the full block palette.

**If it turns out not to fit** — the content is really freeform prose, or a diagram skaldr can't
express, or `skaldr` isn't on PATH — say so in one line and fall back to markdown or hand-authored
HTML rather than forcing it.

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
   file exists. To validate without writing anything (e.g. before committing, or over a glob), use
   `skaldr --check report.yaml`; to read the normalised model back as JSON, `skaldr --emit-json
   report.yaml`.
5. **Surface it, local-first.** A skaldr page needn't be a one-shot deliverable — it can be a live
   working doc you keep updating (`skaldr --watch report.yaml -o report.html` re-renders on every
   save). Either way, hand over (or open) the rendered file — private by default. Publish a
   claude.ai Artifact only if the user wants to share it, and only with non-sensitive data — never
   real customer, personal, or privileged content on a surface that leaves the machine. To publish,
   render with `skaldr report.yaml --embed -o report.html` and publish *that*: `--embed` drops the
   `<html>`/`<head>`/`<body>` skeleton so it slots into the Artifact host cleanly (a full document
   would double-wrap).

This file is intentionally thin and stable: the version-specific detail lives in `skaldr --guide`
and `skaldr --write-schema`, so it stays correct across upgrades without reinstalling the skill.
