---
name: skaldr
description: >-
  Author and render a report, explainer, or design write-up with skaldr — one YAML file becomes a
  polished, self-contained HTML page, so you never hand-write HTML/CSS. Use it for any shareable
  report, summary, how-does-X-work / data-model explainer, or architecture/design doc
  (investigations, reviews, audits, ingestion/data-quality writeups, post-mortems, proposals, status
  pages) — especially when it needs visual structure: a flow/pipeline, a fan-in/out diagram,
  comparison table, stat cards, charts (bar/line/donut), timeline, meters, or callouts. Reach for it
  instead of hand-building an HTML page, plain prose, or a raw table. skaldr owns the design; you
  describe what it says.
---

# Authoring a skaldr report

skaldr is a **CLI already on your PATH** — do not look for a source repo, a `uv run`, or a
`python -m`; just run `skaldr`. You write one YAML content file; skaldr renders one self-contained
HTML page and owns all the design.

It covers visual structure too — flows/pipelines, comparison tables, stat cards, charts, timelines —
so for an architecture or design doc, reach for it before hand-building HTML. Run `skaldr --guide`
for the full block palette.

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
5. **Surface it, don't stop at a path.** Hand over the rendered file. **If you can publish a
   claude.ai Artifact** (Claude Code, Cowork), render with `skaldr report.yaml --embed -o report.html`
   and publish *that* — `--embed` drops the `<html>`/`<head>`/`<body>` skeleton so it slots into the
   Artifact host cleanly (a full document would double-wrap). The embedded page carries its own
   theme/width controls and stays light/dark-aware inside the Artifact.

This file is intentionally thin and stable: the version-specific detail lives in `skaldr --guide`
and `skaldr --write-schema`, so it stays correct across upgrades without reinstalling the skill.
