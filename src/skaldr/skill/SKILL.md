---
name: skaldr
description: >-
  Author and render a report with skaldr — one YAML content file becomes a polished,
  self-contained HTML page. Use when the user wants a shareable report or summary (an
  investigation, review, audit, data-quality or ingestion writeup, incident post-mortem,
  proposal, or status page) rather than plain prose or a raw table. skaldr owns all design;
  you only describe what the report says.
---

# Authoring a skaldr report

skaldr is a **CLI already on your PATH** — do not look for a source repo, a `uv run`, or a
`python -m`; just run `skaldr`. You write one YAML content file; skaldr renders one self-contained
HTML page and owns all the design.

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

This file is intentionally thin and stable: the version-specific detail lives in `skaldr --guide`
and `skaldr --write-schema`, so it stays correct across upgrades without reinstalling the skill.
