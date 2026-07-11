# skaldr

A component framework for **AI-authored report pages**. An AI (or a person) doing real
work — an investigation, a review, a proposal, an ingestion report — writes **one YAML
content file**; skaldr validates it and renders **one polished, self-contained HTML page**.
No time is spent on design, styling, or layout: those decisions are made once, here, by the
component library.

## The easy way — just ask Claude (no install)

You don't need Python or a terminal. Open Claude Code or Cowork, point it at skaldr, and ask in
plain language — it writes the report and renders it for you:

- *"Make me a skaldr report on our Q3 pipeline — deals by stage, what's at risk, the forecast."*
- *"Turn this account list into a skaldr QBR: health by account, renewals, expansion."*
- *"Build a win/loss report from these closed deals — why we won, why we lost, by segment."*
- *"Skaldr report: pipeline health this month — coverage, deal aging, slipped deals."*
- *"Audit this data export as a skaldr report — what's clean, what's broken, and the fix."*

Claude installs the skill on first use (`skaldr --install-skill`) and takes it from there; the
finished report is a self-contained HTML file you can open, share, or publish.

**See live samples →** [sales pipeline](https://alex-yanchenko.github.io/skaldr/) ·
[warehouse count](https://alex-yanchenko.github.io/skaldr/data-import.html) (rendered from
[`examples/sales-pipeline.yaml`](examples/sales-pipeline.yaml) and
[`data/example.yaml`](data/example.yaml)). The rest of this README is for developers running
skaldr directly.

```bash
# from a checkout
uv run skaldr data/example.yaml
open out/example.html

# or installed (from PyPI, once published)
uv tool install skaldr
skaldr data/example.yaml
```

The CLI is deliberately tiny: `skaldr <content.yaml> [-o out.html]`, plus
`skaldr --write-schema schema/page.schema.json`. There are no styling flags — everything is
in the content file.

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
`section` (collapsible) · `grid` (bounded 6-column layout). The `table` is the workhorse — typed
columns, grouped subtotals, sub-rows, and a `reconcile` block that hard-fails the build if the
counts don't sum to a declared total. Prose fields take a small markdown subset
(`**bold**`, `*italic*`, `` `code` ``, `~~strike~~`, links); raw HTML is never interpreted.

**Learn the format:**
- **`skaldr --guide`** — the authoring guide (every block, the table, badges, rich text, the
  rules) with a complete example, straight from the installed version. Source:
  [`src/skaldr/skill/GUIDE.md`](src/skaldr/skill/GUIDE.md).
- [`data/example.yaml`](data/example.yaml) — a complete file exercising every block.
- [`schema/page.schema.json`](schema/page.schema.json) — the machine-readable contract; point
  your editor's YAML language server at it, or regenerate with `skaldr --write-schema`.

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

## Use with Claude Code

skaldr ships a Claude skill so an AI can author reports for you. After installing skaldr, run:

```bash
skaldr --install-skill
```

It copies the skill into `~/.claude/skills/` (or tells you how if Claude Code isn't set up). Then
ask Claude — *"make me a skaldr report on X"* — and it writes the YAML and renders it.

The skill is thin and stable: it reads the current authoring guide from the tool itself
(`skaldr --guide` for the tour, `skaldr --write-schema` for exact fields), so it's
**install-once** — no need to re-run after a `brew upgrade`.

## Layout

- [`src/skaldr/models.py`](src/skaldr/models.py) — the content-file contract (pydantic).
- [`src/skaldr/compute.py`](src/skaldr/compute.py) — derived values (legend, TOC, subtotals, footer).
- [`src/skaldr/render.py`](src/skaldr/render.py) + [`components/`](src/skaldr/components) — Jinja rendering.
- [`src/skaldr/styles.css`](src/skaldr/styles.css) — the single tokenised stylesheet.
