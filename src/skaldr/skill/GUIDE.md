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
  hero: true                     # optional; a larger display title + subtitle in a tinted band
```

`hero` opts the page into a bolder opening — a large display title and subtitle in a tinted band —
for a page that leads by selling an idea (a proposal, an explainer) rather than a plain report header.

Page **width is not an authoring choice** — every page renders at the default cap, and the reader
alone widens it (default / wide / full) from the corner menu on the rendered page. There is no
`meta.width`; don't set one (it fails the build).

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

A standalone `badge_row` is either **flat** (`items:` — an optional leading `label` then chips) or
**grouped** (`groups: [{label, items}]` — each group renders as a labelled gutter row, the labels
aligned in a column like `key_value`). Use one or the other, not both. Reach for `groups` when a dense
set of chips reads better split into a few titled rows.

```yaml
- type: badge_row
  groups:
    - { label: "Severity", items: [{ key: HIGH }, { key: LOW }] }
    - { label: "Area", items: [{ label: "API", tone: blue }, { label: "UI", tone: violet }] }
```

## Colours & tones — one palette, two names

Every `tone:` (on cards, flows, fans, meters, walkthroughs, chart series, comparison cells, …) and every
badge colour names the **same eight colours**. Six of them have two interchangeable names — a *semantic*
name and a *palette* name — and `teal`/`sky` have a palette name only:

`neutral` = `slate` · `info` = `blue` · `success` = `green` · `warning` = `amber` · `danger` = `red` · `accent` = `violet` · `teal` · `sky`

Write whichever reads best: `tone: success` and `tone: green` are identical, and a badge `tone: info` is the
same as `tone: blue`. (`callout` is narrower — it maps only to the four semantic tones info/success/warning/danger;
their palette aliases blue/green/amber/red work too, but accent/neutral/teal/sky don't.) The generated JSON
schema lists the canonical names; the alias names still validate at build even if an editor flags them.

## Rich text

Prose fields (`text.body`, table `rich`/`text` cells, `callout.body`, list items, `quote.body`,
`key_value` values, timeline/status text) accept a small markdown subset:

`**bold**` · `*italic*` · `` `code` `` · `~~strike~~` · `[label](https://url)`
(links allow `http`, `https`, `mailto` only).

**Link to the real thing.** When you cite a ticket, PR, doc, dashboard, or page, use its actual URL —
never a placeholder like `#` or `https://example.com`. (skaldr's own bundled examples use fictional
links on purpose because they ship publicly; that's the exception, not a pattern to copy into a real
report.)

Everything else is escaped and shown literally — there is no raw HTML. A blank line in a `text`
body starts a new paragraph.

## Numbers are formatted for you

Write raw numbers (`8500`, not `"8,500"`). skaldr adds thousands separators, computes
percentages, subtotals, and the reconciliation line. A number field rejects booleans and
infinities.

## Blocks

**Every block accepts an optional `span: 1-6`** — its width in content columns, the same column-count
as a `grid` cell. Omit for full width (the default). `span` is width *only*: blocks still stack
vertically one per row regardless — to place several in a single row, use a `grid`. Reach for a
smaller span to hold long-form prose at a readable measure (e.g. `- {type: text, span: 4, body: …}`)
or to keep a small block from stretching across the whole page.

| `type` | Purpose | Key fields |
|---|---|---|
| `heading` | Section structure (feeds the TOC at level 2) | `text`, `level: 2\|3` |
| `text` | Prose paragraph(s) | `body`, `muted?` |
| `list` | Bulleted or numbered points | `style: bullet\|number`, `items[]` |
| `fact_strip` | One-line metadata row | `facts: [{label, value}]` (1–8) |
| `key_value` | Vertical label/value metadata | `pairs: [{label, value}]` |
| `cards` | Headline numbers | `items: [{label, value, of?, tone?, delta?, note?, badges?}]` |
| `badge_row` | A standalone row of chips, flat or grouped | `label?` + `items: [{key} \| {label, tone}]`, OR `groups: [{label, items[]}]` |
| `callout` | "Stop and look" note | `tone: info\|success\|warning\|danger`, `title?`, `body` |
| `status_list` | Checks / steps | `items: [{state: done\|current\|pending\|failed\|blocked, text}]` |
| `meter` | Labelled bars | `items: [{label, value, max, tone?}]` |
| `range` | One bar split by proportional span (see below) | `segments: [{label, span, tone?, sub?}]`, `axis?: {min?, max?}` |
| `table` | The workhorse (see below) | `columns`, `groups`/`rows`, `reconcile?`, `totals?` |
| `code` | Code / logs / diff | `content`, `label?`, `mode: plain\|diff` |
| `quote` | A verbatim quotation | `body`, `cite?` |
| `image` | An embedded image | `src` (a `data:` URI), `alt`, `caption?`, `max_width?` |
| `timeline` | Ordered events | `items: [{title, time?, body?, state?: done\|current\|pending, badges?}]` |
| `flow` | A directional pipeline / process (see below) | `steps: [{label, tone?, note?, points?, badges?}]`, `style: arrow\|steps`, `loop?`, `numbered?` |
| `fan` | One-to-many convergence / divergence (see below) | `hub: {label, tone?, note?, badges?}`, `spokes: [{label, tone?, note?, badges?}]`, `direction: in\|out` |
| `chart` | Bar / line / donut of quantitative data (see below) | `variant: bar\|line\|donut`, `categories`+`series` or `slices`, `stacked?` |
| `comparison` | Option-vs-option feature matrix (see below) | `options[]`, `rows: [{feature, values[]}]`, `highlight?`, `polarity?` |
| `swimlane` | Multi-track process on a lane × column grid, optional milestone groups (see below) | `lanes[]`, `columns[]`, `steps: [{lane, col, n, label, group?}]`, `groups?` |
| `references` | Numbered sources; cite inline with `[^key]` (see below) | `items: [{key, text, url?}]` |
| `section` | Collapsible container | `title`, `collapsed?` (default true), `blocks[]` |
| `grid` | Side-by-side layout (6 columns) | `cells: [{span: 1-6, blocks[]}]` |
| `walkthrough` | Numbered steps, each with a detail column (see below) | `steps: [{label, sub?, tone?, detail: [blocks]}]`, `step_span?` |

Cards: pass `of` to render a derived percentage (`8,500 · 85.0%`). A `value` may be a short
string (e.g. `HEALTHY`) instead of a number. `delta` adds a trend chip beside the value —
`{label, direction?: up|down|flat, tone?}` — where you choose the `tone` (up isn't always
good: for cost or errors, down is, so skaldr won't infer it) and `direction` sets the glyph. Images must be self-contained `data:` URIs — skaldr
embeds images, it does not fetch or generate them; **base64-encode the payload** (a raw,
unencoded SVG isn't a valid URI and won't render). A `section` holds any blocks except another
`section` (one level of nesting only).

Code diff mode: with `mode: diff`, skaldr reads the **first character of each line** — `+` marks an
added line (green), `-` a removed line (red), anything else is context. You write the `+`/`-`
prefixes yourself; skaldr strips the marker, re-labels the line, and tints it — it does **not**
compute a diff. `mode: plain` (the default) renders the content verbatim with no colouring.

```yaml
- type: code
  mode: diff
  label: "dedupe.py"
  content: |
    -  total = sum(scan.count for scan in scans)
    +  total = sum(scan.count for scan in dedupe(scans))
       return total
```

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

Keep running prose out of narrow columns. A paragraph squeezed into a 1–2-span cell reads as a
cramped ribbon; put `text` in a wide cell (or as a full-width block outside the grid), and reserve
narrow spans for cards, meters, short lists, and stats.

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
    - { label: "Reason",  tone: info,    points: ["Weighs index overlap", "Scores by hit-ratio"] }
    - { label: "Propose", tone: accent }
    - { label: "Deliver", tone: success }
```

**Which `style`:**
- `arrow` (default) — short-labelled chips joined by connectors. Reach for it when the flow is the
  *direction itself*: a pipeline, a request path, a state cycle. Keep labels to a word or two.
- `steps` — equal cards that each carry a one-line `note` caption. Reach for it when **every stage
  needs a sentence of explanation** and the labels alone aren't enough.

Beyond the one-line `note`, a step may carry `points` — a few detail bullets under the node, for
when one line isn't enough. Best paired with `style: steps` (a bullet list crowds a compact arrow
chip). Rule of thumb: if most nodes have a `note`, use `style: steps`; otherwise `arrow`. A flow with more
than ~6 nodes usually reads better as `steps`, or split into two flows. `tone` (any of
`neutral·info·success·warning·danger·accent`) accents a node's border + number — use it to mark the
key stage, not every node. `loop` is for genuine cycles (flag→fix→verify→flag), not linear pipelines.

## The `fan`

A one-to-many shape — several nodes converging into one, or one branching out to several. Reach for
it when the structure is **fan-in / fan-out**, not a linear pipeline (that's `flow`): three source
systems feeding one record, one request dispatched to three services. The `spokes` (the many, 2+)
sit in a dashed well; a single arrow joins them to the `hub` (the one). `direction` sets which way:

```yaml
- type: fan
  direction: in           # in (default): spokes → hub (N→1) | out: hub → spokes (1→N)
  hub: { label: "Student record", tone: accent }
  spokes:
    - { label: "SIS export",  tone: info }
    - { label: "Transcripts", tone: info, note: "nightly batch" }
    - { label: "Registrar",   tone: info }
```

`hub` and `spokes` are flow nodes — each takes `label`, optional `tone`, `note` (rich, one line),
`points` (detail bullets), and `badges`. Use `direction: out` for the reverse (one hub branching to
the spokes).

## The `walkthrough`

A vertical list of numbered steps where **each step needs a whole column of detail beside it** —
a spec broken into tickets, a runbook, a migration plan. Each step is a big numbered title on the
left with its full detail (a nested block list: paragraphs, lists, code, callouts, tables) on the
right, aligned row by row. Reach for it when a `flow` (short labels) or `list` (one line each) is
too thin for the explanation each step carries.

```yaml
- type: walkthrough
  step_span: 2            # width of the title column in 6ths (default 2 → detail gets 4)
  steps:
    - label: "Parse the spec and pull every acceptance criterion"
      sub: "the source of truth"        # optional one-line sub-label
      tone: info                        # optional — draws a subtle accent on the step's edge
      detail:                           # a nested block list, like a grid cell
        - { type: text, body: "Group the criteria by surface; two rules are load-bearing." }
        - { type: list, items: ["exactly-one-default per registry", "the reconcile invariant"] }
    - label: "Slice into shippable tickets"
      detail:
        - { type: code, label: "dedupe key", content: "key = (school_id, course_key)" }
```

`detail` holds the same blocks you'd put anywhere else (it can be long — that's the point). The
step numbers are derived (1..n). Use `tone` to mark a key step. Distinct from `flow` (a directional
pipeline) and `grid` (no row-by-row step alignment).

## The `range`

One horizontal bar cut into `segments` whose widths are **proportional to their `span`** — for a
numeric extent that a `meter` (a single value/max ratio), `chart`, or `flow` (equal chips) can't show:
a date window, a coverage span, a before/after split. Spans are normalised, so only the ratios matter
(`[3, 1]` and `[30, 10]` are identical). Each segment carries a soft-tint `tone` and an optional `sub`
line; an optional `axis` labels the extent's ends.

```yaml
- type: range
  axis: { min: "2015", max: "2025" }      # optional end-cap labels; either end may be omitted
  segments:
    - { label: "Transferable", span: 7, tone: success, sub: "full credit" }
    - { label: "Review", span: 2, tone: warning }
    - { label: "Expired", span: 1, tone: danger }
```

Reach for it when the **relative size of spans** is the message. For a single ratio use `meter`; for a
trend or distribution use `chart`; for an ordered set of stages use `flow`.

## The `chart`

Render-time SVG — self-contained, no JS. You give the data; skaldr computes the scale, ticks,
gridlines, smoothed curves, and arcs, plus a legend whose swatches match the series. Reach for a
chart when a number's **shape** is the point (a trend, a spread, a share); use `cards` for standalone
figures and `meter` for a single ratio.

- **`bar`** — compare a value across categories. Extra `series` group side by side, or `stacked: true`.
- **`line`** — a trend across an ordered axis (smoothed); a lone series gets a soft area fill.
- **`donut`** — parts of a whole; the shares are derived.

`bar`/`line` take `categories` (the x-axis) and `series` (each `{label, values, tone?}` — one value
per category); `donut` takes `slices` (each `{label, value, tone?}`). `tone` is optional — skaldr
colours any unset series/slice from the palette so they stay distinct.

```yaml
- type: chart
  variant: bar
  title: "Imports vs failures by quarter"
  categories: [Q1, Q2, Q3, Q4]
  series:
    - { label: Imported, tone: success, values: [820, 910, 760, 980] }
    - { label: Failed,   tone: danger,  values: [40, 25, 60, 30] }

- type: chart
  variant: donut
  slices:
    - { label: Accepted, tone: success, value: 2160 }
    - { label: Held,     tone: warning, value: 900 }
    - { label: Rejected, tone: danger,  value: 420 }
```

## The `comparison`

A feature matrix — the `options` you're weighing across the top, each `feature` down the side. One
column can be `highlight`ed (0-based) as the recommended pick. Each row's `values` give one cell per
option, in order: a bare `true`/`false` renders ✓/✗, a bare string renders as text, and
`{value, tone}` renders toned text. (YAML also reads bare `yes`/`no`/`on`/`off` as booleans — quote
them (`"yes"`) if you mean the literal word, not a ✓/✗.) Reach for it to weigh a few named options against shared
criteria; for freeform tabular data use `table`.

By default a ✓ reads good (green) and a ✗ reads bad (red). Set `polarity` — one `positive`/`negative`
entry per option — to flip that per column: in a `negative` column a present-is-bad attribute (e.g.
"leaks disk layout") shows a true ✓ in red and a false ✗ in green. The glyph still marks
present/absent; only the colour flips, and only on bool cells.

```yaml
- type: comparison
  options: ["Hand-built HTML", "skaldr"]
  highlight: 1
  polarity: ["positive", "positive"]   # optional; omit for all-positive
  rows:
    - { feature: "Self-contained", values: [true, true] }
    - { feature: "Validated", values: [false, true] }
    - { feature: "Effort", values: [{ value: "high", tone: danger }, { value: "low", tone: success }] }
```

## The `swimlane`

A process laid on a grid: `lanes` are the rows (teams, systems, roles) and `columns` are the axis
across the top (sprints, phases, weeks). Each step sits in one `lane`/`col` cell. Reach for it when
**who does what, when** is the message and a single-track `flow` can't show the hand-offs. Both
`lanes` and `columns` are declared up front, ordered, and unique; up to **8 lanes** (more rows stop
reading as a matrix — split into two swimlanes). Every declared lane and column must carry at least
one step (no empty rows or columns).

Step fields are explicit — skaldr never derives or renumbers: `lane` (one of `lanes`), `col` (one of
`columns`), `n` (the number shown, a free string — `"1"`, `"3a"`, `"R1"`), and `label`. Two steps in
the same cell stack.

```yaml
- type: swimlane
  lanes: ["Product", "Eng", "QA"]
  columns: ["Sprint 1", "Sprint 2", "Sprint 3"]
  steps:
    - { lane: "Product", col: "Sprint 1", n: "1", label: "Spec" }
    - { lane: "Eng", col: "Sprint 2", n: "2", label: "Build" }
    - { lane: "Eng", col: "Sprint 3", n: "3a", label: "Feature flag" }   # stacks with 3b (same cell)
    - { lane: "Eng", col: "Sprint 3", n: "3b", label: "Test plan" }
    - { lane: "QA", col: "Sprint 3", n: "4", label: "Regression" }
```

### Optional group (milestone) overlay

Add `groups` to overlay milestones/deliveries: each group has an author-chosen `color` and a
**contiguous** run of `columns`, drawn as a coloured cap poking above and below the table plus a faint
cell tint. Inside the table stays a plain grey grid — solid lines between columns, a dashed line where
a column is split between groups. Omit `groups` entirely for a plain swimlane.

A column may be split across **several** groups (e.g. two deliveries inside one sprint). When a step's
`col` is covered by more than one group, name its `group`; when the column has one group (or none),
`group` is inferred and can be left off. Every declared group must carry at least one step.

```yaml
- type: swimlane
  lanes: ["Robin", "Sam"]
  columns: ["Sprint 1", "Sprint 2", "Sprint 3"]
  groups:
    - { name: "MVP demo", color: blue,   columns: ["Sprint 1", "Sprint 2"] }
    - { name: "Beta",     color: amber,  columns: ["Sprint 2"] }
    - { name: "GA",       color: violet, columns: ["Sprint 2", "Sprint 3"] }   # Sprint 2 is 3-way split
  steps:
    - { lane: "Robin", col: "Sprint 1", n: "101", label: "auth service" }      # group inferred (one group)
    - { lane: "Robin", col: "Sprint 2", group: "Beta", n: "104", label: "beta gate" }   # split → name it
    - { lane: "Robin", col: "Sprint 3", n: "106", label: "store submit" }
    - { lane: "Sam",   col: "Sprint 1", n: "110", label: "onboarding UI" }
    - { lane: "Sam",   col: "Sprint 2", group: "MVP demo", n: "111", label: "profile screen" }
    - { lane: "Sam",   col: "Sprint 2", group: "GA", n: "113", label: "error states" }
```

Groups must **nest, not interleave**: because a group's cap spans its columns as one contiguous band,
a group that spans past a column cannot also share that column with another group (skaldr rejects the
layout). Columns are fixed-width and the block scrolls horizontally when wide, so a long row of columns
stays a grid rather than reflowing (and fits the page when printed).

## The `references`

Numbered sources with inline citations. Drop a `references` block wherever the list should render;
anywhere in rich text, `[^key]` becomes a superscript number linking to that source — and the number
in the list links back to the citation. Numbering is by first appearance across every `references`
block, so the same `[^key]` always carries the same number. Keys are ASCII `[A-Za-z0-9_-]+` and must
be unique across the whole page (an unknown key stays literal so a typo shows). Put the `references`
block after the prose that cites it, so each source gets a backlink to its citation. Reach for it
when prose needs to cite sources; for a bare link inside a sentence use a `[text](url)` markdown
link instead.

```yaml
- type: text
  body: "Thresholds come from the Q2 audit [^audit]; method from the SOP [^sop]."
- type: references
  items:
    - { key: audit, text: "Q2 Reconciliation Audit, p. 12.", url: "https://example.com/audit" }
    - { key: sop, text: "*Counting SOP*, rev. 7." }   # text is rich; url is optional
```

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
