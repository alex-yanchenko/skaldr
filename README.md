# skaldr

Turn **one YAML file** into **one polished, self-contained HTML report page**. You describe *what*
the report says — findings, tables, a pipeline, the numbers — and skaldr owns *how* it looks:
layout, spacing, colour, light/dark, all decided once, here. No design work, no CSS, no drift.

**See it →** [sales pipeline](https://alex-yanchenko.github.io/skaldr/) ·
[warehouse count](https://alex-yanchenko.github.io/skaldr/data-import.html)
(rendered from [`examples/sales-pipeline.yaml`](examples/sales-pipeline.yaml) and
[`data/example.yaml`](data/example.yaml)).

## Install

```bash
brew install alex-yanchenko/tap/skaldr     # recommended (macOS/Linux)
uv tool install skaldr                     # or, with uv
pipx install skaldr                        # or, with pipx
```

All three put a `skaldr` command on your PATH. (From a checkout, `uv run skaldr …` works without
installing.)

## Use

```bash
skaldr report.yaml                 # → out/report.html
skaldr report.yaml -o review.html  # choose the output path
open review.html                   # a self-contained file — open it, host it, or share it
```

That's the whole tool: point it at a content file, get an HTML page. A few more commands help you
write the content file and share the result:

```bash
skaldr --guide                     # the authoring guide: every block, the rules, a full example
skaldr --write-schema page.schema.json   # JSON Schema for your editor's YAML language server
skaldr report.yaml --embed -o out.html   # Artifact-ready fragment (no <html> skeleton) to publish as a claude.ai Artifact
```

There are no styling flags — everything is in the content file.

## The content file

```yaml
version: 1
meta:
  title: "Q3 Warehouse Inventory Count — Discrepancies & Fixes"
  subtitle: ["Reconciled review of the 10,000-unit cycle count."]
  source: "WMS export"          # optional; feeds the provenance footer
  date: "Q3 2026"               # optional; never auto-now (builds are reproducible)
  toc: true                     # optional; auto table-of-contents from level-2 headings
  width: default                # optional; page width cap: default (1600) | wide (1920) | full
  hero: true                    # optional; larger display title + subtitle in a tinted band
badges:                         # author-declared vocabulary (see below)
  FLOOR:  { label: "Floor",  tone: amber, legend: "Fixable on the floor before the next count." }
  SYSTEM: { label: "System", tone: blue,  legend: "Defect in the scanning/labeling pipeline." }
blocks:
  - { type: heading, text: "Overview" }
  - { type: text, body: "Prose with **bold**, *italic*, `code`, ~~strike~~ and [links](https://x)." }
  - { type: cards, items: [{ label: "Matched cleanly", value: 8500, of: 10000, tone: success }] }
  # … more blocks
```

Top level is `version` · `meta` · optional `badges` · `blocks` — nothing else. Every block
carries a `type` discriminator; the model is a pydantic discriminated union, so an unknown
type, a field from the wrong block, or an unknown key each fails with a precise
`blocks.3.items.2.value`-style error before anything renders.

**Blocks:** `heading` · `text` · `list` · `fact_strip` · `key_value` · `cards` · `badge_row` ·
`callout` · `status_list` · `meter` · `table` · `code` · `quote` · `image` · `timeline` ·
`flow` (a directional pipeline — arrow or step style, optional loop) · `section` (collapsible) ·
`grid` (bounded 6-column layout, with optional per-cell emphasis panels). The `table` is the
workhorse — typed columns, grouped subtotals, sub-rows, colour-only `indicator` dots, row-level
`tone`, and a `reconcile` block that hard-fails the build if the counts don't sum to a declared
total. Badges are declared once and chip onto table rows, **cards, timeline entries, and flow
nodes** alike. Prose fields take a small markdown subset (`**bold**`, `*italic*`, `` `code` ``,
`~~strike~~`, links); raw HTML is never interpreted.

Full reference: **`skaldr --guide`** (source: [`src/skaldr/skill/GUIDE.md`](src/skaldr/skill/GUIDE.md)),
[`data/example.yaml`](data/example.yaml) (a file exercising every block), and
[`schema/page.schema.json`](schema/page.schema.json).

## Guarantees

- **One self-contained file** — inline CSS, system fonts, no external resources; the page
  carries its own `<!doctype>` + `<meta charset>` so it renders correctly from `file://`, any
  static host, or a claude.ai Artifact.
- **Validation is the product** — structural mistakes fail the build with a field path, never
  reach the reader's eyes.
- **Derived, not authored** — number formatting, percentages, subtotals, the legend, the TOC,
  and the provenance footer are all computed, so they can't drift from the data.
- **Light & dark** — the palette follows the viewer's OS theme; a small corner menu lets the
  reader switch theme and page width.

## Let an AI write it

skaldr ships a Claude skill, so you can skip the YAML and just ask. Install it once:

```bash
skaldr --install-skill      # copies the skill into ~/.claude/skills (survives upgrades)
```

Then in Claude Code (or Cowork), ask in plain language — *"make me a skaldr report on this data
export: what's clean, what's broken, and the fix"* — and it writes the content file and renders the
page. The skill reads the current guide from the tool itself (`skaldr --guide`), so it stays correct
across upgrades without reinstalling.

## Development

```bash
uv run skaldr data/example.yaml -o out/example.html   # run from a checkout
uv run pytest                                          # tests
```

- [`src/skaldr/models.py`](src/skaldr/models.py) — the content-file contract (pydantic).
- [`src/skaldr/compute.py`](src/skaldr/compute.py) — derived values (legend, TOC, subtotals, footer).
- [`src/skaldr/render.py`](src/skaldr/render.py) + [`components/`](src/skaldr/components) — Jinja rendering.
- [`src/skaldr/styles.css`](src/skaldr/styles.css) — the single tokenised stylesheet.
