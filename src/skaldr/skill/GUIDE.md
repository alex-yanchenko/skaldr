# skaldr — authoring guide

The current, version-matched authoring contract, printed by `skaldr --guide`. A skaldr report is
**one YAML file**: you describe *what* it says; skaldr owns *how* it looks. For exact field names,
types, and constraints, also run `skaldr --write-schema <path>` (the machine-readable JSON Schema,
generated from the same models).

## Shape

```yaml
version: 1          # required, integer
meta: { ... }       # page header + options
badges: { ... }     # optional: your tag/status vocabulary
blocks: [ ... ]     # the ordered content
```

Top level is exactly `version`, `meta`, optional `badges`, `blocks` — nothing else. Every block
is a mapping with a `type` discriminator. **Validation is strict:** an unknown block type, a
field that doesn't belong to that block, an unknown top-level key, or a value of the wrong shape
each fails the build with a precise path.

## `meta`

```yaml
meta:
  title: "Q3 Warehouse Inventory Count — Discrepancies & Fixes"   # required
  subtitle: ["one line", "another"]                    # optional
  source: "WMS export"           # optional; shown in the provenance footer
  date: "Q3 2026"                # optional; footer. Author it — skaldr never inserts "now"
  toc: true                      # optional; auto table-of-contents from level-2 headings
  width: default                 # optional; page width cap: default (1600px) | wide (1920px) | full
  hero: true                     # optional; a larger display title + subtitle in a tinted band
```

`hero` opts the page into a bolder opening — a large display title and subtitle in a tinted band —
for a page that leads by selling an idea (a proposal, an explainer) rather than a plain report header.

`width` caps how wide the page may grow. It's a ceiling — on a screen narrower than the cap the
page fills the viewport regardless. (The rendered page also carries a corner menu that lets a
reader switch theme and width, but the author sets the default here.)

## `badges` — your vocabulary

skaldr ships **no** built-in tags or statuses. Declare the ones your report uses:

```yaml
badges:
  FLOOR:  { label: "Floor",  tone: amber, legend: "Fixable on the floor before the next count." }
  SYSTEM: { label: "System", tone: blue,  legend: "Defect in the scanning/labeling pipeline." }
```

Each key maps to a `label` (chip text), a `tone` (chip colour), and a `legend` (one-line
meaning). Reference a key from a table `badge` column, a `badge_row`, or a `badges: [KEY, …]` list
on a **card, timeline entry, or flow step** (the chips render on that container). **A referenced key
that isn't declared fails the build.** A legend of the badges you actually used is generated
automatically before the first table — you don't author it.

Badge colours: `slate · blue · green · amber · red · violet · teal · sky`.

## Rich text

Prose fields (`text.body`, table `rich`/`text` cells, `callout.body`, list items, `quote.body`,
`key_value` values, timeline/status text) accept a small markdown subset:

`**bold**` · `*italic*` · `` `code` `` · `~~strike~~` · `[label](https://url)`
(links allow `http`, `https`, `mailto` only).

Everything else is escaped and shown literally — there is no raw HTML. A blank line in a `text`
body starts a new paragraph.

## Numbers are formatted for you

Write raw numbers (`8500`, not `"8,500"`). skaldr adds thousands separators, computes
percentages, subtotals, and the reconciliation line. A number field rejects booleans and
infinities.

## Blocks

| `type` | Purpose | Key fields |
|---|---|---|
| `heading` | Section structure (feeds the TOC at level 2) | `text`, `level: 2\|3` |
| `text` | Prose paragraph(s) | `body`, `muted?` |
| `list` | Bulleted or numbered points | `style: bullet\|number`, `items[]` |
| `fact_strip` | One-line metadata row | `facts: [{label, value}]` (1–8) |
| `key_value` | Vertical label/value metadata | `pairs: [{label, value}]` |
| `cards` | Headline numbers | `items: [{label, value, of?, tone?, note?, badges?}]` |
| `badge_row` | A standalone row of chips | `label?`, `items: [{key} \| {label, tone}]` |
| `callout` | "Stop and look" note | `tone: info\|success\|warning\|danger`, `title?`, `body` |
| `status_list` | Checks / steps | `items: [{state: done\|pending\|failed\|blocked, text}]` |
| `meter` | Labelled bars | `items: [{label, value, max, tone?}]` |
| `table` | The workhorse (see below) | `columns`, `groups`/`rows`, `reconcile?`, `totals?` |
| `code` | Code / logs / diff | `content`, `label?`, `mode: plain\|diff` |
| `quote` | A verbatim quotation | `body`, `cite?` |
| `image` | An embedded image | `src` (a `data:` URI), `alt`, `caption?`, `max_width?` |
| `timeline` | Ordered events | `items: [{title, time?, body?, state?, badges?}]` |
| `flow` | A directional pipeline / process (see below) | `steps: [{label, tone?, note?, badges?}]`, `style: arrow\|steps`, `loop?`, `numbered?` |
| `section` | Collapsible container | `title`, `collapsed?`, `blocks[]` |
| `grid` | Side-by-side layout (6 columns) | `cells: [{span: 1-6, blocks[]}]` |

Cards: pass `of` to render a derived percentage (`8,500 · 85.0%`). A `value` may be a short
string (e.g. `HEALTHY`) instead of a number. Images must be self-contained `data:` URIs — skaldr
embeds images, it does not fetch or generate them; **base64-encode the payload** (a raw,
unencoded SVG isn't a valid URI and won't render). A `section` holds any blocks except another
`section` (one level of nesting only).

## The `grid`

Place blocks side by side over a 6-column base. Each cell takes a required `span` (1–6); spans in
one grid sum to at most 6 (leave it under 6 for trailing space).

```yaml
- type: grid
  cells:
    - span: 2                       # left third
      blocks:
        - { type: cards, items: [ ... ] }
    - span: 4                       # right two-thirds
      blocks:
        - { type: table, ... }
```

A cell's blocks stack vertically. A cell may hold one nested `grid` (depth 2 max); a nested
grid's cells hold only leaf blocks. `grid` and `section` don't mix. Below a narrow width the
columns stack into one. You choose *how many columns* and *which cells*; skaldr owns every width,
gap, and alignment. For many equal small items (e.g. cards), prefer the block's own auto-flow
rather than a grid; the grid is for asymmetric composition.

Give a cell an optional **`tone`** to make it an emphasis panel (accent top-border + tint): use
`accent`/`success` for the *primary* panel and `neutral` for a *muted aside*, so a reader sees which
of two side-by-side panels is the answer.

## The `flow`

A directional pipeline — the block for a process, data flow, or architecture where the **direction
between stages is the message** (the thing a bulleted list or `status_list` throws away). Nodes are
connected left-to-right; the connector leads each node, so a long flow wraps cleanly with no
dangling arrows.

```yaml
- type: flow
  style: arrow          # arrow (default) | steps
  loop: true            # draws a "↺ back to <first>" return marker — for a cycle, not a one-way flow
  numbered: true        # 1..n on the nodes (default); set false to hide
  steps:
    - { label: "Source",  tone: info,    note: "Atlas Advisor + $indexStats" }
    - { label: "Reason",  tone: info }
    - { label: "Propose", tone: accent }
    - { label: "Deliver", tone: success }
```

**Which `style`:**
- `arrow` (default) — short-labelled chips joined by connectors. Reach for it when the flow is the
  *direction itself*: a pipeline, a request path, a state cycle. Keep labels to a word or two.
- `steps` — equal cards that each carry a one-line `note` caption. Reach for it when **every stage
  needs a sentence of explanation** and the labels alone aren't enough.

Rule of thumb: if most nodes have a `note`, use `style: steps`; otherwise `arrow`. A flow with more
than ~6 nodes usually reads better as `steps`, or split into two flows. `tone` (any of
`neutral·info·success·warning·danger·accent`) accents a node's border + number — use it to mark the
key stage, not every node. `loop` is for genuine cycles (flag→fix→verify→flag), not linear pipelines.

## The `table`

```yaml
- type: table
  columns:
    - { key: issue,   label: "Discrepancy",   kind: text }    # first text/rich col = the title
    - { key: tag,     label: "",              kind: badge }   # chip shown under the title
    - { key: count,   label: "Units",         kind: number, pct_of_total: true }
    - { key: problem, label: "What happened", kind: rich }
  reconcile:                        # optional trust check
    total: 10000
    column: count
    handled: { label: "Matched cleanly", value: 8500 }   # optional bucket outside the rows
  groups:                           # OR use `rows:` for an ungrouped table (not both)
    - name: "Floor — fixable"
      rows:
        - issue: "Double-counted units"
          tag: FLOOR
          count: 600
          problem: "The same pallet is scanned twice…"
          subrows:                  # optional quieter inner rows
            - { label: "bin > 12", value: 260 }
```

- **Columns** need at least one `text`/`rich` column (it hosts the row title and any chips). A
  `badge` column's value renders as a chip under the title, not in its own cell. An `indicator`
  column renders a colour-only **dot in its own cell** — the cell value is a tone name
  (`success`/`warning`/`danger`/…) or blank; use it for several orthogonal green/amber/red signals
  per row (e.g. Reliability, Cost) that each want their own at-a-glance column.
- **Column widths** are automatic by default. To set proportions, give every non-badge column a
  `width` weight (1–6): each takes `width / Σwidth` (e.g. `4` + `2` → two-thirds / one-third).
  It's all-or-none — set `width` on every non-badge column or none; `badge` columns can't take one.
- **Every row supplies every column key and nothing else** (plus an optional `subrows`, and an
  optional `tone: muted | danger`). A row `tone` emphasises the whole row: `muted` dims and strikes
  it (a rejected/superseded row), `danger` tints it red (a bad row).
- **`reconcile`** is the trust check: the column sum, plus any `handled` bucket, must equal
  `total` or the build fails naming the delta. With `pct_of_total` on a number column, each cell
  also shows its share of the reconcile total.
- **`totals`** adds a bold footer summing a number column (for tables that aren't reconciled).
- A group with an empty `rows: []` renders a "— none —" row, so an empty section reads as
  intentional. Group bands show a subtotal of the reconcile/totals column.

## What you never write

Colours, CSS, fonts, pixel sizes, HTML, the legend, the TOC, percentages, subtotals, the
provenance footer, or thousands separators. Those are derived or fixed by the design system, so
they can't drift from your data. If a report seems to need markup skaldr doesn't offer, it needs
a component — file it, don't smuggle HTML.
