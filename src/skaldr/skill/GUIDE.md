# skaldr: authoring guide

The current, version-matched authoring contract, printed by `skaldr --guide`. A skaldr report is
**one YAML file**: you describe *what* it says; skaldr owns *how* it looks. For exact field names,
types, and constraints, also run `skaldr --write-schema <path>` (the machine-readable JSON Schema,
generated from the same models).

`skaldr --guide` prints this whole guide. `skaldr --guide <name>` prints one part of it. A block name (for example `skaldr --guide request`) prints that block's row from the `## Blocks` table, its `## The <block>` section when the guide has one, and its fields from the model with their types, whether each is required or its default, and its description; a field that holds a nested model also lists that model's fields, one level deep, indented. A section title (for example `skaldr --guide "rich text"`) prints that whole section; the match ignores case and backticks, so `meta` finds `` `meta` ``, and a unique start of a title is enough. When no title starts with the name, a unique start of one word in a title is enough, so `skaldr --guide plan` prints the working plan starter. A block name wins when a section has the same title. `skaldr --guide --list` prints the guide's section names and the block names, one per line, so you can see what to ask for. A name that is neither fails with an error that lists the block names and the section titles. A name that is both a block or section and a file in the current directory is looked up as the block or section.

## Shape

```yaml
version: 1          # required, integer
meta: { ... }       # page header + options
badges: { ... }     # optional: your tag/status vocabulary
blocks: [ ... ]     # the ordered content
index: { ... }      # optional: build one page from other documents (see Index documents)
publish: { ... }    # optional: where the document publishes (see below)
```

Top level is `version`, `meta`, `blocks`, and optional `badges`, `index` and `publish` (see *Index
documents* and *Where it publishes* below), nothing else. Every block is a mapping with a `type` discriminator.
**Validation is strict:** an unknown block type, a field that doesn't belong to that block, an
unknown top-level key, or a value of the wrong shape each fails the build with a precise path,
e.g. `error: invalid content data: blocks.3.items.2.value: number column needs a numeric value`.
Text holding a lone surrogate, which only a YAML escape such as `"\ud800"` can produce and no page
can hold, fails the same way with its path. A failed reconciliation is listed with the other block errors in the file. A page-wide check (an
undeclared badge key, a repeated table, matrix, reference or heading id) runs once every block is
valid and names each place involved after `at`. Run `skaldr --check <file>` to validate without
rendering; read the path, fix, re-run. When the document has a `publish` block and the publish extra
is installed, `--check` also drafts each target the block names the way `skaldr publish` does, without
signing in or sending anything, so it refuses what that publish would refuse: a block the target
cannot show (a Jira target is drafted as `adf` and a Notion target as `notion`, each item over the
sections it is built from) and an item over the service's size limit. For each target you name with
`--for`, `--check` runs that whole export in memory and writes nothing, so it refuses exactly what
`--export <target>` refuses, including a limit measured on the written export, such as the Slack
canvas size: `skaldr --check --for slack --for adf plan.yaml` fails with the block's path, why the
target cannot show it and what to write instead. Add an output flag and the check becomes a gate on that
render: `skaldr --check --strict plan.yaml -o plan.html --if-stale` validates and writes in one
invocation, and writes nothing at all if the check fails.

**Values are never coerced.** A number field takes a YAML number, so `value: '5'` and `start: '4'`
fail where `value: 5` and `start: 4` pass. A whole-number field such as `span` or `start` takes an
integer, not `2.0`; a field that takes decimals also takes an integer. A true/false field takes
`true` or `false` (YAML also reads a bare `yes` or `no` as one), not a quoted `'no'` or a `1`. YAML
reads `1e3` and `1e+3` as text, because its float form needs a dot and a signed exponent, so write
`1000` or `1.0e+3` in a number field. The JSON Schema from `--write-schema` is looser than the build
in one place: it accepts an integral float such as `span: 2.0` where the build wants `2`.

A heading's text, a section, panel or toggle title, a tab label, a list point, and the other names
and labels the schema marks with `pattern: \S` must hold visible text. An empty one fails the build
at its path with `String should have at least 1 character`, and a whitespace-only one with `String
should match pattern '\S'`. To leave an optional one empty, leave the field out.

`--if-stale` renders only when the page is missing, is older than the content file or any file it pulls in with `!include`, or was written with different `--embed`, `--no-source` or `--live` options or by another version of skaldr. A page it cannot read its options from, and content it cannot load, count as stale too, so the render runs and reports the problem. Without `--live` it keeps the reloader of a page that was rendered with `--live`, at the same interval, so rendering once with `--live` and then running `--if-stale` after every edit keeps the open tab refreshing. To drop the reloader, render once without `--if-stale`.

A flag the command would ignore is refused with a usage error instead: `--if-stale` with `--watch`, `--no-source` when no HTML page is written (with `--check` or `--pdf` alone, or with `--emit-json`), and any other flag or a content file next to `--write-schema`, `--extract-source`, `--guide`, `--install-skill` or `--install-plan-rule`, each of which runs on its own. The one flag `--guide` accepts is `--list`, which only works with a bare `--guide`.

The files skaldr writes itself (the page, an export, the schema, an installed skill, the plan rule in `CLAUDE.md`) are written to a temporary file next to the file and then swapped into place, so a failed write leaves the earlier file as it was. A path that is a symlink gets the new text in its target and stays a link, a missing folder on the way to that target is created, and an existing file keeps its permissions. A read-only file is refused with an error naming it and left as it is. A file with more than one hard link, or a file in a folder you cannot write to, is rewritten in place instead, so every name for it sees the new text; if that write fails partway, such as on a full disk, the earlier bytes are written back. The staged file and its folder are flushed to disk around the swap. The `--pdf` file follows the same rules: the headless browser prints into a temporary folder and skaldr swaps the finished PDF into place, so a browser that fails leaves an earlier PDF as it was.

## `meta`

```yaml
meta:
  title: "Q3 Warehouse Inventory Count: Discrepancies & Fixes"    # required
  subtitle: ["one line", "another"]                    # optional
  source: "WMS export"           # optional; shown in the provenance footer, rich text (`code`, links)
  date: "Q3 2026"                # optional; footer. Author it: skaldr never inserts "now"
  updated: "18 Jul 2026"         # optional; footer "updated <value>", a living-doc freshness stamp
  toc: true                      # optional; auto table-of-contents from level-2 headings + sections
  hero: true                     # optional; a larger display title + subtitle in a tinted band
  notion_width: full             # optional; normal (default) or full: the Notion page width tables are sized for
  people:                        # optional; who a [Ada](user:ada) link can name (see Rich text)
    ada: { notion: "user://11111111-2222-3333-4444-555555555555", jira: "5b10a2844c20165700ede21g", slack: "U0EXAMPLE1" }
  jira_site: "https://example.atlassian.net"   # optional; where a [ABC-123](jira:ABC-123) link points
  icon: "🧪"                     # optional; one emoji beside the title and as the favicon
  cover: "https://example.com/cover.png"   # optional; an http or https image address
```

`source` is rich text, so `*`, backticks, `[label](url)` and `[^key]` in it are read as marks, code, links and citations (escape a literal one with a backslash), and a link to an unknown `#anchor` fails the build naming `meta.source`. The footer renders after the page's `references` block, so a reference cited only from `source` gets no back-link. The footer's date, updated stamp and reconcile lines stay plain text.

`hero` opts the page into a bolder opening (a large display title and subtitle in a tinted band)
for a page that leads by selling an idea (a proposal, an explainer) rather than a plain report header.

`icon` is one emoji. The page shows it beside the title and uses it as the favicon, and the GitHub-flavored export leads the title with it. `cover` is an `http://` or `https://` address. The page allows no remote images, so it shows a "Cover image" link under the title instead of the image, and the GitHub-flavored export writes the same link under the title. Neither reaches the Notion export's Markdown, which holds only the body. A Notion publish sets them on the page itself, as the page icon and cover (see Publishing to Notion).

Page **width is not an authoring choice**: every page renders at the default cap, and the reader
alone widens it (default / wide / full) from the corner menu on the rendered page. There is no
`meta.width`; don't set one (it fails the build). `notion_width` touches only the Notion export: see Exporting as Markdown.

The browser remembers the reader's width and theme across reloads and pages. A stored value the page does not know, such as one left by another version, is ignored and removed.

## `badges`: your vocabulary

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
automatically before the first table; you don't author it. Set a badge's `legend: false` to keep it
**out** of that legend, for a one-off inline chip that needs no explanation.

Badge colours: `slate · blue · green · amber · red · violet · teal · sky`.

A standalone `badge_row` is either **flat** (`items:`, an optional leading `label` then chips) or
**grouped** (`groups: [{label, items}]`, where each group renders as a labelled gutter row, the labels
aligned in a column like `key_value`). Use one or the other, not both. Reach for `groups` when a dense
set of chips reads better split into a few titled rows.

```yaml
- type: badge_row
  groups:
    - { label: "Severity", items: [{ key: HIGH }, { key: LOW }] }
    - { label: "Area", items: [{ label: "API", tone: blue }, { label: "UI", tone: violet }] }
```

## Colours & tones: one palette, two names

Every `tone:` (on cards, flows, fans, meters, walkthroughs, chart series, comparison cells, …) and every
badge colour names the **same eight colours**. Six of them have two interchangeable names (a *semantic*
name and a *palette* name), and `teal`/`sky` have a palette name only:

`neutral` = `slate` · `info` = `blue` · `success` = `green` · `warning` = `amber` · `danger` = `red` · `accent` = `violet` · `teal` · `sky`

Write whichever reads best: `tone: success` and `tone: green` are identical, and a badge `tone: info` is the
same as `tone: blue`. (`callout` is narrower: it maps only to the four semantic tones info/success/warning/danger;
their palette aliases blue/green/amber/red work too, but accent/neutral/teal/sky don't.) The generated JSON
schema lists the canonical names; the alias names still validate at build even if an editor flags them.

## Rich text

Prose fields (`text.body`, table `rich`/`text` cells, `callout.body`, list items, `quote.body`,
`key_value` values, timeline/status text) accept a small markdown subset:

`**bold**` · `*italic*` · `++underline++` · `` `code` `` · `~~strike~~` · `H~2~O` (subscript) · `10^3^` (superscript) · `` $`x_i`$ `` (inline math) · `[label](https://url)`
(links allow `http`, `https`, `mailto` and the typed links below only).

**CommonMark rules.** Rich text follows CommonMark's inline rules (it is parsed with markdown-it-py) for emphasis, code spans, links and backslash escapes, plus the extensions this section lists: underline, subscript, superscript, coloured spans, inline math, `[^key]` citations and `{{name}}` blanks. So marks nest (`**bold with *italic* inside**`), a link label holds marks (`[**docs** H~2~O](https://url)`), and a link URL may hold balanced parentheses (`https://en.wikipedia.org/wiki/Foo_(bar)`). A link needs both text and a URL and takes no title, so `[x]()`, `[](https://url)` and `[x](https://url "title")` show as typed. A marker opens or closes only where CommonMark's flanking rules allow it: `2 * 3 * 4` and `a ** b ** c` stay prose, and so does ``the **`api`**s``, because a closing `**` between punctuation and a letter closes nothing. `_word_` is italic and `__word__` bold, as on GitHub, while an underscore inside a word (`snake_case`, `a__init__b`) stays text; write an identifier such as `__init__` in a `` `code` `` span. A backslash before any ASCII punctuation shows that character literally and drops the backslash (`\*`, `\~`, `\[`); a backslash before a letter stays. Multi-backtick code spans (``` `` a`b `` ```) work. Raw HTML, autolinks (`<https://url>`), images, entity references (`&amp;`) and hard line breaks are not read: they show as typed. A NUL character becomes U+FFFD, as CommonMark requires. Marks, links and coloured spans nest up to 20 deep; more than that fails the build naming the limit. A rich-text mistake that fails the build names the field it sits in, as in `blocks.1.items.2: unknown tone 'purple' in {tone=purple}: …`.

**Underline, subscript and superscript.** `++underline++` follows the flanking rule CommonMark gives `_`: a `++` opens only where no letter or digit runs into it from the left and closes only where none follows it, so `C++`, `i++`, `a ++ b ++ c`, `x++y++` and `++x++y` stay prose. Two increments in one paragraph, like `++i over i++`, do read as an underline of `i over i`, since nothing tells them apart from one; put code in backticks (`` `++i` ``) and it stays code. Subscript `~…~` and superscript `^…^` follow Pandoc: the marked text holds no spaces, so `about ~5 days` and `cut from ~5 days~ to 2` stay prose, and `~~strike~~` is still a strike. The marked text holds only letters, digits and `+ - − = ( ) . , ' ′ *`, as in `H~2~O`, `10^3^`, `e^-i^` and `x~i,j~`, so paths, URLs, regexes and `~5%~` stay prose (`~/code,~/notes`, `http://host/~alice/x~bob`, `(^|[^\p{L}])`), and a `~` or `^` after a backslash is an escaped character that opens nothing (`C:\~tmp~` shows as `C:~tmp~`). A script that holds a `+` or `=` and is followed at once by a letter or digit is prose, so `x^2+y^2=z^2` stays as typed while `Ca^2+^` and `x^n+1^.` are scripts. Any other tilde pair around a short word reads as a subscript, `a~b~c` included, since nothing tells it from `H~2~O`; write `a\~b\~c` to keep the tildes. The marked text is plain text; no other mark goes inside a subscript or a superscript.

**Colour and highlight.** `[text]{tone=danger}` colours the text, `[text]{bg=warning}` highlights it, and `[text]{tone=danger bg=warning}` does both. The braces hold space-separated `key=value` attributes in either order, `tone` and `bg` at most once each, and each value is a tone or its palette name (see Colours & tones above). The bracketed text follows the rules of a link label: it may hold other marks, citations, blanks and balanced brackets (`[a [b] c]{tone=info}`), but not a link; a link inside, an empty `[]`, or a `]{tone=…}` with no opening `[` fails the build naming the attribute list. A span inside a link label works: `[[docs]{tone=info}](https://url)` is a link whose label is coloured. Braces right after `]` that hold `tone=` or `bg=` and no other brace are an attribute list, and its text is read exactly as written, so an unknown tone, an unknown attribute next to them, a repeated attribute, a space on either side of `=` (`{tone = info}`, `{tone= info}`), or anything that is not `key=value`, such as a code span, math or a citation inside the braces, fails the build naming that attribute. Anything else, like `arr[i]{n=3}`, `[a]{x=1}` or `[a] {tone=info}`, stays prose, and `[label](https://url)` is still a link, since nothing inside a link's URL is read as a span.

**Math.** A single-backtick `` `code` `` span wrapped in dollars, `` $`\frac{a}{b}`$ ``, is inline LaTeX math (the expression holds no backtick, so `` $`x` and `y`$ `` is two code spans between dollars, and `` $` `$ `` fails the build as empty), and a `math` block (`{type: math, expression: '\sum_{i=1}^{n} x_i'}`) is display math on its own line. skaldr converts both to MathML when the page builds, so the page needs no script or font to show them. An expression the converter cannot read fails the build naming it, and so do an unknown command (a typo like `\simga`, a misspelt font like `\mathbbb{R}`, a command latex2mathml lacks like `\mathcolor`, or a backslash before a character no command uses, like `\<`), a fraction, stack, root or script missing a part (`\frac{a}`, `\overset{a}`, `\displaystyle_a`), an environment latex2mathml does not define (`aligned`, `equation`, or a typo like `pmatrx`; `matrix`, `pmatrix`, `bmatrix`, `cases`, `array`, `split` and `align` are defined), a colour that CSS Color Level 4 does not parse, or that holds a CSS comment or an unclosed parenthesis (`\color{simga}`; a name like `red` or `rebeccapurple`, `transparent`, `currentColor`, a hex value like `#f00`, `#ff0000` or `#ff000080`, and a function like `rgb(255,0,0)`, `hsl(0 100% 50%)` or `oklch(0.6 0.2 30)` are all colours in `\color` and `\textcolor`; `\colorbox` and `\fcolorbox` drop the spaces, and everything after a `%`, from their colours, so give those two a name, a hex value, or the comma form `rgb(255,0,0)`), a command that sets an attribute MathML has no use for (`\href`, `\class`, `\style`), and `$$`, which would end the Notion export's equation early (write `\$\$` for literal dollars). A backslash inside `\text{…}` is literal text. An entity typed there shows as typed when it is a named entity (`&lt;`), a decimal one (`&#60;`), a hex one with a capital X (`&#X3C;`), or a hex one without its closing semicolon (`&#x3C`). A hex entity written `&#x3C;` decodes to its character, as `\unicode{x3C}` does, and shows as U+FFFD instead when its code point is past U+10FFFF, a surrogate (U+D800 to U+DFFF), a control character other than tab and newline (U+0000 to U+001F and U+007F to U+009F), or a noncharacter (U+FDD0 to U+FDEF, or one ending in FFFE or FFFF such as U+FFFE or U+10FFFF). A lone `$` in prose, like `costs $5`, stays text. In YAML, single-quote an expression so its backslashes reach skaldr unchanged.

**Same-page anchor links.** `[label](#slug)` jumps to a heading or section on the same page. The
`slug` is the heading text lowercased with every run of characters that are not letters, digits or
combining marks turned to `-` (so `## Count pipeline` → `#count-pipeline`, and `## Über uns` →
`#über-uns`; letters, digits and marks from any script are kept); duplicates get a `-2` suffix,
matching the TOC. A slug that would equal an id the page itself uses (`skaldr-source`, `sc-menu`, or
`ref-<key>` and `fnref-<key>` for a reference key) gets the suffix too, and an author `id` equal to
one fails the build. A `#slug` that names no heading or section **fails the build**, so a dangling
in-page link never ships. The GitHub-flavored export keeps the link; the Notion, ADF and Slack
exports refuse a document holding one you wrote, since none of them can link to its own headings.

**Typed links.** Four more link targets name a date, a person, an issue or another document instead of a URL. `[1 Oct](date:2026-10-01)` is a date chip, and a range is `[the week](date:2026-10-05/2026-10-09)`; a date is `YYYY-MM-DD`, a range holds two dates and its end is not before its start, and anything else fails the build naming the value. `[Ada](user:ada)` is a person chip: `ada` must be a key under `meta.people`, a map from a key (letters, digits, `_` and `-`) to `notion` (a `user://` id), `jira` (an account id) and `slack` (a member id: `U` then capital letters and digits, such as `U0EXAMPLE1`), all optional, and a key missing from the map fails the build naming it. `[ABC-123](jira:ABC-123)` is an issue link to `<meta.jira_site>/browse/ABC-123`, where `jira_site` is your `https://` Jira address with no username, password, query or fragment (a path is allowed, and a trailing slash is dropped); without `jira_site` the label shows as text, because the key alone names no site. The key is capitals, a hyphen and a number. `[the plan](doc:onboarding-plan#st2)` links to another skaldr document by its `doc_id`, with an optional `#section` id; the HTML page links to `onboarding-plan.html#st2` and the GitHub Markdown to `onboarding-plan.md`, which work when the files sit side by side under those names. The GitHub link drops the section, because GitHub makes a heading's anchor from its title and never from a section `id`. When an index document includes the part whose `publish.doc_id` is that document, the link is an in-page link to the section, or to the part's title when there is no `#section`, in the HTML page and the GitHub-flavored export; the Notion, ADF and Slack exports refuse it, since none of them can link to its own headings. Only that part's own sections (blocks with a `section` `id`) can be named: a heading, or a section of another part, fails the build, since the link would break once the parts publish separately. Two parts with the same `publish.doc_id` fail the build naming both files. Every label is rich text, and a typed link inside a flow label or other plain-text field reads as its label. Exports: see Exporting as Markdown.

**Link to the real thing.** When you cite a ticket, PR, doc, dashboard, or page, use its actual URL,
never a bare `#` or `https://example.com` placeholder (a `#`-only href is not a valid anchor and
fails). (skaldr's own bundled examples use fictional links on purpose because they ship publicly;
that's the exception, not a pattern to copy into a real report.)

Everything else is escaped and shown literally: there is no raw HTML.

**Multi-paragraph fields.** A blank line starts a new paragraph in the **set-apart prose** bodies:
`text.body`, `callout.body`, `quote.body`, `note.body`, `def_list` item bodies, and `text`/`rich`
table cells. Every other prose field (`key_value` values, `list` items, `status_list`/`timeline`
text, headings, labels) is single-line: a blank line there is just collapsed whitespace.

**Lists inside a body.** In those same set-apart bodies, lines that start with `- `, `* `, `+ ` or a number and `. ` or `) ` (`1. `, `2) `) are a list, read with CommonMark's list rules (the same as GitHub): bulleted for `-`, `*` and `+`, numbered from the first item's number otherwise, and an item indented under another item is a nested list, up to 20 levels deep (deeper fails the build naming the field). A bulleted list, or a numbered one that starts at 1, can follow a line of text directly (`Two checks:` on the line above needs no blank line); a numbered list that starts at another number needs a blank line above it. A line right after an item continues that item, so leave a blank line before text that follows a list. A change of marker (`-` to `*`, `.` to `)`) starts a new list, and `\-` at the start of a line is a literal dash. skaldr adds one rule of its own: a list needs at least two items at the top level, so a single marked line stays text exactly as written, and `2024. was the year` or a lone `- note` is never a list.

> **YAML gotcha:** a folded `>` block scalar turns blank lines into spaces *before skaldr sees them*,
> so paragraphs are lost. Use a literal `|` block scalar for any multi-paragraph body:
> ```yaml
> - type: callout
>   tone: info
>   body: |
>     First paragraph.
>
>     Second paragraph.
> ```

## Placeholders: fill-me-later blanks

For a rehearse-then-finalize doc (a demo runbook whose real URL/ticket doesn't exist yet), write a
blank as `{{name}}` in any prose field. It renders as a loud `‹name›` chip so it can't ship
unnoticed, and there's no separate to-fill list to keep in sync. Fill it by replacing the token with
the real text.

A placeholder **name is letters, digits, `_` or `-`** (`{{next-round}}` is fine; `{{a.b}}` or
`{{two words}}` is not). `{{ … }}` is reserved for this: a token whose name breaks the rule is a
**hard build error** naming it, never silently emitted as prose (that would defeat the whole point).
To show a literal `{{`, put it in a `` `code` `` span. A blank inside a link label stays a blank
(`[ticket {{ticket}}](https://url)`). A link whose URL holds a blank is not a link: it shows as
bracket text around the blank's chip, so `[the PR](https://host/pull/{{pr}})` is counted like any
other blank until you fill in the URL.

A blank in the page's `meta` title, subtitle lines, `date` or `updated` counts too, even though those fields are plain text and show the `{{name}}` as written.

- `skaldr --check file.yaml` reports the count (`… (2 placeholders unfilled: ticket, url)`) but still passes.
- `skaldr --check --strict file.yaml` **fails** while any blank remains, which makes it the gate
  you run before "final".

> **Self-checking a rendered page?** Every render, full page and `--embed` fragment alike, **embeds its
> own YAML source** (so `--extract-source` can recover it), which means any `{{…}}` or `[^ref]` in the
> source also appears in the output. Grepping the HTML for unfilled markers therefore needs
> `skaldr … --no-source`; better yet, run `skaldr --check --strict` and let skaldr do it.

## Working plan starter

`skaldr new plan plan.yaml` writes this file for you: copy it, replace each `{{placeholder}}` with real content, delete what the plan does not need, and run `skaldr --check --strict plan.yaml` until nothing is unfilled.

Keep the plan file next to the work it tracks; in a public repository keep it out of git or in a private folder. After each edit run `skaldr plan.yaml -o plan.html --if-stale`, keep the Working state section current, and re-read the file after a context reset.

```yaml
version: 1
meta:
  title: "{{plan-title}}"
  subtitle: ["{{one-line-summary}}"]
  updated: "{{date}}"

blocks:
  - { type: heading, text: "Intent" }
  - type: callout
    tone: info
    title: "Done looks like"
    body: "{{what-done-looks-like-and-why-it-matters}}"

  - { type: heading, text: "Constraints and decisions" }
  - type: list
    items:
      - "{{decision-one}}, because {{reason-one}}"
      - "{{decision-two}}, because {{reason-two}}"

  - { type: heading, text: "Working state" }
  - type: status_list
    items:
      - { state: done, text: "{{finished-step}}" }
      - { state: current, text: "{{step-in-progress}}" }
      - { state: pending, text: "{{step-not-started}}" }
      - { state: blocked, text: "{{step-waiting-on-something}}" }

  - { type: heading, text: "Next" }
  - type: list
    style: number
    items:
      - "{{first-action}}"
      - "{{second-action}}"

  - { type: heading, text: "Pitfalls" }
  - type: list
    items:
      - "{{mistake-to-avoid}}"

  - { type: heading, text: "Open questions" }
  - type: callout
    tone: info
    title: "Open questions and blockers"
    body: 'List each open question and blocker here, or write "none".'
```

## Numbers are formatted for you

Write raw numbers (`8500`, not `"8,500"`). skaldr adds thousands separators, computes
percentages, subtotals, and the reconciliation line. A number field, a table `number` cell and a
subrow value reject booleans, infinities, and anything beyond 1e300 in either direction, so the sums
and chart axes skaldr derives always stay finite.

## Blocks

**Every block accepts an optional `span: 1-6`**: its width in content columns, the same column-count
as a `grid` cell. Omit for full width (the default). `span` is width *only*: blocks still stack
vertically one per row regardless; to place several in a single row, use a `grid`. Reach for a
smaller span to hold long-form prose at a readable measure (e.g. `- {type: text, span: 4, body: …}`)
or to keep a small block from stretching across the whole page.

| `type` | Purpose | Key fields |
|---|---|---|
| `heading` | Section structure (feeds the TOC at level 2; levels 3 and 4 get an anchor but no TOC entry) | `text`, `level?: 2\|3\|4` (default 2), `id?` (stable anchor), `sub?` (subordinate caption line) |
| `text` | Prose paragraph(s) | `body`, `muted?` |
| `list` | Bulleted, numbered, checkbox, or decision points (nestable) | `style: bullet\|number\|check\|decision`, `items[]`: each item a string or `{text, items:[…]}` to nest (≤4 deep); in a `check` list an item may set `checked: true`; in a `decision` list an item sets `decided: true` for a decision taken and leaves it out for an open question; a `number` list takes `start?` (the first number, 1 to 999999999, default 1) and `numbering?: decimal\|letters\|roman` |
| `fact_strip` | One-line metadata row | `facts: [{label, value}]` (1 to 8) |
| `key_value` | Vertical label/value metadata | `pairs: [{label, value}]` |
| `def_list` | Labelled list: prominent term + rich body (e.g. Action/Expected/Say) | `items: [{term, body}]` |
| `cards` | Headline numbers (a value may be author-set, or **derived** by counting a matrix / tables) | `items: [{label, value, of?, tone?, delta?, note?, badges?}]` OR a derived item `{badge, of_matrix \| of_tables, label?, tone?, note?}` |
| `badge_row` | A standalone row of chips, flat or grouped | `label?` + `items: [{key} \| {label, tone}]`, OR `groups: [{label, items[]}]` |
| `callout` | "Stop and look" note | `tone: info\|success\|warning\|danger`, `title?`, `body`, `icon?` (one emoji, e.g. `"🚧"`) |
| `status_list` | Checks / steps | `items: [{state: done\|current\|pending\|failed\|blocked, text}]` |
| `meter` | Labelled bars | `items: [{label, value, max, tone?}]` |
| `range` | One bar split by proportional span (see below) | `segments: [{label, span, tone?, sub?}]`, `axis?: {min?, max?}` |
| `table` | The workhorse (see below) | `columns` (each `{key, label, kind?, width?, tone?}`), `groups`/`rows`, `reconcile?`, `totals?`, `rollup?`, `tint_by?`, `id?` (for `of_tables`) |
| `code` | Code / logs / diff | `content`, `label?`, `mode: plain\|diff`, `lang?` |
| `math` | A display equation, written in LaTeX and rendered as MathML | `expression` |
| `quote` | A verbatim quotation | `body`, `cite?` |
| `note` | A quiet set-apart aside (speaker notes, narration), softer than a `callout` | `body`, `title?`, `icon?` (one emoji) |
| `divider` | A horizontal rule that separates the blocks before it from the blocks after it | none: write `- type: divider` |
| `image` | An image: embedded, or named by URL (see below) | `src` (a `data:` URI or an http(s) URL), `alt` (required), `caption?`, `max_width?` |
| `media` | A video, audio, file or PDF named by URL (see below) | `kind: video\|audio\|file\|pdf`, `src` (an http(s) URL), `caption?` |
| `link` | A link to another page, as a plain link, a card or an embed (see below) | `url` (http or https), `display?: inline\|card\|embed` (default `card`), `title?`, `caption?` (not on `inline`) |
| `timeline` | Ordered events | `items: [{title, time?, body?, state?: done\|current\|pending, badges?}]` |
| `flow` | A directional pipeline / process (see below) | `steps: [{label, tone?, note?, points?, badges?}]`, `style: arrow\|steps`, `loop?`, `numbered?` |
| `fan` | One-to-many convergence / divergence (see below) | `hub: {label, tone?, note?, badges?}`, `spokes: [{label, tone?, note?, badges?}]`, `direction: in\|out` |
| `chart` | Bar / line / donut of quantitative data (see below) | `variant: bar\|line\|donut`, `categories`+`series` or `slices`, `stacked?` |
| `comparison` | Option-vs-option feature matrix (see below) | `options[]`, `rows: [{feature, values[]}]`, `highlight?`, `polarity?` |
| `matrix` | Rows × columns with one state per cell: a coverage / RACI / capability grid (see below) | `rows[]`, `columns[]`, `cells: [{row, col, badge? \| tone?, label?}]`, `id?` (for `of_matrix`) |
| `swimlane` | Multi-track process on a lane × column grid, optional milestone groups + value rollups (see below) | `lanes[]`, `columns[]`, `steps: [{lane, col, n, label, group?, value?, url?, state?: done\|current\|todo\|blocked\|deferred, id?, depends_on?}]`, `groups?` |
| `request` | A recorded call the reader can re-run: skaldr builds the curl, or you give the exact `command` (see below), which runs any shell line, including a secret-manager wrapper such as `doppler run`, `op run` or `vault-run`, so the credential never enters the page, or a `query` for a database, SQL or MCP call | `method` + `url` + `headers?` + `body?`, **or** `command` + `command_note?`, **or** `query: {runner, lang, content}`; `variables?`, `case_variable?`, `cases: [{label, value? or values?, command?, headers?, headers_add?, tone?, response, verdict?}]` |
| `request_flow` | Calls that depend on each other, passing a captured value along (see below) | `variables?`, `steps: [{label, method + url + headers? + body? or command or query, case_variable?, cases (each with value? or values?, as in a request), captures?}]` |
| `references` | Numbered sources; cite inline with `[^key]` (see below) | `items: [{key, text, url?}]` |
| `section` | Collapsible container | `title`, `id?` (stable anchor), `fields?` (status, priority, assignee, due, labels, estimate, links; see below), `collapsed?` (default true), `updated?`, `blocks[]` |
| `panel` | Always-open titled card, one per "slide" in a deck-style doc | `title`, `blocks[]` |
| `toggle` | Collapsible group for anywhere a block can go, with no TOC entry or anchor | `title`, `collapsed?` (default true), `blocks[]` |
| `tabs` | Several panes shown one at a time, chosen from the label strip a multi-case `request` uses | `tabs: [{label, tone?, blocks[]}]` (2 to 24 tabs, distinct labels) |
| `grid` | Side-by-side layout (6 columns) | `cells: [{span: 1-6, blocks[]}]` |
| `walkthrough` | Numbered steps, each with a detail column (see below) | `steps: [{label, sub?, tone?, detail: [blocks]}]`, `step_span?`; a step's `detail` may include a `grid` for a two-column step (Action \| Script) |

Cards: pass `of` to render a derived percentage (`8,500 · 85.0%`). A `value` may be a short
string (e.g. `HEALTHY`) instead of a number. `delta` adds a trend chip beside the value,
`{label, direction?: up|down|flat, tone?}`, where you choose the `tone` (up isn't always
good: for cost or errors, down is, so skaldr won't infer it) and `direction` sets the glyph.

**Derived cards.** Instead of a hand-typed `value`, a card can *count* a state so the number can never
drift. Two sources, each keyed by a `badge` (which also supplies the card's chip / label / border tone);
`value`/`of` are computed, so don't author them; add a `note` or override `label`/`tone` if you like. A
`badge` on a card *requires* one of these (for plain chips on a normal card, use `badges`):

- **`of_matrix: <id>`**: count cells in the `matrix` with that `id` whose state is the badge; the
  denominator is the matrix's total cell count.
- **`of_tables: [<id>, …]`**: count the badge across several **tables** (a page-level summary over
  per-section tables). Each named table needs an `id` **and** a `rollup` (its `rollup.by` is the column
  counted); the denominator is the total rows across those tables. Reach for this when your rows carry
  one state each (a list, not a grid) and a single `matrix` can't model them.

```yaml
- type: cards            # a summary that can't go stale
  items:
    - { badge: HAVE, of_matrix: readiness }               # from one matrix, e.g. 15 · 42%
    - { badge: GAP,  of_tables: [tier1, tier2, tier3] }   # summed across three tables' rollup columns
- type: matrix
  id: readiness
  # rows / columns / cells …
```

An `image` `src` is either a self-contained `data:` URI or an http(s) URL. skaldr never fetches or
generates images. **Base64-encode a `data:` payload** (a raw, unencoded SVG isn't a valid URI and
won't render). The page's content security policy lets it load `data:` images only, so a URL cannot
show as a picture there: an `image` or `media` block with a URL shows as a card with its kind
(`Image`, `Video`, `Audio`, `File` or `PDF`), its alt text or caption, and the URL's host, and the
card links to the URL. An `image` needs `alt`, and a blank `alt` fails the build. A URL must start
with `http://` or `https://` and may not hold a username or password. A `media` block takes http(s)
URLs only. Every export refuses an `image` with a `data:` source, since none of its targets can show
one; in a document you export, host the image and give its https address (for a Slack canvas,
upload it to Slack and give its permalink).

```yaml
- type: image
  src: "https://example.com/aisle-12.png"
  alt: "Aisle 12 with overflow bins"
  caption: "Overflow bins before the count"
- type: media
  kind: video
  src: "https://example.com/dock-walkthrough.mp4"
  caption: "Dock walkthrough"
```

A `link` block points at a page the reader can open. `display: inline` writes a plain link in a line of text, `card` (the default) a bordered card with the title, the domain and an optional caption, and `embed` asks for the page to be shown in place. The page skaldr writes loads nothing from outside, so it cannot show an embedded page: an `embed` renders as the same card with a note that the page cannot load embedded content, and the card opens the link. Without a `title` the link text is the URL without its scheme, and a card shows no domain line. The `url` must be an `http://` or `https://` address. An `inline` link takes no `caption`.

```yaml
- type: link
  url: "https://example.com/runbook"
  title: "Counting runbook"
  caption: "rev. 7"
- type: link
  url: "https://example.com/board"
  display: inline
  title: "the live board"
```

A `section` holds any block except another
`section`, a `grid`, or a `walkthrough`, so a `panel` may sit inside one. A `panel` holds any block
except a `section`, a `grid`, a `walkthrough` or another `panel` directly inside it. A section
**starts collapsed** (`collapsed: true` default), right for an appendix or detail-on-demand; for a
doc meant to be **read through** (a weekly status doc), set `collapsed: false` so it opens expanded.
Its optional `updated` shows a muted "updated <value>" stamp in the section header: a free-form
label like `meta.date`, for keeping a living doc's regions honest.
A top-level `section` is a document region on a par with an `h2`, so it gets its own TOC entry (with
`meta.toc`) and anchor, so a living-doc region can be both navigable and freshness-stamped.

**Section `fields`.** A section may carry issue fields or page properties, shown as a fact strip at the top of its body (the HTML) or as a bulleted list under its heading (the GitHub and Notion Markdown). Every key is optional: `status`, `priority` (strings, shown as chips), `assignee` (a person key, shown as a person chip carrying the key), `due` (an ISO date such as `2026-10-15`; YAML reads it unquoted), `labels` (a list of strings, one chip each), `estimate` (a number) and `links`. `links` maps a link type to the ids of the sections it points at, such as `blocks: [st3]`; each id must be the `id` of a section in the document, or the build fails naming the missing id, and the HTML shows each as a link to that section. The GitHub-flavored export writes it as a link too, and the Notion, ADF and Slack exports write the section's title as text, since they cannot link to a heading of their own page. A link stays within one file: a section in an index's part can link to another section of the same part file, never to a section in a different part, because each part is checked on its own and the build fails naming the id. A key skaldr does not know is kept and shown as a generic chip, so a Jira custom field fits: its value is a string, a number or a list of strings and numbers, and a boolean, a mapping, null, a blank string, an empty list or a number that is not finite fails the build. Numbers show as written, without thousands separators, so `year: 2026` stays `2026`. A link type shows with its first letter upper-cased (`QA review` stays `QA review`), an extra key shows exactly as written, and two facts that would show under the same label, such as an extra key `Status` beside the `status` field, fail the build.

```yaml
- type: section
  id: st2
  title: "Widen the bin code"
  collapsed: false
  fields:
    status: "In Progress"
    priority: High
    assignee: ada
    due: 2026-10-15
    labels: [onboarding]
    estimate: 3
    links: { blocks: [st3] }
    team: "Floor ops"
  blocks: [{ type: text, body: "Bin codes grow from four to six characters." }]
- type: section
  id: st3
  title: "Relabel the aisles"
  blocks: [{ type: text, body: "Print and hang the new aisle labels." }]
```

A `toggle` is the collapsible for everywhere a `section` cannot go: inside a section, a panel, a grid cell or a walkthrough step's detail, as well as at the top level. It looks like a section's collapse but gets no TOC entry and no anchor, so use it to tuck away detail rather than to mark a region. It starts collapsed like a section (`collapsed: false` opens it). What it holds depends on where it sits. At the top level, in a section, in a panel or in another such toggle it holds whatever a section holds, including a `request` or `request_flow`. In a grid cell, a walkthrough step's detail or a tab it holds any block except a section, panel, grid, walkthrough, request or request_flow. A toggle may hold another toggle, and a heading inside one still gets its anchor.

A `tabs` block shows one of its panes at a time, chosen from the same label strip a multi-case `request` uses, so choosing a tab needs no script and a strip too wide for its container turns into a rail. The first tab starts chosen. A tab's optional `tone` puts a coloured dot before its label; leave it out for a plain label. A tabs block goes wherever a toggle goes. A tab holds what a toggle in a grid cell holds, including a toggle or another tabs block, and never a `request` or `request_flow`: a request draws its cases with the same strip and the same pane class, so the rules that lay out a tab's pane would override the layout of a request's case panes inside it. On paper every tab prints, each under its own label, so a tab never hides content from a PDF. A same-page `[…](#id)` link to a heading inside a tab that is not chosen opens that tab, and every tab around it, before the page scrolls to the heading. It does so again when the reader follows the same link a second time after choosing another tab.

```yaml
- type: tabs
  tabs:
    - { label: "Floor", tone: warning, blocks: [{ type: text, body: "Recount Zone C by hand." }] }
    - { label: "System", blocks: [{ type: text, body: "Rescan the truncated bins." }] }
```

Lists: `start` and `numbering` belong to a `style: number` list, `checked` to a `style: check` list, and `decided` to a `style: decision` list; anywhere else the build fails. A nested list keeps the numbering and counts from 1. A decision list shows a tick for a decision taken and a question mark for one still open, so a record of what was settled and what is still open reads at a glance.

In the example below, the numbered list continues a procedure whose first three steps came earlier, so its points read iv, v and vi. In the decision list, the first point is a decision taken and the second, with no `decided`, is still open.

```yaml
- type: list
  style: number
  start: 4
  numbering: roman
  items: ["Freeze inbound moves.", "Re-scan every bin.", "Re-run reconciliation."]
- type: list
  style: decision
  items:
    - { text: "Keep the most recent scan.", decided: true }
    - "Whether overflow aisles get their own count window."
```

Icons: a `callout` or a `note` may set `icon` to one emoji, shown at the head of the block. It replaces the icon the Markdown exports otherwise pick from the tone. It must be exactly one emoji from the Unicode emoji list: a flag such as 🇺🇦, an emoji with a skin tone such as 👍🏽, a keycap such as 1️⃣ or a joined emoji such as 👩‍💻 each count as one. A symbol that has both a text and an emoji form, written without its emoji selector (⚠ for ⚠️, © for ©️), is stored in its emoji form. A letter, a digit, a word, a symbol that is not an emoji such as ✓, a skin tone or a single flag letter on its own, two emoji, or an emoji padded with spaces fail the build.

Code diff mode: with `mode: diff`, skaldr reads the **first character of each line**: `+` marks an
added line (green), `-` a removed line (red), anything else is context. You write the `+`/`-`
prefixes yourself; skaldr strips the marker, re-labels the line, and tints it; it does **not**
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

Code language: `lang` names the language the Markdown exports put on the code fence (`lang: shell`, `lang: python`, `lang: plain text`). Without it, a file name in `label` decides (`deploy.sh` is bash, `query.sql` is sql); with neither, the GitHub fence has no language and the Notion fence says `plain text`, since Notion shows a fence without a language as JavaScript. `mode: diff` always exports as `diff`. The HTML page highlights the code in that same language, in `mode: diff` too, with colours that follow the light and dark themes; code with no known language, or a `lang` Pygments has no lexer for, renders plain. Copy and print keep the code as written.

## The `grid`

Place blocks side by side over a 6-column base. Each cell takes a required `span` (1 to 6); spans in
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

Keep running prose out of narrow columns. A paragraph squeezed into a 1- or 2-span cell reads as a
cramped ribbon; put `text` in a wide cell (or as a full-width block outside the grid), and reserve
narrow spans for cards, meters, short lists, and stats.

Give a cell an optional **`tone`** to make it an emphasis panel (accent top-border + tint): use
`accent`/`success` for the *primary* panel and `neutral` for a *muted aside*, so a reader sees which
of two side-by-side panels is the answer.

## The `flow`

A directional pipeline: the block for a process, data flow, or architecture where the **direction
between stages is the message** (the thing a bulleted list or `status_list` throws away). Nodes are
connected left-to-right; the connector leads each node, so a long flow wraps cleanly with no
dangling arrows.

```yaml
- type: flow
  style: arrow          # arrow (default) | steps
  loop: true            # draws a "↺ back to <first>" return marker, for a cycle, not a one-way flow
  numbered: true        # 1..n on the nodes (default); set false to hide
  steps:
    - { label: "Source",  tone: info,    note: "Query log + index stats" }
    - { label: "Reason",  tone: info,    points: ["Weighs index overlap", "Scores by hit-ratio"] }
    - { label: "Propose", tone: accent }
    - { label: "Deliver", tone: success }
```

**Which `style`:**
- `arrow` (default): short-labelled chips joined by connectors. Reach for it when the flow is the
  *direction itself*: a pipeline, a request path, a state cycle. Keep labels to a word or two.
- `steps`: equal cards that each carry a one-line `note` caption. Reach for it when **every stage
  needs a sentence of explanation** and the labels alone aren't enough.

Beyond the one-line `note`, a step may carry `points`, a few detail bullets under the node, for
when one line isn't enough. Best paired with `style: steps` (a bullet list crowds a compact arrow
chip). Rule of thumb: if most nodes have a `note`, use `style: steps`; otherwise `arrow`. A flow with more
than ~6 nodes usually reads better as `steps`, or split into two flows. `tone` (any of
`neutral·info·success·warning·danger·accent`) accents a node's border + number; use it to mark the
key stage, not every node. `loop` is for genuine cycles (flag→fix→verify→flag), not linear pipelines.

The GitHub-flavored and Notion exports draw a flow as a Mermaid diagram, whose labels hold plain text
only, so they refuse a step whose `note` holds a link, citation, inline math, struck-through text, or a
subscript or superscript with no Unicode form; keep such a note plain and put the rest in a text block
after the flow. A subscript or superscript with a Unicode form, such as `H~2~O`, is written as `H₂O`, with
the same characters a Slack canvas takes. Any other mark in a note, such as bold, italic, underline, a
colour or inline code, keeps its characters and loses its formatting. The ADF and Slack
canvas exports cannot draw a diagram, so they refuse a document holding a `flow`; for those targets,
write the steps as a numbered list.

## The `fan`

A one-to-many shape: several nodes converging into one, or one branching out to several. Reach for
it when the structure is **fan-in / fan-out**, not a linear pipeline (that's `flow`): three source
systems feeding one record, one request dispatched to three services. The `spokes` (the many, 2+)
sit in a dashed well; a single arrow joins them to the `hub` (the one). `direction` sets which way:

```yaml
- type: fan
  direction: in           # in (default): spokes → hub (N→1) | out: hub → spokes (1→N)
  hub: { label: "Order record", tone: accent }
  spokes:
    - { label: "Payment gateway", tone: info }
    - { label: "Inventory check",  tone: info, note: "nightly batch" }
    - { label: "Shipping quote",   tone: info }
```

`hub` and `spokes` are flow nodes: each takes `label`, optional `tone`, `note` (rich, one line),
`points` (detail bullets), and `badges`. Use `direction: out` for the reverse (one hub branching to
the spokes).

As with a `flow`, the GitHub-flavored and Notion exports draw a fan as a Mermaid diagram, and the
ADF and Slack canvas exports refuse a document holding one; for those targets, write the hub and
its spokes as a list.

## The `walkthrough`

A vertical list of numbered steps where **each step needs a whole column of detail beside it**:
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
      tone: info                        # optional; draws a subtle accent on the step's edge
      detail:                           # a nested block list, like a grid cell
        - { type: text, body: "Group the criteria by surface; two rules are load-bearing." }
        - { type: list, items: ["exactly-one-default per registry", "the reconcile invariant"] }
    - label: "Slice into shippable tickets"
      detail:
        - { type: code, label: "dedupe key", content: "key = (warehouse_id, sku)" }
```

`detail` holds the same blocks you'd put anywhere else (it can be long; that's the point). The
step numbers are derived (1..n). Every step always shows its left rail (it is the list's structure);
`tone` only changes the rail's **colour**, so use it to mark the **key** step, not every step
(toning all of them just removes the contrast). Distinct from `flow` (a directional pipeline) and
`grid` (no row-by-row step alignment).

## The `range`

One horizontal bar cut into `segments` whose widths are **proportional to their `span`**, for a
numeric extent that a `meter` (a single value/max ratio), `chart`, or `flow` (equal chips) can't show:
a date window, a coverage span, a before/after split. Spans are normalised, so only the ratios matter
(`[3, 1]` and `[30, 10]` are identical). Each segment carries a soft-tint `tone` and an optional `sub`
line; an optional `axis` labels the extent's ends.

```yaml
- type: range
  axis: { min: "2015", max: "2025" }      # optional end-cap labels; either end may be omitted
  segments:
    - { label: "Supported", span: 7, tone: success, sub: "security fixes" }
    - { label: "Review", span: 2, tone: warning }
    - { label: "Expired", span: 1, tone: danger }
```

Reach for it when the **relative size of spans** is the message. For a single ratio use `meter`; for a
trend or distribution use `chart`; for an ordered set of stages use `flow`.

No export can draw a range bar. Every `--export` target, `skaldr publish` and
`skaldr --check --for <target>` refuse a document holding a `range`; in a document you export, use a
`meter` or a `table` instead.

## The `chart`

Render-time SVG: self-contained, no JS. You give the data; skaldr computes the scale, ticks,
gridlines, smoothed curves, and arcs, plus a legend whose swatches match the series. Reach for a
chart when a number's **shape** is the point (a trend, a spread, a share); use `cards` for standalone
figures and `meter` for a single ratio.

- **`bar`**: compare a value across categories. Extra `series` group side by side, or `stacked: true`.
- **`line`**: a trend across an ordered axis (smoothed); a lone series gets a soft area fill.
- **`donut`**: parts of a whole; the shares are derived.

`bar`/`line` take `categories` (the x-axis) and `series` (each `{label, values, tone?}`, with one value
per category); `donut` takes `slices` (each `{label, value, tone?}`). `tone` is optional: skaldr
colours any unset series/slice from the palette so they stay distinct.

The GitHub-flavored and Notion exports draw a donut, or a bar or line chart with one series, as a
Mermaid chart over its data table. A Mermaid chart has no legend, so they write a chart with several
series as its data table alone. The ADF and Slack canvas exports write every chart as its data table.
The table holds every value the chart draws, and for stacked bars with several series a `Total` row
holds each category's stack. A row keeps the `tone` set on its series or slice, where the target shows a
row's tone; the colour the page picks for a series or slice with no `tone` is not carried, since the
label in the row's first cell tells it apart.

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

A feature matrix: the `options` you're weighing across the top, each `feature` down the side. One
column can be `highlight`ed (0-based) as the recommended pick. Each row's `values` give one cell per
option, in order: a bare `true`/`false` renders ✓/✗, a bare string renders as text, and
`{value, tone}` renders toned text. (YAML also reads bare `yes`/`no`/`on`/`off` as booleans, so quote
them (`"yes"`) if you mean the literal word, not a ✓/✗.) Reach for it to weigh a few named options against shared
criteria; for freeform tabular data use `table`.

By default a ✓ reads good (green) and a ✗ reads bad (red). Set `polarity` (one `positive`/`negative`
entry per option) to flip that per column: in a `negative` column a present-is-bad attribute (e.g.
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

## The `matrix`

Rows × columns with **one state per cell**: a coverage map you see the shape of at a glance, instead
of several stacked tables. `rows` are the row axis (top to bottom), `columns` the header axis (left to
right); `cells` fill the grid. The **cell is the signal**: its badge (or one-off tone) fills it with
colour, so the whole grid reads as a heatmap. Reach for it for a coverage grid, a RACI chart, a
capability / support matrix, or an env-vs-feature grid. (Use `comparison` instead when you're weighing
named *options* against criteria with a recommend column; use `table` for freeform tabular data.)

Each cell names a `row` + `col` from the axes, plus its fill:

- `badge: KEY`: a declared badge. Its tone fills the cell, its label is the text. (These badges join
  the page legend automatically, like any badge reference.)
- `tone: <colour>`: a one-off fill with no vocabulary badge; pair with `label` for the cell text (a
  RACI letter, a ✓).
- `label: "…"` alone: plain short text on an untinted cell.
- **omit the cell entirely for a blank.** At most one cell per (row, col); `badge` and `tone` are
  mutually exclusive.

```yaml
# HAVE / PARTIAL / GAP declared in the page `badges:` map (see above)
- type: matrix
  rows: [Receiving, Putaway, Picking]
  columns: [Docs, Tests, Alerts, Runbook]
  cells:
    - { row: Receiving, col: Docs,   badge: HAVE }
    - { row: Putaway,   col: Alerts, badge: GAP }
    - { row: Picking,   col: Docs,   tone: blue, label: "R" }   # one-off, e.g. a RACI letter
    # Picking / Runbook omitted → a blank cell
```

Give the matrix an `id` and a `cards` block can **count** its states into derived, drift-proof summary
numbers (see *Derived cards* under the block table above).

## The `swimlane`

A process laid on a grid: `lanes` are the rows (teams, systems, roles) and `columns` are the axis
across the top (sprints, phases, weeks). Each step sits in one `lane`/`col` cell. Reach for it when
**who does what, when** is the message and a single-track `flow` can't show the hand-offs. Both
`lanes` and `columns` are declared up front, ordered, and unique; up to **8 lanes** (more rows stop
reading as a matrix, so split into two swimlanes). Every declared lane and column must carry at least
one step (no empty rows or columns).

A lane or column is either a **bare string** (the simple case: the string is both the label and the
reference key, used verbatim; spaces are fine, e.g. `col: "Sprint 1"`) or an **object** for more
control: `{id, name}` on a lane, `{id, name, sub}` on a column. The slug rule (letters, digits, `_`,
`-`, no spaces) applies **only to an explicit `id`**, not to a bare-string name. `id` is the key steps
reference, defaulting to `name`; set it to rename a header without touching every step. `sub` puts a secondary caption under a
column header (e.g. `sub: "→ MVP demo"` or a date range).

```yaml
columns:
  - "Sprint 1"                                        # bare string: key == label
  - { id: s2, name: "Sprint 2", sub: "→ MVP demo" }   # id key, display name, sub-caption
```

Step fields are explicit, and skaldr never derives or renumbers them: `lane` (a lane's key), `col`
(a column's key), `n` (the number shown, a free string such as `"1"`, `"3a"` or `"R1"`), and
`label`. Two steps in the same cell stack.

Give steps an optional numeric `value` (points, hours, cost, headcount: whatever the matrix measures)
and skaldr auto-sums it into **totals that never drift by hand**: a footer row of per-column sums, a
per-lane sum beside each lane label, and (with `groups`) a per-group sum on each cap (a group's total
counts only the steps resolved into it). Totals appear only when at least one step has a `value`; a step
without one counts as 0.

A step may also carry an optional `url` (http/https/mailto, e.g. its Jira/GitHub ticket), which turns
its number into a link, and a **`state`**: the same progress axis as `status_list` and `timeline`, in
roadmap terms (`todo` for not-started, plus a `deferred`). The states are `done` (green),
`current` (in progress, the raised blue badge), `todo` (planned, not started; a cool
filled slate badge, which is also how the HTML draws a step with no `state`; the Markdown exports
show a state glyph only for a step whose `state` is set), `blocked` (waiting / on-hold: amber + a sharp dashed frame), and `deferred`
(pushed out / post-MVP: a warm hollow badge that recedes). Colour rides on the number badge and the
ticket's left edge; the label stays legible at every state (`deferred` recedes by hue, not by
dimming). Reach for `deferred` for work you've consciously parked, `blocked` for work stopped by a
dependency (pair it with a `depends_on` marker). A step's `value` counts toward the totals in every
state. skaldr auto-renders a small state legend under the grid whenever two or more states appear
(a single-state swimlane needs none); you don't author it. In the Markdown exports the legend lists
the states that carry a glyph, and appears whenever two or more glyphs appear or some steps carry a
glyph and others none.

To record dependencies, give a step an `id` (a safe slug: letters, digits, `_`, `-`) and point at it
from another step's `depends_on: [id, …]`. Each dependent renders a small "needs 1, 2" line showing the
numbers of the steps it waits on. (skaldr doesn't draw arrows across the matrix, since a dense grid leaves no
room; the "needs" marker is the compact, readable form.)

```yaml
- type: swimlane
  lanes: ["Product", "Eng", "QA"]
  columns: ["Sprint 1", "Sprint 2", "Sprint 3"]
  steps:
    - { lane: "Product", col: "Sprint 1", n: "1", label: "Spec", url: "https://jira/PROJ-1" }
    - { lane: "Eng", col: "Sprint 2", n: "2", label: "Build", value: 5 }
    - { lane: "Eng", col: "Sprint 3", n: "3a", label: "Feature flag", state: current }   # stacks with 3b
    - { lane: "Eng", col: "Sprint 3", n: "3b", label: "Perf pass", state: deferred }   # parked / post-MVP
    - { lane: "QA", col: "Sprint 2", n: "2b", label: "Vendor sign-off", state: blocked }   # waiting on a dep
    - { lane: "QA", col: "Sprint 3", n: "4", label: "Regression" }   # no state: drawn as todo
```

### Optional group (milestone) overlay

Add `groups` to overlay milestones/deliveries: each group has an author-chosen `color` and a
**contiguous** run of `columns`, drawn as a coloured cap poking above and below the table plus a faint
cell tint. Inside the table stays a plain grey grid: solid lines between columns, a dashed line where
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
layout). Columns share the width evenly with a 150px floor, so a few columns fill the page rather than
huddling at the left; once that floor would overflow, the block scrolls horizontally, staying a grid
rather than reflowing (and fits the page when printed).

## The `request`

A call you made, what came back, and what it meant, shared so a reader can reproduce it with their
own credentials. The page builds a `curl` they copy and run; it never makes a request itself, which is
also all a self-contained page with a locked-down CSP could ever do.

```yaml
- type: request
  label: "Read an endpoint on the demo API"
  method: GET
  url: "https://{{host}}/{{resource}}?limit={{limit}}"
  headers:                                 # a map, in the order it should read
    Authorization: "Bearer {{token}}"
    Accept: "application/json"
  variables:                               # the fields the reader fills
    - { name: host,  example: "api.example.com" }
    - { name: limit, example: "2" }
    - { name: token, secret: true }        # never prefilled, so it cannot live in this file
  case_variable: resource                  # what each case below supplies
  cases:
    - label: widgets
      response:
        status: 200
        headers: { content-type: "application/json" }
        body: |
          { "widgets": [], "total": 0 }
      verdict: "Open data, no credential needed."
    - label: admin
      headers: {}                          # this case sends none, recording the no-auth result
      response: { status: 401, body: '{ "message": "Access Token is required" }' }
```

**`{{name}}` is a runtime blank, not a fill-me-later one.** A name declared in `variables` (or supplied
by `case_variable`) is a field the reader fills when they open the page, so `--check --strict` leaves it
alone. A name you never declared is still an unfilled placeholder and still fails strict, which is what
catches `{{tokne}}`.

**Cases are the outcomes, not the requests.** They tab on screen and **stack under their own headings
when printed**, because a tab must not hide evidence on paper. Give each a `verdict`: what you expected,
what you got, what it means. That is the one part a reader cannot work out for themselves. A case
usually varies one value through `case_variable`; set `headers` on it to replace the request's headers
instead, which is how you record what happens with the auth header removed.

**Cases that differ by several values use `values`.** `case_variable` fills one name per case. When a
case changes more than one thing, declare each in `variables` and give every case a `values` map from
variable name to value. The `command` (or the built call) is written once, and each case's tab shows it
with that case's values written in, so it runs as copied:

```yaml
- type: request
  label: "One record, two terms"
  command: |
    vault-run -- curl -s "https://api.example.test/v1/records?id={{id}}&term={{term}}&seq={{seq}}" | jq '.'
  variables: [{ name: id }, { name: term }, { name: seq }]
  cases:
    - label: "Second term"
      values: { id: A100, term: "2", seq: "1" }
      tone: warning
      response: { body: '{ "records": [] }' }
      verdict: "The record exists in term 1 and is missing from term 2."
    - label: "Control"
      values: { id: A100, term: "1", seq: "1" }
      tone: success
      response: { body: '{ "records": [{ "id": "A100" }] }' }
```

A case sets `values` or `value`, never both, and `values` requires the request to declare no
`case_variable`. Every key of `values` must be a name declared in `variables`; a case that sets a key
that is not declared fails the build naming the case and the key. A variable a case binds is written
into that case's command and is not a field on that tab. A variable no case binds, or that a case
leaves out, is still a field the reader fills on that tab, and `--check --strict` still leaves it alone
as a declared name, so a case may bind only some of the variables. Once every case that uses a variable
binds it, the variable is no longer listed in the fields at all. `values` works the same for a built
call (the url, header values and body take the `{{name}}` tokens) and for a case's own `command`.

A key of `values` must also appear as a `{{name}}` in what that case sends: its own `command`, or the
request's command or url, headers and body as that case sees them. A key the case never uses fails the
build naming the case and the key. A `secret` variable cannot be bound through `values`, because the
value would be written into the page and the exports; the reader supplies it. A value is inserted as
written, so a `{{name}}` inside a value is read as a slot the reader fills.

**`headers` replaces, `headers_add` layers.** Cases that share a credential and differ in one header
write the shared one once on the request and the difference under `headers_add`, which replaces the
names it lists and leaves the rest. `headers` stays a replacement, because `headers: {}` is what records
a call with the auth header removed and layering would quietly turn that case's 401 into a lie. A case
may set one or the other, never both.

`status` drives the tone, so you never pick a colour. Omit `reason` and the standard text for the code
fills in, which is what an HTTP/2 response needs since it carries none. Omit `status` entirely for a
response with no status line, such as a bare token from `curl -s`. A header that legitimately repeats
takes a list: `set-cookie: ["a=1", "b=2"]`. A one-line JSON body, the way `curl -s` prints it, is
pretty-printed on the page; a body you laid out across lines keeps your layout.

### Running an exact command: `command`

Give `command` instead of `method`/`url`/`headers`/`body` when the call needs something those fields
cannot say: a secret manager (`doppler run`, `op run`, `vault-run`) that supplies the credential so
the reader never handles one, a proxy, a `| jq` that makes the evidence visible. The Copy button hands
over the command exactly as you wrote it, every line and every quote, so one copy, one paste, one run
reproduces what you saw.

```yaml
- type: request
  label: "Tier mappings on the partner API"
  command: |
    cd ~/code/example-service && vault-run --env prod -- sh -c 'curl -s --proxy "$EGRESS_PROXY" -u "$PARTNER_USER:$PARTNER_PASS" "https://api.partner.example/v1/mappings?label=TIER"' | jq 'map({code, mappedValue})'
  command_note: "The API omits `mappedValue` when it is empty, so the `jq` names the field to make the gap print as `null`."
  cases:
    - label: "TIER, the finding"
      tone: warning                        # no HTTP status to colour it, so you say what it is
      response:
        body: '[{"code":"STANDARD","mappedValue":null},{"code":"PREMIUM","mappedValue":null}]'
      verdict: "Rows exist, and none carries a mapped value, so the import resolves zero tiers."
    - label: "REGION, the control"
      command: |                           # a case may run its own command
        cd ~/code/example-service && vault-run --env prod -- sh -c 'curl -s --proxy "$EGRESS_PROXY" -u "$PARTNER_USER:$PARTNER_PASS" "https://api.partner.example/v1/mappings?label=REGION"' | jq 'map({code, mappedValue})'
      tone: success
      response:
        body: '[{"code":"EU","mappedValue":"eu-west-1"}]'
      verdict: "Same endpoint, same credentials, and the value comes back. Access is not the explanation."
    - label: "REGION through Doppler"
      command: |
        doppler run -p example-service -c prd -- sh -c 'curl -s -u "$PARTNER_USER:$PARTNER_PASS" "https://api.partner.example/v1/mappings?label=REGION"' | jq 'map({code, mappedValue})'
      tone: success
      response:
        body: '[{"code":"EU","mappedValue":"eu-west-1"}]'
      verdict: "Doppler injects the credentials for the one command, so none of them appears on the page."
```

- **Pick `command` when a copied curl would fail or mislead.** If the reader would run skaldr's curl
  and get a 403 because the credential, proxy or filter is missing, the button is manufacturing
  counter-evidence. Write the command you ran.
- **A `{{name}}` still works** inside `command`, from `variables`, `case_variable` or a case's
  `values`, and is written in exactly as the reader types it, with no shell quoting added. You own the
  quoting, so put the token where the shell will read it the way you mean.
- **`command` excludes `method`, `url`, `headers` and `body`**, and a case of a command request cannot
  set `headers` or `headers_add`. Those fields exist to build a curl, and a request with a `command`
  builds none, so they would never reach what the reader runs. A request that sets `command` together
  with any of them fails the build with a message naming that field.
- **`tone` colours a case with no `status`**: `warning` or `danger` for a finding, `success` for a
  control that passes, `info` or `neutral` otherwise. A recorded `status` decides the tone by itself,
  so a case never sets both.
- **`command_note`** says why the command is shaped the way it is. The `verdict` stays about what came
  back.
- **"Copy + capture"** pipes the output to the clipboard. Every command, one line or many, is wrapped
  in `{` and `}` on lines of their own first, so the capture takes the output of all of it, including
  `a; b` and a line that ends in a `# comment`. Plain Copy is always the command byte for byte.

**A verification document** (numbered claims a reader re-runs to check them for themselves) is a page
of these blocks. Put each claim in its own `request`, with the finding as the first case and each
control that rules out another explanation as a case after it. Give each case a `tone` and a verdict
that says what it proves. Cases stack under their own headings in print, so the paper copy keeps every
control.

A `request` is full width. It may sit at the top level or inside a `section` or `panel`, but not in a
grid cell, where the form and the response pane have no room.

**What a `secret` guarantees, exactly.** It is never prefilled, so it cannot be written into the YAML,
and it never reaches the embedded source block. `--pdf` loads the file fresh with the form empty, so it
never reaches that either. It is not masked on screen, and a reader printing from a tab they have
filled in does capture what they typed, in the form and in the command.

**A secret reaches the command as the value the reader typed**, like every other field, so the command
runs exactly as it is copied: one click, one paste, one return. That value is in the reader's shell
history afterwards, which is a property of pasting a credential into a terminal rather than of this
page. A reader who minds can set their shell to skip a space-prefixed line.

**A field that is not secret is kept for the length of the tab.** A reload restores `host` and an id
rather than asking for them again. It lives in `sessionStorage`, so it dies with the tab and never
reaches disk, and a `secret` field is never written there at all.

That store is keyed by the block's `id`, or by its `label` when it sets none, which is why no two
request blocks on a page may share one: they would share the reader's values. Give one an `id` when
two blocks legitimately carry the same label, and keep that `id` fixed if you want the values to
survive a rename.

### Evidence that is not a shell command: `query`

Give `query` when the evidence is a database aggregation, a SQL statement or an MCP tool call, run in
some named tool rather than a shell. The page shows the query highlighted, labelled with the tool it
runs in, and the cases record its real output the way they do for any other request.

```yaml
- type: request
  label: "Orders by status in the shop database"
  query:
    runner: "mongosh, orders database"    # free text, shown with the query
    lang: json                             # a Pygments lexer name: json, sql, js, ...
    content: '[{"$match": {"status": "{{status}}"}}, {"$count": "n"}]'
  variables: [{ name: status, example: "open" }]
  cases:
    - label: "Open orders"
      tone: warning
      response: { body: '[{"n": 12}]' }
      verdict: "Twelve orders are still open, so the nightly close has not run for them."
```

- **Copy hands over the query text**, with `{{name}}` filled in exactly as the reader typed it, so
  pasting it into the tool re-runs what you ran. A `{{name}}` works from `variables` and
  `case_variable` the same way it does in a `command`.
- **There is nothing to run or capture on the page.** A query shows no "Run this" shell line, no
  "Copy + capture" and no field to paste output into, because the page cannot run a query. Record the
  output you got as the case's `response`.
- **`lang` is checked when the file is read.** A name Pygments has no lexer for fails the build naming
  it. The same name highlights the query on the page and labels its fence in the Markdown exports,
  where the query is a fenced block under the runner's name.
- **`query` excludes `method`, `url`, `headers`, `body` and `command`**, and a case of a query request
  cannot set `command`, `headers` or `headers_add`; nor can it replace the query. A request that sets
  `query` together with any of them fails the build with a message naming that field. `command_note`
  is refused too: say it in a `verdict`. A `request_flow` step may record a `query` but cannot capture
  from one.
- Cases, responses, `tone` and `verdict` work exactly as they do for a `command` request.

## The `request_flow`

Calls that depend on each other: get a token, then use it. A step says what its response produces, and
a later step writes that name the way it writes a reader's field, so the reader supplies the credential
once and never copies a value between two boxes.

```yaml
- type: request_flow
  label: "Token, then profile"
  variables:
    - { name: host, example: "api.example.com" }
    - { name: password, secret: true }
  steps:
    - label: "Exchange the credentials for a token"
      method: POST
      url: "https://{{host}}/auth/login"
      body: '{"user":"ada","password":"{{password}}"}'
      captures:
        - { name: access_token, json_path: "$.accessToken", secret: true }
      cases:
        - label: "200"
          response: { status: 200, body: '{ "accessToken": "eyJ…" }' }

    - label: "Read what the token reaches"
      method: GET
      url: "https://{{host}}/{{resource}}"
      headers:
        Authorization: "Bearer {{access_token}}"
      case_variable: resource        # this step tabs, like a request does
      cases:
        - label: "auth/me"
          response: { status: 200, body: '{ "user": "ada" }' }
          verdict: "The token from step 1 is the only thing that makes this a 200."
        - label: "auth/sessions"
          headers_add: { Accept: "application/vnd.example.v2+json" }
          response: { status: 200, body: "[]" }
        - label: "auth/me without the token"
          value: "auth/me"
          headers: {}
          response: { status: 401, body: '{ "message": "Access Token is required" }' }
```

**A capture takes `source: body`** for an endpoint that answers with a bare token, **or a `json_path`**
like `$.accessToken` for one that answers with JSON. Object keys separated by dots, which is what the
page resolves; an array index is not part of the path. Mark it `secret: true` and the field reports a
length rather than the value.

**`variables` belongs to the flow, not to a step**, and every step draws on the same set. A name a step
captures is never declared there: the flow produces it rather than asking a reader for it.

**Order is enforced.** A step may only write a name an earlier step captured. Writing one from a later
step, or from itself, fails the build rather than leaving a reader a command with a blank in it. A
capture name may not also be a declared variable, since the flow produces it.

**A step that captures records one case**, because the value it produces has to be the one the later
steps read. A step that captures nothing may record as many as it likes, and takes `case_variable` like
a `request` does: one step authenticates, the next tabs through every resource that token reaches, and
the reader supplies the credential once rather than to two separate blocks.

**A step's cases take `values` as a `request`'s do.** A step that tabs through several outcomes by more
than one value gives each case a `values` map over the flow's `variables`, under the same rules: `value`
and `values` are never both, `values` requires the step to have no `case_variable`, and a key must be a
declared variable. A name a step captures is not declared, so a case cannot bind it. Captures still read
from the response pasted into the step, and a variable every case of every step binds is no longer
listed in the flow's fields.

```yaml
- type: request_flow
  label: "Sign in, then read a record"
  variables: [{ name: id }, { name: term }]
  steps:
    - label: "Sign in"
      command: "vault-run -- curl -s https://api.example.test/v1/session"
      captures: [{ name: session, source: body, secret: true }]
      cases:
        - label: "200"
          tone: success
          response: { body: "abc123" }
    - label: "Read the record"
      command: "vault-run -- curl -s -H 'X-Session: {{session}}' https://api.example.test/v1/records/{{id}}/{{term}}"
      cases:
        - label: "Second term"
          values: { id: A100, term: "2" }
          tone: warning
          response: { body: "{}" }
        - label: "Control"
          values: { id: A100, term: "1" }
          tone: success
          response: { body: '{ "id": "A100" }' }
```

**Each step's Copy gives that one call**, with every value written out (the reader's fields and any
value an earlier step captured alike), so it runs exactly as it is pasted. The reader works down the
steps in order, pasting each response back to fill the next.

A flow needs at least two steps. One step is a `request`.

A step may run an exact `command` on the same terms as a `request`, and its captures read from the
output the reader pastes back, so `vault-run -- mint-token` can hand its token to the next step.

A step may instead record a `query` (see the `request` section), shown with its runner and a Copy
button. A query has nowhere to paste output, so a step that records one cannot capture from it.

## The `references`

Numbered sources with inline citations. Drop a `references` block wherever the list should render;
anywhere in rich text, `[^key]` becomes a superscript number linking to that source, and the number
in the list links back to the citation. Numbering is by first appearance across every `references`
block, so the same `[^key]` always carries the same number. Keys are ASCII `[A-Za-z0-9_-]+` and must
be unique across the whole page (an unknown key stays literal so a typo shows). Put the `references`
block after the prose that cites it, so each source gets a backlink to its citation. Reach for it
when prose needs to cite sources; for a bare link inside a sentence use a `[text](url)` markdown
link instead.

A reference's `url`, like a swimlane step's, must be a well-formed `http`, `https` or `mailto` URL: one with no host (`https://`), any whitespace, a `mailto:` with no address, or a port past 65535 fails the build naming it. Write a space in a path as `%20`. The page links to the URL exactly as you wrote it.

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
    - { key: issue,   label: "Discrepancy" }                  # kind omitted → text; first text/rich col = the title
    - { key: tag,     label: "",              kind: badge }   # chip shown under the title
    - { key: count,   label: "Units",         kind: number, pct_of_total: true }
    - { key: problem, label: "What happened", kind: rich }
  reconcile:                        # optional trust check
    total: 9100
    column: count
    handled: { label: "Matched cleanly", value: 8500 }   # optional bucket outside the rows
  groups:                           # OR use `rows:` for an ungrouped table (not both)
    - name: "Floor: fixable"
      rows:
        - issue: "Double-counted units"
          tag: FLOOR
          count: 600
          problem: "The same pallet is scanned twice…"
          subrows:                  # optional quieter inner rows
            - { label: "bin > 12", value: 260 }
```

- **Columns** need at least one `text`/`rich` column (it hosts the row title and any chips). `kind`
  **defaults to `text`**, so a plain column is just `{key, label}`; only set `kind` for a non-text
  column (`rich`/`number`/`badge`/`indicator`). A
  `text`/`rich` cell may hold **multiple paragraphs**: separate them with a blank line (like a
  `text` block's `body`) and they stack; a single newline collapses to a space, unless the lines
  form a list (see Lists inside a body). A
  `badge` column with a non-blank `label` defaults to `placement: cell`: the badge gets **its own
  labelled column**, where the cell value is a badge key *or a list of keys* (several chips,
  wrapping), as for a real column like "Access" or "Severity". A badge column with a blank `label`
  (`label: ""`) defaults to `placement: title`: its value chips **under the row title**. Set
  `placement` to choose either one explicitly. An `indicator` column renders a
  colour-only **dot in its own cell** (the value is a tone name or blank), for orthogonal
  green/amber/red signals per row that each want an at-a-glance column.

  ```yaml
  - { key: access, label: "Access", kind: badge, placement: cell, width: 1 }
  # row: { name: "Supplier ledger", access: [WRITE, PARTNER], … }   # two chips in one cell
  ```
- **Column widths** are automatic by default. To set proportions, give every in-cell column a
  `width` weight (1 to 6): each takes `width / Σwidth` (e.g. `4` + `2` → two-thirds / one-third).
  It's all-or-none: set `width` on every in-cell column or none. A `placement: title` badge takes
  no width (it rides under the title); a `placement: cell` badge is a normal column and does.
- **Column tone.** A column may set `tone` (any tone name, or its palette alias) to tint the whole column faintly, for example a variance column that needs the reader's eye: `{ key: variance, label: "Variance", kind: number, tone: warning }`. The header and group bands stay untinted. A row `tone` or a `tint_by` row tint paints over the column tint, so a flagged row reads as one unbroken band. A `placement: title` badge column takes no tone.
- **Every row supplies every column key and nothing else** (plus an optional `subrows`, and an
  optional `tone: muted | danger`). A row `tone` emphasises the whole row: `muted` dims and strikes
  it (a rejected/superseded row), `danger` tints it red (a bad row).
- **Compact rows.** For a dense, data-heavy table, write a row as a **positional list** of values in
  column order instead of a mapping, with no repeated keys:

  ```yaml
  - type: table
    columns: [{key: issue, label: "Discrepancy"}, {key: tag, label: "", kind: badge}, {key: n, label: "Units", kind: number}]
    rows:
      - [Double-counted units, FLOOR, 600]     # positional: values in column order
      - {issue: Complex, tag: FLOOR, n: 10, subrows: [{label: "bin > 12", value: 4}]}   # still a mapping, mix freely
  ```

  A list row must have exactly one value per column (a length mismatch fails the build). Types and
  list cells (a `placement: cell` badge column's `[KEY, KEY]`) work the same as in a mapping; a row
  that needs `subrows` or `tone` stays a mapping (a list has no slot for them).
- **`reconcile`** is the trust check: the column sum, plus any `handled` bucket, must equal
  `total` or the build fails naming the delta. With `pct_of_total` on a number column, each cell
  also shows its share of the reconcile total. `pct_of_total` is defined **only** against a
  `reconcile` total. It has no meaning against a plain `totals` sum, so a table that sets
  `pct_of_total` without a `reconcile` is rejected at build time (add a `reconcile`, or drop the flag).
  It is also rejected on a column that is not a `number` column, which has no share to show.
- **`totals`** adds a bold footer summing a number column (for tables that aren't reconciled).
- **`rollup`** (`{ by: <badge-column-key>, label? }`) adds a summary strip below the table that
  counts the rows by that badge column, one `<chip> <count>` per value (in first-appearance order).
  The counts are **derived from the rows**, so they can't drift the way a hand-typed summary would;
  `by` must name a `badge` column, and each row counts under one badge, so a rollup over an in-cell
  badge column whose cells hold a list of keys is rejected.
- **`tint_by`** (`<badge-column-key>`) faintly tints each row by the tone of the badge in that
  column, so a long table reads as bands of colour (a lightweight heatmap). You name the column;
  skaldr owns the intensity. A row left blank there stays untinted, and an explicit row `tone`
  (`muted`/`danger`) wins over the tint. Must name a `badge` column; the same column can still show
  its chip. Each row takes one badge's tone, so a `tint_by` over an in-cell badge column whose cells
  hold a list of keys is rejected, as a `rollup` over one is.
- A group with an empty `rows: []` renders a "none" row, so an empty section reads as
  intentional. Group bands show a subtotal of the reconcile/totals column.

## Reusing fragments: `!include`

Pull a chunk of YAML in from another file with `!include <path>`. The referenced file is parsed and
spliced in where the tag sits, so it works for a whole list or a single node:

```yaml
badges: !include shared/badges.yaml   # a shared vocabulary across several reports
blocks:
  - !include shared/legend-block.yaml # one reused block
  - type: text
    body: "…the rest, inline."
```

Paths resolve relative to the file doing the including (not your shell's directory), so a set of
fragments can move as a unit. Includes can nest; a file that includes itself (directly or through a
chain) fails the build rather than looping. A missing fragment fails with the path that named it.
`--check` and `--emit-json` resolve includes too, so validating a top file validates everything it
pulls in, and the emitted JSON is fully flattened.

## Index documents: one page from several

Several small reports that belong together, such as the chapters of a review, read better as one page. An index document builds that page from the other files without copying them:

```yaml
version: 1                    # an index document
meta: { title: "Platform review", toc: true }
index:
  parts: [01-overview.skaldr.yaml, 02-findings.skaldr.yaml, 03-plan.skaldr.yaml]
blocks:                       # optional: an intro shown before the first part
  - type: text
    body: "Three reviews, read in order."
```

- **Parts** are paths relative to the index file. Each part stays a normal skaldr document that still builds alone; an index never edits it.
- **Each part becomes a part of the page**: its `meta.title` is the part's title, a level 1 heading in the exports and a title band in the HTML, and its blocks follow unchanged. The table of contents lists the index's own headings and sections, then one entry per part. The rest of a part's `meta` (subtitle, source, date, updated, toc and the other options) applies only when the part builds alone; the page takes its header, footer and options from the index's `meta`.
- **`collapsed: true`** under `index` starts every part collapsed: a collapsible in the HTML, a toggle heading in the Notion export. Parts are open by default.
- **Badges merge.** The index's `badges` and every part's `badges` combine into one vocabulary and one legend, shown at the top of the page unless the index's own blocks hold a table. A key declared with a different label, tone or legend in two files fails the build naming both files; rename one key or make them agree.
- **People and the Jira site merge.** The index's `meta.people` and every part's combine, so a part's `[Ada](user:ada)` resolves on the combined page. A key declared with different ids in two files fails the build naming both, and so do two different `meta.jira_site` addresses.
- **Ids are page-wide.** A heading, section, table or matrix id, a reference key or a request label repeated across two parts fails like a repeat inside one file, and the error names the file behind each part it points at. A file listed twice is refused.
- The rendered page is the combined page, and `--export notion` writes one `page.md` for it. `--if-stale` and `--watch` follow every part file and every file a part includes, so an edit to a part rebuilds the index. While a part cannot be read, `--watch` keeps following the files it last found.
- `--emit-json` prints the combined page, with every part already in place and no `index` key. It is a view of the page, not a source file: building it again is refused, because its `part` blocks were not built by an index. The source embedded in the rendered page is the index file alone, as with `!include`; keep the part files beside it.
- A part cannot be an index itself, and `index` takes only `layout: one_page` for now. An index document cannot carry `publish` yet, and a part's own `publish` block is left out of the combined page; publish each part file on its own.
- `part` is the block an index builds; it is not written by hand, and the build refuses one outside an index. To group content inside one file, use a `section` or a `heading`.

## Where it publishes: `publish`

An optional top-level `publish` block says where the document is meant to live outside skaldr: Notion pages, Jira issues and Slack canvases. skaldr reads the block, validates it, and keeps it out of the source a rendered page embeds. The block changes nothing about what a render or an export does; the `skaldr publish`, `skaldr diff` and `skaldr status` commands read it (see Publishing below). `skaldr auth` keeps one sign-in per Jira site, per Notion workspace and per Slack workspace (`skaldr auth status` lists them, `skaldr auth logout jira <site>`, `skaldr auth logout notion <workspace>` and `skaldr auth logout slack <workspace>` remove one), so a second site or workspace never replaces the first. `where` has a different shape for each service; the other keys mean the same thing everywhere.

```yaml
publish:
  doc_id: onboarding-plan            # the document's identity in every target
  targets:
    - to: notion
      where: { parent_page: "https://www.notion.so/Team-Plans-0123456789abcdef0123456789abcdef" }
      split: [st1, st2]              # each named top-level section becomes its own child page
    - to: jira
      where: { project: PLAN, issue_type: Task, parent: PLAN-100, fields: { labels: [onboarding] } }
      from: [st1, st2]               # build this target from these sections only
      split: [st1, st2]              # one child issue per section
      overrides: { st2: { fields: { priority: { name: High } } } }
    - to: slack
      where: { conversation: C0EXAMPLE1 }   # share each new canvas with this channel and post the document's link there
```

| Key | Meaning |
| --- | --- |
| `doc_id` | At least two characters: lowercase letters and digits joined by single hyphens. |
| `to` | `notion`, `jira` or `slack`. |
| `where` (Notion) | Exactly one of `parent_page` (create the document under it) or `page` (write into it), each a Notion page URL or page id, plus `fields` for database properties when the page is a database row. |
| `where` (Jira) | A `project` key, an `issue_type`, an optional `parent` issue key, and `fields` for labels, priority, components and custom fields. |
| `where` (Slack) | Optional: at most one of `conversation` (a channel or DM that can read each new canvas and where the document's canvas link is posted) or `canvas` (an existing canvas to write into), each an id or a Slack link, plus `workspace`. `canvas` and `workspace` are the target's place; `conversation` is not. A canvas has no fields, so a Slack target takes no `fields`. |
| `from` | Top-level section ids the target is built from; the content keeps document order. Left out: the whole document. |
| `split` | Top-level section ids that each become a child page or child issue; everything else stays on the document's own page or issue. Left out: one item for the whole document. |
| `overrides` | Per-item `fields`, keyed by a split section id; each key it names replaces that key of `where.fields` whole. |

`skaldr --check` holds the block to these rules and names the target in every message:

- every id in `from` and `split` names exactly one top-level `section` by its `id:` (a heading id or a title does not count), appears once in its list, and no two top-level sections share an id;
- every `split` id sits inside `from` when `from` is given, and every `overrides` key is a `split` id;
- a Notion page is a URL on notion.so, notion.site or notion.com, or a page id; a Jira project key is an uppercase letter followed by uppercase letters, digits or `_`, a `parent` is an issue key such as `PLAN-100`, and `issue_type` is not blank; a Slack `conversation` is a channel or DM id (`C...`, `G...` or `D...`) or a slack.com link to it (`/archives/<id>`, with or without a message after it, or `/client/<team id>/<id>`), and a Slack `canvas` is a canvas id (`F...`) or a canvas link (`/docs/<team id>/<canvas id>`), so a link to another kind of file is refused;
- no two targets write to the same place: the same Notion page id, whether given as `parent_page` or `page` and however it is written, the same Jira project and parent issue, or the same Slack canvas (two Slack targets that name no canvas share a place too, whatever conversations they name);
- with the publish extra installed, each item a target would write holds no block the target cannot show and fits the service's size limit: `--check` drafts every target as `skaldr publish` does before it sends anything, a Jira target as `--export adf`, a Notion target as `--export notion` and a Slack target as `--export slack` (see *Exporting as ADF for Jira*), so it refuses what that publish would refuse.

A rendered page embeds its source **without** the `publish` block: the block, the comment and blank lines between it and the previous key's content, and every line up to the next top-level key are left out, so a shared page never shows where the document publishes. A comment anywhere else stays, so keep ids out of other comments. The render stops with an error rather than embed a block it cannot cut out exactly, such as one reached through a `<<` merge key or one whose YAML anchor another key uses. To keep the ids out of a public repo entirely, write `publish: !include publish.private.yaml`.

## Publishing

This version of skaldr publishes to Notion, Jira and Slack (see Publishing to Notion, Publishing to Jira and Publishing to Slack below). What follows is how the commands behave for every service.

```bash
skaldr publish garden.yaml                      # dry run: reads the services, prints the plan, writes nothing
skaldr publish garden.yaml --apply              # publishes; stops with a diff if an item was edited in the service
skaldr publish garden.yaml --apply --overwrite  # replaces the remote edits the last diff showed
skaldr diff garden.yaml                         # remote edits since the last publish, then what the YAML would change
skaldr diff garden.yaml --json                  # the same facts as JSON
skaldr status garden.yaml                       # per item: in sync, edited remotely, changed in the YAML, removed, missing remotely, never published
```

**The plan.** `skaldr publish garden.yaml` prints, for each target, the items it would create, then each item's updates (its title, fields, icon and cover, each section it writes, and each section it removes from the item), then the items it would archive or release. For a document that publishes to Notion and to Jira, it then lists each link it would add or remove between a page and an issue (see Links between Notion and Jira below). `--apply` carries the plan out one step at a time and prints each step as it lands.

The dry run reads every service the document publishes to, with your stored sign-in, and never writes to a service or to the state file. It reads each item skaldr published and the page a target writes into, so its plan is the one `--apply` would carry out. When `--apply` would not go ahead, the dry run says so and exits with status 1: after remote edits it prints each edit and `error: --apply would stop: ...`, and for any other reason (a stamp from another document, a page that already holds content, an item missing in the service, an interrupted create) it prints `error: --apply would refuse: ...` with the reason.

```text
notion page 0123456789abcdef0123456789abcdef: 1 to create, 3 to update, 1 to archive
  create   section planting "Planting"
  update   document: fields
  update   document: watering (blocks[1])
  remove   document: page legend
  archive  section tools (page-2)
```

A Notion page takes one write per changed section. A connector that can only replace an item's whole content, such as a Jira description, takes one write per changed item instead, and the plan lists every section that write changes on one line.

**Links between Notion and Jira.** When a document publishes to a Notion target and to a Jira target, the page and the issue that hold the same part of the document link to each other: the document's page and the document's issue, and a split section's page and issue when both targets split that section. A section split in one target and not in the other has no pair, so it gets no link. With two targets of one service, an item links to the matching item of each target of the other service. The issue gets a remote link to the page, listed under the issue's web links and titled with the page's title, or with the page's id when the title is blank. The page's stamp names the issue after its usual text, as a link to the issue at `<site>/browse/<key>`: `Published with skaldr from document onboarding-plan, section st2 · Jira [PLAN-12](https://example.atlassian.net/browse/PLAN-12)` in the page's Markdown, which Notion shows as `... section st2 · Jira PLAN-12`. A page published by an older skaldr has a stamp without links, and skaldr reads it as before. A Slack target pairs the same way with the other two: the canvas's stamp names the paired page and issue as links (`Published with skaldr from document onboarding-plan · Notion [Onboarding plan](https://www.notion.so/0123456789abcdef0123456789abcdef) · Jira [PLAN-12](https://example.atlassian.net/browse/PLAN-12)`), the page's stamp names the canvas after the issue (`· Slack [Onboarding plan](https://example.slack.com/docs/T0EXAMPLE1/F0EXAMPLE1)`), and the issue gets a remote link to the canvas with the `globalId` `skaldr:<doc_id>:document:slack:<canvas id>`. Within one Slack target, the document's canvas also names each `split` section's canvas in its stamp, after the Notion and Jira links, so the canvases of one document link from one place. skaldr writes the links last, once every item of the run exists, so a first publish creates each page and issue and then links them. A link is not content: it never counts as a remote edit and is never shown in `skaldr diff`. A link removed or changed by hand is written again by the next `--apply`, and a run where every link is already in place writes nothing. skaldr knows each link by the service and the id of the item it points to, so a link whose address or title was changed by hand is one link step that puts it back in place, not an unlink and a link. A pair ends when a target or a section leaves the YAML or its `split`, or when an item is archived or released: skaldr then deletes the issue's remote link to the page and drops the issue from the page's stamp. Archiving an issue deletes the remote links skaldr put on it; a remote link skaldr did not write is left alone. The plan lists the link changes after the targets: a link step names the target and the item it links to, and an unlink step names the service and the title of the link it removes:

```text
links: 2 to link, 1 to unlink
  notion page 0123456789abcdef0123456789abcdef: link     section st2 to jira project PLAN under PLAN-100, section st2
  jira project PLAN under PLAN-100: link     section st2 to notion page 0123456789abcdef0123456789abcdef, section st2
  notion page 0123456789abcdef0123456789abcdef: unlink   section st3 from Jira PLAN-14
```

**What goes where.** The document's own page or issue holds the subtitle, the table of contents, every top-level block that `from` keeps and `split` does not take, and the footer. A split section's page or issue holds that section alone, titled by it. Only the document's item has a table of contents. Each item has its own badge legend, listing only the badges that item uses, placed before its first top-level table as on the HTML page. Within an item, each top-level block is a section of its own for updates: a `section` by its `id`, a heading by its anchor, any other block by its content (a short hash of the block as the YAML parser reads it, so anchors, merge keys, quoting and key order do not change it, with a `#2` suffix for a second identical block), plus the `page header`, `page legend` and `page footer`. So adding or deleting a block writes only that block, and changing the text of a block that has no id, or of a heading (whose anchor follows its text), writes it as one block added and one removed. A newer skaldr keys the same YAML the same way. Publishing again writes only the sections whose text changed and leaves the rest of the item as it is. A section that moved is written again at its new place, and a section that left the item is removed from it. An item whose section left the YAML or the `split` list is archived, and so is every item of a target removed from the `publish` block. Lists of plain values (labels, components, numbers) and the keys of field values compare as sorted sets, so `[seeds, soil]` and `[soil, seeds]` are the same value and reordering them publishes nothing; a list of objects or of lists keeps its order. skaldr owns only the fields it has published: only those are compared for remote edits, so a field the service or a person sets that skaldr never published (a Jira board or sprint, say) never counts as a remote edit and is never cleared, even by `--overwrite`. A field newly added to the YAML is written over whatever the service holds, without counting that value as an edit. Removing a field from the YAML clears it in the service. An empty value (null, an empty string, list or object) is the same as no value, so a service that reads a cleared field back as null, or drops an empty one, causes no change. `fields` from `where` apply to every item. A split section's `overrides` replace them key by key: a key the override names takes the override's value whole (a `labels` list in an override replaces the `labels` of `where`, it does not add to it), and every other key keeps the value from `where`. skaldr's own stamp of the `doc_id` is not a field, so no override can remove it.

**The state file.** `--apply` keeps a state file next to the YAML: `garden.skaldr-state.json` for `garden.yaml`. It records each page and issue skaldr made, with its id, the text skaldr last rendered for each section, the copy the service returned right after skaldr's write, a marker the connector uses to spot later edits, and the links skaldr last wrote on it. To find remote edits, skaldr puts that copy and the item it reads now in the connector's current formatting before comparing them, and `skaldr diff` shows both that way. A newer skaldr that formats an item differently therefore does not report every item published before the upgrade as edited remotely. `skaldr diff` updates the state file too, to remember which remote edits it showed you. skaldr writes it whole to a new file beside it, flushes that to disk and only then puts it in place, so a crash never leaves half a file; a folder skaldr cannot write to stops the run before anything is sent. While `--apply` or `skaldr diff` runs, it holds `garden.skaldr-state.json.lock`, and it reads the state file and the YAML only once it holds the lock, so it always plans from what the previous run left. A second run on the same document stops at once, naming the command it blocked, instead of racing the first.

skaldr saves the state after every step and notes each write, archive and release before sending it, so a run that stops halfway, for example on a network error, carries on from the failed step when you run it again. On the next run, each part of an interrupted write that the service now holds exactly as skaldr was writing it (compared in the service's own formatting) is recorded as published, even when someone also edited another part of the item; the parts that did not land are written again, and only the other changes count as remote edits. Notion, Jira and Slack write a part in one request (Slack sends one request that replaces the canvas body), so there any other state of a part is a remote edit. An interrupted archive or release whose item is already archived, gone, or released (unstamped, with no content and none of the fields, icon or cover skaldr set) is simply forgotten; otherwise it is sent again, without checking the item for edits, since the document no longer holds it. If the section comes back into the YAML before that, skaldr tracks the item again as usual. A write the service rejected outright leaves no trace and is tried again on the next run. `--apply` plans again once it holds the lock and stops if the YAML changed after the plan was made.

A create is different: if a run stops while creating a page or issue and the service's answer never arrived, skaldr cannot tell whether it was made, so the next `--apply` stops and names the parent and the title to look for, rather than risk creating it twice. Archive the item if it is there, delete its entry from `pending_creates` in the state file, and publish again. When the service did answer with the new item's id and only a later step failed (reading it back, for example), skaldr notes that id in the entry, and the next run reads the item: if it carries this document's stamp, or no stamp skaldr can read, skaldr records it as created and carries on (a missing stamp goes back with the next write); if it is stamped for another document, the run stops naming it and keeps the entry; and if it is gone, skaldr creates it again. Writing into a page that a target names with `page` resolves itself, even if the target has since left the `publish` block: if the page carries this document's stamp, skaldr records it as adopted, and if it is unstamped but empty, or holds exactly what skaldr was writing, skaldr writes into it again. Every item skaldr creates is stamped with the `doc_id` and the id of the section it holds, so a later version of skaldr can find such an item by itself.

Keep the file: without it skaldr no longer knows which items it made. It names pages and issues by id, so in a public repository add `*.skaldr-state.json` and `*.skaldr-state.json.lock` to `.gitignore` and keep a copy of the state file elsewhere. A state file that records another `doc_id` is refused; the usual cause is a changed `doc_id`, so change it back. A target in the state file that this version of skaldr cannot read stops the run with an error before anything is written.

**Only what this document owns.** skaldr writes only to items in the state file and to the page a Notion target names in `page`. Every one of them is read before the first write, and an item stamped with another document's `doc_id` stops the run, naming both documents, before anything is sent.

A page that a target names with `page` was not made by skaldr, so skaldr writes into it only while it is empty: a page that already holds content, child pages or properties the service reports as set, and carries no skaldr stamp, is refused, naming it. In the state file and in every message, such a target reads as `notion page <id> (written into)`. The state file records such a page as adopted, and skaldr never archives it. When its target leaves the `publish` block, skaldr releases it instead: it clears what skaldr wrote and removes the stamp, leaving the page itself in place. Every item skaldr created is archived as before.

**Moved targets.** A target is known by its place: the Notion `parent_page`, or the Notion `page` it writes into (so switching one page between `parent_page` and `page` is a move too), or the Jira `project` and `parent`. When a target's place changes, skaldr does not move pages or issues: `--apply` stops before writing anything, naming the old place and the new one, and the dry run says it would. `skaldr diff` and `skaldr status` still run, showing the old target's items as removed and the new target's as never published. To move, publish once with the old target removed from the `publish` block, which archives the items skaldr created there and releases any page it wrote into, then add the new target and publish again. A target removed from the block with no new target for the same service in its place is not a move: its created items are archived and an adopted page is released.

**Retiring a document.** To stop publishing a document, keep its `doc_id` and set `targets: []`. The plan, `--apply`, `skaldr diff` and `skaldr status` then treat every target as removed: the dry run lists an archive for each item skaldr created and a release for each page it wrote into, `--apply` carries them out, `diff` and `status` show every item as removed, and afterwards the state file holds no targets. Publishing again then prints `Nothing to publish`. A document with `targets: []` and no state file has nothing published, so the dry run and `--apply` say so and send nothing. An empty list is not a move.

**Items deleted in the service.** An item skaldr published that is no longer in the service shows as missing remotely in `skaldr status`, and under "Missing remotely" in `skaldr diff` (`missing_remotely` in `--json`). `--apply` stops, naming it. `--apply --overwrite` creates it again under its parent and records its new id, or forgets it when the YAML no longer has it. A page a target wrote into cannot be created again: `--apply --overwrite` stops, naming the page, so name an existing empty page or publish under one with `parent_page`.

**Edits made in the service.** Before writing, skaldr reads every item it published and compares the service's copy now with the copy the service returned right after skaldr's last write, so formatting the service adds is never mistaken for an edit; a connector can also report an edit the text does not show. When an item was edited, `--apply` writes nothing, prints each edited part as a unified diff and exits with status 1. Then choose: leave it, copy the edit into the YAML, or replace it with `--apply --overwrite`, which writes the YAML's content over exactly the edits the last diff showed, whether that diff came from `--apply` or from `skaldr diff`. If the item changed again after that diff, or no diff has shown the edit yet, `--overwrite` writes nothing either and prints the new diff, so an edit you have not seen is never overwritten.

```text
--- notion page 0123456789abcdef0123456789abcdef, document: planting (blocks[2]), as published
+++ notion page 0123456789abcdef0123456789abcdef, document: planting (blocks[2]), now
@@ -1,2 +1,2 @@
 ## Planting
-Sow in spring.
+Sow in late spring.
error: 1 part was edited in the service since the last publish, so nothing was written. To keep the edit, copy it into the YAML first; to replace it, publish with --apply --overwrite.
```

**`skaldr diff --json`** prints three lists, `remote_edits`, `yaml_changes` and `missing_remotely` (each missing item's `target`, `item` and `item_id`). Each entry names its `target`, `item` (`document` or `section <id>`), `part` (`section`, `title`, `fields`, `icon` or `cover`), `section` id, `yaml_path` and the `published` text; a remote edit adds the `current` text and, when the service says, `edited_by` and `edited_at`; a YAML change adds the `next` text. An item never published shows `null` as its published text, and an item the YAML removed shows `null` as its next text.

**Limits.** A connector can declare a limit on a section or on a whole item, such as a character count. Content over it stops the plan before anything is sent, naming the target, the item, the section and the limit, and suggesting a further `split`.

### Publishing to Notion

**Sign-in.** Sign in once with `skaldr auth notion`; `skaldr publish`, `diff` and `status` use that sign-in, or `NOTION_ACCESS_TOKEN` when it is set. When several Notion workspaces are signed in, a Notion target names the one it publishes with in `where: { workspace: "Team Space" }`, by workspace id or name (the same selectors `skaldr auth logout notion` takes); without it the commands stop and ask for one, and a `workspace` that matches no sign-in stops them listing the signed-in workspaces. A name that two signed-in workspaces share stops them too, listing each with its id, so name one by its id. `workspace` is not part of the target's place, so changing it is not a move. In Notion, give your connection access to the page a target names, from that page's menu under Connections; a page the connection cannot see reads as missing. The dry run of a document never published reads nothing, so a missing sign-in shows only when skaldr first needs Notion: `--apply` then stops before sending anything and says to run `skaldr auth notion`. Notion's tokens carry no expiry, so when Notion refuses the token, skaldr first looks in the keychain: if another skaldr command has stored a newer token meanwhile, it sends the request again with that one. Otherwise, or when Notion refuses that token too, skaldr renews the sign-in once with the stored refresh token, saves the new token in the keychain and sends the request again; if Notion refuses the refresh token but the keychain holds a newer one, skaldr renews with that instead. If Notion still refuses, run `skaldr auth notion` again. If the keychain cannot save the renewed token, for example because it is locked or does not answer in time, the command stops and says to run `skaldr auth notion` again, since Notion may already have retired the stored refresh token. A dry run renews and saves the sign-in the same way: renewing changes the keychain, never the document, and Notion may retire the old refresh token once it issues a new one. A token from `NOTION_ACCESS_TOKEN` is never renewed: set a current one.

**`parent_page` or `page`.** With `parent_page`, skaldr creates the document as a new page under that page. When `parent_page` names a Notion database (with one data source), the document becomes a row of it, and `fields` set the row's properties by name, each in the shape of its kind: a text for a text, URL, email or phone property, a number, an option name for a select or status, a list of names for a multi-select, a date as `2026-10-01` or `{start: 2026-03-01, end: 2026-05-31}`, `true` or `false` for a checkbox, and a list of user ids or page ids for people or a relation. The title property comes from the document's title, never from `fields`, and files, formulas and other computed properties cannot be set. A value a property cannot take, or a property the database does not have, stops the create before anything is sent, naming the property. Split sections become child pages of the document's page, and a page under a page has no properties: a field that reaches one stops the publish naming it, so clear it for that section with `overrides: { st2: { fields: { Status: null } } }`. With `page`, skaldr writes into an existing page, such as a database row, while it is empty (see above), and `fields` set that page's own properties.

**What lands where.** A page's title is the document's title, or the split section's title. Its body is the item's Notion Markdown (the same text `--export notion` writes for it), and its last line is a gray stamp, `Published with skaldr from document onboarding-plan, section st2` (no section for the document's own page), which is how skaldr recognises its pages. When the document also publishes to Jira, the stamp goes on to name the paired issues, each as a link (see Links between Notion and Jira). Everything below the stamp belongs to the people using the page: Notion lists new child pages there, and text written below the stamp is never compared, rewritten or removed. If the stamp is deleted, skaldr puts it back at the end of the page the next time it writes to the page: a section, the content, the title, the fields, the icon or the cover. A child page someone moves up into the page stays where it is: it belongs to the section around it but is not part of its text, and a rewrite of that section keeps it in place. Each changed section is one search-and-replace of that section's current text, so a comment on text skaldr does not rewrite stays attached; a comment on a section skaldr rewrites is detached, and Notion keeps it in its sidebar. A new section is placed with the shortest stretch of its neighbour that appears once on the page, preferring lines that carry no comment, so the neighbour's comments stay attached; a section that moved rewrites the sections between its old and its new place in the same request. A section holding a block Notion cannot show as Markdown (a bookmark or an embed, which Notion shows as an `<unknown>` tag) is never rewritten: a write to that section stops, naming the section, until that block is changed or removed in Notion. A release keeps such a block and never quotes it, so it does not stop a release. The title, fields, icon and cover go in one page update. A remote edit is a change to the Markdown of a section skaldr published, to the title, to a field skaldr set, or to an icon or cover the YAML sets; comment markers, Notion's own indentation inside tables and indented code blocks, blank lines, and an empty block someone adds at the end of a section do not count. A remote edit names the person Notion says last edited the page: by name when the connection may read user information (Notion's "Read user information" capability), and by user id when it may not; skaldr asks Notion once per person in a run. Archiving moves the page to Notion's trash, where it can be restored. Releasing a page removes each block skaldr published that nobody has edited, and its stamp, in as many requests as the page needs; it keeps text people added, child pages, and any table, code block or other block in which a person changed a line, whole. It then clears the fields, icon and cover skaldr set, in one page update.

**Icon and cover.** `meta.icon` is the icon of the document's page and of every split section's page, sent as a Notion emoji icon (`{"type": "emoji", "emoji": "🧪"}`). `meta.cover` is the cover of the document's page only, sent as an external image Notion loads from that address (`{"type": "external", "external": {"url": "https://example.com/cover.png"}}`); a split section's page gets no cover. skaldr sets them when it creates a page or writes into one with `page`, and changes them with a page update when they change in the YAML. Removing `icon` or `cover` from the YAML clears it in Notion. An icon or cover the YAML does not set belongs to the people using the page, as a field skaldr never published does: skaldr never compares, replaces or clears it, and a page `page` names keeps the icon and cover it already has. Once the YAML sets one, a person changing or removing it in Notion is a remote edit, and the diff shows it as the emoji or address, as `Notion icon <name> (<color>)` for one of Notion's own icons, as `Notion custom emoji <id>`, or as `a file uploaded to Notion (<address>)`. Notion signs an uploaded file's address again each time the page is read, so skaldr compares that address without its query string: a new signature for the same file is not an edit, and swapping one uploaded file for another is. Adding an icon or cover to the YAML writes it over one a person set, without counting that as an edit. A release clears an icon or cover the YAML set, as it clears the fields skaldr set, and leaves one skaldr never set.

**Notion's limits.** One request creates at most 5,000 blocks and stays under 450,000 bytes of JSON, so a page larger than that is created with the sections that fit and filled in by further requests that each add whole sections before the stamp. skaldr never splits a section, so a table always stays one table. A section that alone takes more than 4,999 Notion blocks or 200,000 bytes of JSON stops the plan before anything is sent, naming the section; give it its own page with `split`, or shorten it. A write that quotes more than one section, such as a move, is held to the same 450,000 bytes and 5,000 blocks per request, counting the old text and the new, and is refused before it is sent, naming the sections it quotes. Notion also limits how large a page may be after an update and refuses a larger one; the error says so, and the cure is the same: move sections into child pages with `split`. A request Notion rate-limits (429) or finds overloaded (529) is tried again, and so is a read that fails with another 5xx or cannot reach Notion (a timeout or a dropped connection), up to six attempts in all, waiting as long as Notion's `Retry-After` asks or, without one, a random part of a backoff that doubles from one second up to 30, so several runs do not retry in step. When `Retry-After` asks for more than a minute, on any request skaldr would try again, skaldr stops instead, naming the wait. A write that fails with any other 5xx, or whose answer never arrives, is not repeated, because it may have landed, and neither is a create Notion accepted for later whose progress skaldr then cannot follow. For a section write, the next run reads the page and carries on from there, and so does a target that writes into a `page`. A create under `parent_page` that stops this way is an interrupted create: the next `--apply` stops and names the parent and the title to look for (see the state file above).

### Publishing to Jira

**Sign in once.** Run `skaldr auth jira`: it asks for your Jira Cloud site (`https://example.atlassian.net`), your Atlassian account email and an API token you create at id.atlassian.com under Security, API tokens, checks them against the site and keeps them in the system keychain. In CI, set `JIRA_SITE`, `JIRA_EMAIL` and `JIRA_API_TOKEN` (all three) instead; they win over the keychain. skaldr publishes with your one Jira sign-in; if you are signed in to more than one site, name the site this target publishes to with `site` in its `where` (an https site URL, written the way `skaldr auth` takes it), which is part of the target's place, so changing it is a move. Every issue skaldr creates or edits is created or edited by you, and Jira notifies watchers as it does for your own edits.

```yaml
publish:
  doc_id: garden-handbook
  targets:
    - to: jira
      where:
        project: DEMO
        issue_type: Task
        parent: DEMO-100                  # optional: the document's issue goes under it
        fields:
          labels: [garden]
          priority: { name: High }
          components: [{ name: Beds }]
          customfield_10010: 3            # a custom field, by its id
      split: [tools, planting]            # each becomes its own issue under the document's issue
      overrides: { planting: { fields: { priority: { name: Low } } } }
```

**`where`.** `project` is the project key and `issue_type` the issue type every created issue gets (a name such as Task or Story). `parent` puts the document's issue under an existing issue; each `split` section becomes an issue whose parent is the document's issue, so the issue type has to be one your project lets sit under that parent. `fields` holds any other field of a Jira create screen, keyed by the field's id as Jira's REST API names it (`labels`, `priority`, `components`, `duedate`, `customfield_10010`) and written in the shape that API takes: a priority is `{ name: High }`, components are a list of `{ name: ... }`, a select option is `{ value: ... }`, a person is `{ accountId: ... }`. skaldr compares each field in the shape you wrote it, so the extra keys Jira adds when it reads a field back (`self`, `id`, `iconUrl`) never count as an edit. A field Jira does not know, or a value it refuses, stops the run with Jira's own message, naming the field. `fields` and `overrides` may not set `summary`, `description`, `project`, `issuetype`, `parent` or `status`: skaldr sets the first five itself, and Jira changes a status only through a transition, so `skaldr --check` refuses them, naming the target and where they were set. `labels` is allowed, and skaldr adds its own label to yours.

**What lands where.** The summary is the item's title. The description is the item's content in the Atlassian Document Format that `--export adf` writes (see Exporting as ADF for Jira). The labels are yours plus `skaldr-<doc_id>`, which skaldr keeps on every issue it publishes and leaves out when it compares labels. The prefix goes on every `doc_id`, one that already starts with `skaldr-` included (`skaldr-skaldr-plan`), so no two documents share a label. Two issue properties, which Jira stores with the issue and does not show, carry the rest: `skaldr.stamp` holds the `doc_id` and the section id, and `skaldr.layout` records which section each part of the description came from, so skaldr can tell later which section an edit touched. A `skaldr.stamp` that skaldr cannot read, such as one edited through the REST API, stops the run naming the issue, since skaldr cannot tell which document the issue belongs to; a `skaldr.layout` it cannot read only makes the whole description one section until the next write records it again. When the document also publishes to Notion, the issue has a remote link to each paired page (see Links between Notion and Jira). Its `globalId` is `skaldr:<doc_id>:document:notion:<page id>` for the document's issue and `skaldr:<doc_id>:section:<section id>:notion:<page id>` for a split section's, so publishing again updates that link instead of adding a second one. Writing the links to an issue whose `skaldr.stamp` is gone puts the stamp back first, as a write to a Notion page puts back its stamp line, and an issue stamped for another document or section is never linked. A `globalId` can be longer than the 255 characters Jira takes only through a long `doc_id` or section id, so skaldr measures it from those before anything is sent, counting the page id as the 32 characters skaldr stores it in, without dashes, so a `globalId` of exactly 255 characters is written: the dry run refuses one longer, and `--apply` stops before its first write, naming the target and the item; shorten the `doc_id` or the section's id.

**Updates.** A description is one field in Jira and cannot be changed in part, so when any section of an item changes, skaldr replaces the item's whole description in one request, and leaves it alone when nothing in it changed. The summary and the fields go in one request holding only the ones that changed; a field removed from the YAML is cleared. A rate-limited request is sent again after the wait Jira asks for (up to a minute), and a read that fails on Jira's side is tried again after 2, 4 and 8 seconds, or after the wait Jira asks for when it names one; when Jira asks for more than a minute, skaldr stops instead of waiting; a write that fails on Jira's side is never sent twice, since it may have landed.

**Edits made in Jira.** skaldr reads each issue's history after every write and remembers its own entry for that write. An entry after it that changes the summary, the description, the labels (when the YAML sets `labels`) or a field the YAML sets is an edit made in Jira when the issue no longer holds what skaldr published there, and `skaldr diff` shows it under the section, the title or the fields it changed, with who made it and when. An edit undone in Jira before the next publish is therefore not an edit. Comments, status changes and fields the YAML does not set are not edits. Since skaldr writes as you, an edit you make yourself in Jira counts too. Sections moved around in Jira keep their own text, but the new order counts as an edit to the moved sections.

Right before each write, skaldr reads the issue's history again: an edit made since skaldr read the issue earlier in the run stops that write before it is sent. An edit that lands while skaldr writes, between its request and its read-back, stops the run after the write with `<issue> was edited in Jira while skaldr wrote to it (<fields>)`; the next `skaldr publish` or `skaldr diff` shows that edit, and the parts skaldr wrote count as published. An edit to the same field that lands in the instant before skaldr's write is replaced by it; the run then stops with `<issue>: skaldr's write replaced an edit made in Jira just before it (<field> in changelog <id> by <person> at <time>)`, so you can restore it from the issue's history. When the history holds only skaldr's own entry, or a new issue's history holds no entry yet, skaldr takes the issue as Jira saved it as the published copy, even where Jira stored skaldr's text in a slightly different form. A mention compares by the person's account id alone, because Jira rewrites a mention's text to the person's current display name when it saves the issue; a mention that points at another person counts as an edit, and changing only the text of a `[text](user:key)` link publishes nothing.

**The description limit.** Jira takes at most 32,767 characters of description, counted on the compact ADF JSON. An item over that stops the plan before anything is sent, naming the item and its size:

```text
error: jira project DEMO under no parent issue, document: the item has 40,112 characters of ADF, over the 32,767 a Jira item can take; split the document further with `split`, or shorten it
```

skaldr never cuts a description short: move sections into their own issues with `split`.

**Archiving.** skaldr never deletes an issue. An item whose section left the YAML or the `split` list is archived: skaldr deletes the remote links it put on the issue, adds a comment saying it archived the issue, moves the issue to a status in Jira's done category (by any transition the workflow offers to one), and marks its `skaldr.stamp` as archived, after which skaldr treats the issue as gone. `skaldr.stamp` also records whether skaldr has put remote links on the issue, so archiving an issue that never held one asks Jira for no remote links, and a remote link already gone when skaldr deletes it does not stop the archive. skaldr notes the comment in `skaldr.stamp`, so if the transition fails, for example on a workflow rule that wants a resolution, publishing again retries the transition without commenting a second time. Before it adds the comment, skaldr looks for the same comment among the issue's comments, so a run that stopped after commenting and before noting it does not comment twice either. An issue already in a done status gets no transition and no comment. If the workflow offers no transition to a done status from the issue's current status, the run stops naming the issue; close it in Jira and publish again. An issue someone closes by hand is not archived: skaldr keeps publishing to it.

**No writing into an existing issue.** Jira has no counterpart of Notion's `page`: skaldr writes only into issues it created, so a Jira target never adopts an issue and nothing is ever released.

### Publishing to Slack

**Sign in once.** Slack has no personal token outside an app, so create your own app once at https://api.slack.com/apps, give it the user token scopes `canvases:read`, `canvases:write` and `chat:write` under OAuth & Permissions, install it to your workspace, and copy its User OAuth Token, which starts with `xoxp-`. Run `skaldr auth slack` and paste the token: skaldr checks it with Slack's `auth.test` and keeps it in the system keychain under the workspace's id. A bot token (`xoxb-`) is refused, because skaldr publishes as you: each canvas it creates is yours, and each link it posts carries your name. A rotating token (`xoxe.xoxp-...`) is refused too: it expires and skaldr does not renew it, so use an app that does not rotate its tokens. In CI, set `SLACK_USER_TOKEN` instead; it wins over the keychain for a target that names no workspace. When several workspaces are signed in, a Slack target names the one it publishes with in `where: { workspace: "Example Garden" }`, by the workspace's id (`T0EXAMPLE1`) or name. `workspace` is part of the target's place, so two Slack targets can publish one document to two workspaces, and naming another workspace (or the same one by id instead of by name) is a move, which skaldr refuses as it does for Notion and Jira. `skaldr auth logout slack <workspace>` removes a sign-in from the keychain; revoke the token itself on your app's OAuth & Permissions page.

```yaml
publish:
  doc_id: garden-handbook
  targets:
    - to: slack
      where: { conversation: C0EXAMPLE1 }   # or a link: https://example.slack.com/archives/C0EXAMPLE1
      split: [tools]                         # the tools section gets a canvas of its own
```

**`where`.** Every key is optional. `conversation` names a channel (`C...` or `G...`) or a DM (`D...`), by id or by the link Slack copies; `canvas` names an existing canvas (`F...`), by id or link, to write the document into. A target names at most one of the two. With neither, skaldr creates canvases and posts their links nowhere, so a target can be just `- to: slack`. A target's place is its `canvas`, or the standalone canvases it creates when it names none, in its `workspace`; `conversation` is not part of it, so changing where links are posted moves no canvas and archives nothing. A canvas holds a title and content only, so a Slack target has no `fields`, and `--check` refuses `fields` in its `overrides`.

**What lands where.** Each item is a standalone canvas you own: one for the document, and one for each `split` section. Its title is the item's title, and its content is the item's canvas Markdown (the same text `--export slack` writes for it, see Exporting for a Slack canvas) followed by a stamp line, `Published with skaldr from document garden-handbook, section tools` (no section for the document's own canvas), which is how skaldr recognises its canvases. When the target names a `conversation`, skaldr gives that conversation read access to each canvas it creates (Slack's `canvases.access.set`, which the `canvases:write` scope covers) and posts the link to the document's canvas there once, when it creates that canvas (`Garden handbook: https://example.slack.com/docs/T0EXAMPLE1/F0EXAMPLE1`, with `&`, `<` and `>` in the title escaped so a title cannot mention a channel), and Slack shows the link as a card for the canvas; later changes post nothing. A `split` section's canvas is not posted: the document's canvas names each of them in its stamp, `Published with skaldr from document garden-handbook · Slack [Tools](https://example.slack.com/docs/T0EXAMPLE1/F0EXAMPLE2)`, written once every canvas of the run exists and kept up to date like the links between Notion and Jira. Sharing is not part of the canvas: when Slack refuses the access or the message (`channel_not_found`, `not_in_channel`, `is_archived` and the like are named), the canvas is kept and recorded as published, and skaldr prints a `warning:` line naming the canvas, the reason, and what to do by hand (share the canvas with the conversation, or post the link printed in the warning there); the next run does not try again. When the canvas is created but cannot be read back, skaldr stops and the next run records it (see the state file above). When Slack's answer to a create never arrives, the error names the title to look for, since a canvas may exist already. When the document also publishes to Notion or Jira, the stamp goes on to name the paired page and issue (see Links between Notion and Jira). Everything below the stamp belongs to the people using the canvas: skaldr never compares, rewrites or removes it. With `canvas`, skaldr writes into that canvas while it is empty, renames it to the item's title, and records it as adopted, as it does for a Notion `page`.

**Updates.** Slack's canvas API cannot change one block of a canvas reliably, so every write to a canvas's content, whether one section, all of the content, a new stamp line or a missing stamp put back, is one request that replaces the canvas body. skaldr composes the new body from the canvas as it reads it: every block as Slack stored it, with the written section's blocks swapped for the new text, and sends it back. The title is not part of the body, so the request leaves it as it is; a new title is a separate rename request. Everything below the stamp, which is what people wrote there, goes back as Slack's Markdown gives it, so a block that Markdown cannot hold in full, such as a file or message unfurl, a date or a column layout, may come back in a plainer form; keep such blocks out of a canvas skaldr updates, or put them in a canvas of their own. The request replaces the body Slack holds at that moment, so a line someone types into the canvas in the second between skaldr's last read and its write is lost. When two lists would end up in a row, which Slack would merge into one list, skaldr puts a paragraph holding `&nbsp;` between them. A new stamp line (when the links in it change) replaces the old one in the same way. If the stamp is gone, skaldr adds it back at the end the next time it writes to the canvas. Right before writing, skaldr reads the canvas again: when it changed since skaldr read it earlier in the run, nothing is written. A request that fails leaves the canvas as it was, and the next `--apply` writes it again. A request Slack rate-limits, or turns away because someone is editing the canvas (`canvas_editing_locked`), is sent again, up to five attempts, after the wait Slack's `Retry-After` asks for or after 1, 2, 4 and 8 seconds; when Slack asks for more than a minute, skaldr stops instead. A read that fails on Slack's side or cannot reach Slack is tried again too, and a write whose answer never arrives is not repeated, since it may have landed.

**Edits made in Slack.** Slack's canvas API names no editor and no edit time, so skaldr compares the canvas it reads with the copy it saved after its last write: the title and each section that reads differently are remote edits, and `skaldr diff` shows them without a name or a time. Slack stores Markdown in its own form, so these differences never count: `-` bullets stored as `*`, table cells without their padding, a table separator row of any width, blank lines, trailing spaces, a hard-break backslash, an `&nbsp;` paragraph that keeps two lists apart, and a mention written `![](@U0EXAMPLE1)` stored as `<@U0EXAMPLE1>`.

**The size limit.** A canvas holds at most 1,048,576 characters (1 MiB) of Markdown. An item over that stops the plan before anything is sent, naming the item; give some sections a canvas of their own with `split`.

**Archiving and releasing.** skaldr never deletes a canvas. An item whose section left the YAML or the `split` list, or whose target left the `publish` block, is archived: one request replaces the canvas body with that line, `skaldr archived this canvas: the document garden-handbook no longer publishes here.`, in place of everything between the title and the stamp and the stamp itself, and a second request renames the canvas with ` (archived by skaldr)` after its title. What people wrote below the stamp stays where it is. When the canvas changed after skaldr read it earlier in the run, nothing is written. An archive whose rename fails stops with `Slack canvas F0EXAMPLE1 holds the archived line but is not renamed yet, so publish again to finish: ...` and is finished by the next run: a canvas that already opens with that line is only renamed. From then on skaldr treats the canvas as gone: a canvas whose title ends with the marker reads as archived. Delete it in Slack when nobody needs it. A canvas written into with `canvas` is released instead: skaldr deletes the blocks it published that nobody has edited and its stamp, keeps what people added or edited, and stops managing the canvas. Slack refuses an empty canvas body, so a released canvas that held only what skaldr published keeps one blank paragraph. A canvas that has lost its stamp has no line between skaldr's content and what people added, so an archive replaces all of its body.

**Slack's errors.** A canvas Slack no longer has (`canvas_not_found`, `canvas_deleted`) reads as missing. A revoked or invalid token (`token_revoked`, `invalid_auth`) stops the run and says to run `skaldr auth slack` with a new token, and a missing scope is named, so you can add it to your app, install the app again and sign in again. `canvas_too_large` points at `split`, and a workspace on Slack's free plan, which cannot edit a standalone canvas (`free_teams_cannot_edit_standalone_canvases`), stops the write naming that.

## The render carries its own source

Every rendered page embeds its **editable YAML source** in an inert `<script id="skaldr-source">`
block, placed *before* the stylesheet. So an agent handed a skaldr page (a local `.html`, or a
shared artifact URL) recovers the source **without** wading through the rendered HTML/CSS:

- `skaldr --extract-source report.html` (or an `http(s)://` URL) prints just the YAML.
- Reading the top of the file (or a fetch) reaches the source block before the CSS.

Slicing the text between the scissor markers yourself gives the YAML verbatim, with one exception the
markers announce: a source that itself contains `</script>` would end the block early, so that one is
written with a backslash in front of every `</script` and its begin marker reads
`skaldr source (yaml, backslash-escaped)`. Prefer `--extract-source`, which undoes it for you.

A top-of-file comment tells agents this. Pass `--no-source` to omit the embed (e.g. a shared page
whose authoring notes shouldn't ship). The `--embed` fragment carries it too: that's the artifact
case, where the page is shared as a URL an agent later has to read back.

## Exporting as Markdown

`skaldr report.yaml --export markdown` writes GitHub-flavored Markdown and `--export notion` writes Notion-flavored Markdown, each to `out/<name>.<target>/page.md` (or the folder `--export-dir` names); `--export adf` writes the ADF JSON for Jira and `--export slack` the Markdown for a Slack canvas, each described in the sections below. Write the YAML the same way for every output; what changes is how some blocks look. A block a target cannot show the way the page shows it is refused rather than written badly: the export stops before it writes anything, with an error naming the block's path in the YAML, why the target cannot show it and what to write instead, and `skaldr --check --for <target>` runs the same export in memory and writes nothing, so it refuses exactly what the export refuses. `skaldr publish` runs the same check before it sends anything, so a Notion target refuses what `--export notion` refuses (a same-page or `doc:` link included) and a Jira target what `--export adf` refuses. When a document holds several such blocks, the error names the first in the document, and a container the target refuses before anything inside it. Each export section lists the blocks its target refuses and its table says what it refuses inside the text, and the ADF and Slack sections also give the size each target can hold, which skaldr measures on the written output rather than on the blocks. The rest of this section shows how the GitHub-flavored and Notion exports write each block:

| Block | GitHub-flavored | Notion |
| --- | --- | --- |
| `flow`, `fan` | a Mermaid diagram, plus a list of the steps whose points or badges it cannot show | the same |
| `chart` | a donut is a Mermaid pie over a table of each slice's value and share and the total; a bar or line chart with one series, stacked or not, is a Mermaid xy chart over its data table; a chart with several series is its data table alone, with a `Total` row of each category's stack for stacked bars | the same |
| `callout`, `note`, a toned `grid` cell | a quote led by an icon | a native callout |
| `panel` | a quote led by its bold title and no icon, as on the page | a native callout |
| a list inside a set-apart body | a Markdown list, nested as written; inside a table cell or a `quote`, each item is a line led by `• ` (`◦ ` when nested) or its number | a native list, nested as written; inside a table cell or a `quote`, each item is a line led by `• ` (`◦ ` when nested) or its number, since a Notion cell or quote holds only text; a list in a muted `text` body keeps the normal text colour |
| a `callout` or `note` `icon` | the icon that leads the quote | the callout's icon |
| a decimal `number` list's `start` | the first marker is the start number, which GitHub and CommonMark honour; a marker holds at most nine digits, so an item past 999999999 is written as 999999999 and still shows its own number, since a reader counts on from the start | a native numbered list when it starts at 1; a list whose `start` is not 1, or a numbered list in prose such as `3. a`, is refused, since Notion numbers every list from 1; number it from 1 |
| a `number` list's `numbering: letters\|roman` | a bullet list whose items start with their label as text (`iv.`, `v.`, `vi.`), since Markdown has no letter or roman markers | the same |
| a `decision` list | a bullet list whose items start with ☑️ (decided) or ❓ (open) | the same |
| a multi-case `request` | each case under a bold title | one toggle per case, its title led by the icon of the case's status |
| `tabs` | each tab under a bold title, led by an icon when its tone is info, success, warning or danger | one toggle per tab, its title led by the same icon |
| a collapsed `section` | a heading with its content below | a toggle heading |
| `toggle` | its bold title with its content below | a `<details>` toggle with its content tab-indented; an open one is its bold title with its content below |
| `heading` | `##`, `###` or `####` for levels 2 to 4; inside a section every heading moves down one level, so a level 4 heading there is `#####` | `##`, `###` or `####`; a heading that would be deeper than `####`, such as a level 4 heading inside a section, is `####`, the deepest heading Notion has |
| `grid` | its cells one after another | native columns |
| `divider` | a `---` thematic break with a blank line on each side | a `---` divider |
| badges | the bold label preceded by the dot of the badge's colour, as in `🔴 **High**`: 🔴 for `red`, 🟡 for `amber`, 🟢 for `green` and `teal`, 🔵 for `blue` and `sky`, 🟣 for `violet` and ⚪ for `slate`; the badge legend, a `badge_row` and a badge column write their badges the same way | bold text in the badge's colour, or in the normal text colour inside a filled table cell, where the fill carries the colour; each badge colour has its own Notion colour, and since Notion has no teal or light blue, `teal` is brown and `sky` is pink there and everywhere else a colour reaches Notion (highlights, text colours, cell and column backgrounds) |
| a table row's `tone` (including a `tint_by` tint, and a chart slice's or series' row in its data table) | shown in the row's title cell (the first `text` column, or the first `rich` column when there is none): a `muted` row's title text is struck through, with any dot the title cell shows kept before the strike, and a `danger` row's title is preceded by 🔴; a `tint_by` tint is dropped, since the row's badge already shows its dot, and so is a chart slice's or series' tone, since its label names it | the background of one cell: the first cell that holds a badge, or the row's first cell when none does; a cell's own `tone` wins in that cell; a `group` row is a full-width band |
| tones on meters, cards and walkthrough steps | the tone's dot before the item's bold label, as in `🟡 **Disk**`; a card whose tone is the colour of one of its badges or of its delta chip (`danger` and `red`, for example) leaves the dot to that chip, a card with a badge or delta of another colour shows both dots, and a derived card leaves its colour to its badge's dot; an item with no label shows no dot | the item's bold label (and a walkthrough step's subtitle) in the tone's colour, and the rest of the item in the normal text colour; a card whose tone is the colour of one of its badges or of its delta chip leaves its colour to that chip, a card with a badge or delta of another colour shows both colours, and a derived card leaves its colour to its badge; an item with no label shows no colour |
| tones on table cells and columns | a cell's tone is its dot before the cell's text, or the dot alone in a cell with no text, such as a `matrix` cell with a `tone` and no `label`; a `comparison`'s ✓ and ✗ take 🟢 or 🔴 by what they mean under the column's `polarity`, so `🔴 ✓` is a ✓ in a `negative` column; an `indicator` cell is its dot once; a column's `tone` is dropped | cell and column backgrounds |
| a table column's `tone` and `width` | dropped (a pipe table has no column colour or width) | column colours, and widths in the same proportions as the HTML (including the default share a `number` or `indicator` column takes), in whole pixels that add up to Notion's default page width, 708 px (an assumption, unverified) |
| tones on flow and fan steps | Mermaid node colours | the same |
| `image` with a URL | a Markdown image `![alt](url)`, with the caption in italics below it | a Markdown image `![caption](url)`, with the alt text in place of the caption when there is none (Notion Markdown has no alt text, so its image text is the caption) |
| `media` | a link, `Video: [caption](url)`, with the URL as the link text when there is no caption (`Audio`, `File` and `PDF` likewise) | a `<video src="url">caption</video>` tag, or `<audio>`, `<file>` or `<pdf>` (the forms in Notion's enhanced Markdown reference) |
| `link` | `inline` is a Markdown link; a `card` or an `embed` is a quote holding the bold linked title, then the domain and the caption in italics; the export writes no `<iframe>` | `inline` is a Markdown link; a `card` or an `embed` is a quote holding the bold linked title, then the domain and the caption in italics; Notion's `<embed>` tag takes an HTML attachment, not a URL, so the export never writes it |
| `**bold**`, `*italic*`, `~~strike~~` | the same marks, except where GitHub would not read them, such as bold text that ends in a bracket right before a letter, or an italic that opens or closes a bold (or a bold an italic), since their markers would run together into one; there the mark is a `<strong>`, `<em>` or `<del>` tag. A mark inside the same mark, such as an italic word in an italic sentence, is written once | the same marks |
| `++underline++` | an `<ins>` tag | an underline span; an underline inside or around a colour or a highlight, such as `[a ++b++ c]{tone=danger}`, is written as spans side by side, each part of the text carrying the underline and its innermost colour or highlight, since Notion holds no span inside a span |
| `H~2~O`, `10^3^` | `<sub>` and `<sup>` tags | inline math (`` $`_{\text{2}}`$ ``), since Notion has no subscript or superscript |
| `[text]{tone=…}` | refused, since GitHub cannot colour text; write the text without the colour | a text colour span |
| `[text]{bg=…}` | refused, since GitHub cannot highlight text; write the text without the highlight | a background colour span |
| `[text]{tone=… bg=…}` | refused, like a colour span | refused, since a Notion text run takes a colour or a highlight, not both; keep one of them |
| a colour span inside a colour span, or a highlight inside a highlight, such as `[a [b]{tone=info} c]{tone=danger}` | refused, like a colour or a highlight span | spans side by side, each part of the text in its innermost span, since Notion holds no span inside a span; an author's colour in a toned walkthrough step's title is written the same way |
| a highlight inside a colour or a colour inside a highlight, nested either way, or a highlight in a toned walkthrough step's title | refused, like the outer colour or highlight span; in a toned step's title, like a highlight span | refused, since Notion holds no span inside a span; keep either the colour or the highlight |
| a `{{name}}` blank | inline code | a yellow highlight span; inside a colour, a highlight, an underline or a toned walkthrough step's title it is written beside the text around it, keeping the underline, since a blank shows its own colours on the page |
| `[1 Oct](date:2026-10-01)` | the label in a `<time datetime="2026-10-01">` tag; a range is the label in a `<span data-range="2026-10-05/2026-10-09">` tag, a form GitHub may sanitise to the label alone, so a range's dates may not show on GitHub. A label of only spaces writes an empty tag, and the HTML page shows an empty chip | the label, then a date mention, `1 Oct <mention-date start="2026-10-01"/>`, with `end` for a range; a label of only spaces is left out |
| `[Ada](user:ada)` | the label as text | a user mention, `<mention-user url="user://…">Ada</mention-user>`, when the person has a `notion` id; otherwise the label as text |
| `[ABC-123](jira:ABC-123)` | a link to the issue on `meta.jira_site`, or the label as text without one | the same |
| `[the plan](doc:onboarding-plan#st2)` | a link to `onboarding-plan.md`; to a part of the same index, an in-page link | refused, since skaldr has no address for that document's Notion page; link to its https address instead. To a part of the same index, refused like a same-page link |
| `` $`x_i`$ `` inline math | GitHub's `` $`x_i`$ `` math | Notion inline math, the same form |
| an inline `` `code` `` span holding a closing tag (`</`) or a backtick, including a `code` block's `label` | inline code | inline code, except that a span holding a backtick is refused, since no Notion form keeps it as code, and so is a span holding `</` inside a table cell, since Notion loses that cell's content, or inside a colour, highlight or underline span you wrote, since Notion closes the span there; write such code in a code block, or move it out of the table or the coloured, highlighted or underlined text. In a toned walkthrough step's title, such code is written outside the step's colour, and the rest of the title keeps it |
| `math` | a ` ```math ` fence | a `$$` equation block |

The GitHub-flavored and Notion exports refuse:

- a `range`, since neither can draw a range bar; use a `meter` or a `table`.
- a `flow` or `fan` step whose `note` holds a link, citation, inline math, struck-through text, or a subscript or superscript with no Unicode form (see the Slack canvas section for the characters that have one), since a Mermaid label holds plain text only; write the note as plain text and put the rest in a text block after the diagram. Any other mark in a note, such as bold, italic, underline, a colour or inline code, keeps its characters and loses its formatting.
- an `image` with a `data:` source, since neither shows an image from a `data:` URI; host the image and give its https address.

Interactive parts of the HTML (request input fields, live reload) have no Markdown form, so a request shows each case's command (or its `query`, as a fenced block in its language under the runner's name), with that case's `values` written in, and its recorded response, and a `request_flow` step names each value it captures and where in the response it comes from (its `json_path`, or the whole response body). Same-page `[…](#id)` links work in GitHub-flavored Markdown; the Notion export refuses a document holding one you wrote, since a Notion page cannot link to its own headings, and writes a section's `fields.links` entry as the linked section's title. The Notion page takes its title from the page, so the Notion export starts with the body; the GitHub-flavored file starts with the title, led by `meta.icon` when there is one, then a `Cover image` link when `meta.cover` is set. Notion does not fit a table written through its API to the page; it takes the column widths the export writes. With `meta.notion_width: normal` (the default) only columns given a `width` (or the default share of a `number` or `indicator` column) are sized, to Notion's 708 px page. With `meta.notion_width: full` every table is sized to 1,200 px, or to its column's share of that inside a `grid`: columns given a `width` (or the default share of a `number` or `indicator` column) keep their share, the others split the rest by their longest text (header included), and no column is narrower than 64 px. No Notion API switches a page to Full width; switch it in Notion's ••• menu, or start from a page that is already Full width (a page created from a Full width template, or a duplicate of one, is Full width too). `--chunk N` (Notion only) splits the page at level 1 and 2 headings into `page.00.md`, `page.01.md`, …, each holding as many whole sections as fit in N characters. A section longer than N on its own is split between its blocks, keeping a heading with the block after it. A table is never split, because Notion shows the parts of a split table as separate tables. A part that still cannot fit in N, such as a long table, a long code block, or a heading together with the block after it, stays whole in one file, and the command prints a warning naming its section. The folder keeps a `.skaldr-export.json` list of what skaldr wrote, and a re-export removes only files on that list, so nothing else in the folder is touched. An export that would replace a page file not on that list, such as your own `page.md` in a folder skaldr has never exported to, stops with an error naming the file and writes nothing, and so does an export whose page name is taken by a folder; move the file or folder away or choose another `--export-dir`.

## Exporting as ADF for Jira

`skaldr report.yaml --export adf` writes the document as Atlassian Document Format, the JSON a Jira issue description takes, to `out/<name>.adf/page.adf.json` (or the folder `--export-dir` names). It lets you inspect what a Jira publish would send, and nothing is sent anywhere. Jira renders ADF panels, expands, task lists and status lozenges, which Markdown cannot carry, so Jira gets ADF built by skaldr rather than Markdown. Like the Notion export, the file holds the body only: the title is the issue's summary. The folder keeps its `.skaldr-export.json` list, with the same overwrite rules as the Markdown exports. `--chunk` does not apply.

| Block | ADF |
| --- | --- |
| `heading` | a heading of the same level |
| `text`, and prose in other blocks | a paragraph; a toned paragraph gets the tone's text colour |
| a list | a bullet, ordered (with its start number) or task list, nested as written; a `number` list with `numbering: letters` or `roman` is refused, since ADF numbers a list only with digits |
| `callout`, `note`, `panel` | a panel: info, success, warning, error (a danger tone) or note (neutral, muted and accent tones; teal and sky are info) |
| `code` | a code block with its language; a `math` block is a code block in `latex`, since ADF has no math, and `` $`x_i`$ `` inline math is inline code holding the LaTeX |
| `quote` | a block quote, the citation in italics |
| `divider` | a rule |
| `table`, `comparison`, `matrix`, `swimlane` | a table with a header row; a row, column or cell tone is the cell's background, a group row is a bold band, a total row is bold, and a `header_column` makes the first column header cells |
| a collapsed `section`, a `toggle`, and each tab or request case | an expand with its title; an expand inside an expand is a nested expand; a tab's title is led by an icon when its tone is info, success, warning or danger, and a request case's by the icon of its status |
| `grid` | its cells one after another |
| `chart` | its data table in place of the chart, since ADF cannot draw one: a row per slice with its value and share and a total row for a donut, a row per series for a bar or line chart, and for stacked bars with several series a bold `Total` row of each category's stack |
| badges, and the states of a `status_list` or `swimlane` | status lozenges in the nearest of ADF's six colours (neutral, purple, blue, red, yellow, green) |
| `image` and `media` | a paragraph holding the kind (Image, Video, Audio, File or PDF), a colon and a link to the URL, named by the caption, else the description, else the URL; ADF media nodes need uploaded files, so nothing is embedded, and a URL with a scheme other than `http://`, `https://` or `mailto:` is written as its name alone |
| a table of contents | nothing, because a Jira heading has no anchor for an entry to link to |
| `++underline++`, strike, bold, italic, links, subscripts, superscripts, `[text]{tone=…}` | the matching marks; inline code carries only a link, because ADF allows no other mark on code, so bold or a colour around code is dropped; a link to anything but an `http://`, `https://` or `mailto:` address is written as its label alone |
| `[text]{bg=…}`, alone or with a `tone` | refused, since a Jira description does not show a text highlight; write the text without the highlight |
| an issue key of the target project, once a Jira site is known | a live issue card; a card carries no marks, so bold or a colour around a key is dropped, and a key in code or a link label stays text |
| `[text](date:…)` | the text, a space and a date node at UTC midnight of the date; a range is the text, a space, the start date, the text " to " and the end date; a text of only spaces is left out |
| `[text](user:key)` | a mention of the person's `jira` account id, shown as "@" and the text; a person with no `jira` id is the text alone |
| `[text](jira:KEY)` | a live issue card when a Jira site is known (`jira_site`); otherwise the text alone |
| `[text](doc:id)` | refused, since skaldr has no address for that document's Jira issue; link to its https address instead. A link to a part of the same index is refused like a same-page link |
| a same-page `[…](#id)` link | refused, since a Jira description cannot link to its own headings; write the heading's name without the link. A section's `fields.links` entry, which skaldr writes, is the linked section's title as text |

The ADF export refuses:

- a `range`, since ADF cannot draw a range bar; use a `meter` or a `table`.
- a `flow`, since ADF cannot draw a diagram; write the steps as a numbered list.
- a `fan`, for the same reason; write the hub and its spokes as a list.
- an `image` with a `data:` source, since Jira embeds only files attached to the issue; host the image and give its https address.

ADF limits what each container may hold, and skaldr does not guess. A walkthrough step, list item or checklist entry holds text, lists, code blocks, math, images and media; one holding a table, a callout or panel, a heading, a quote, a toggle, a set of tabs or a divider fails the export naming that block's path, as in `ADF cannot place a table inside a walkthrough step, at blocks.1.walkthrough.steps.0.detail.1.table; move the table out of the step, after the walkthrough`, and a divider in a walkthrough step is refused since Jira writes a step as a list item. A block ADF cannot place at all stops the export, and a publish to Jira, before anything is written or sent, with an error naming the block in the document's own terms, what it was inside, its path in the YAML, the nearest heading above it, and what to do instead, for example `ADF cannot place a table inside a panel, at blocks.2.panel.blocks.0.table, under the heading 'Totals'; move the table out of the panel` or `ADF cannot place a toggle inside a toggle that is itself inside a toggle, at blocks.0.toggle.blocks.0.toggle.blocks.0.toggle; move the toggle out of the toggle`. The block, and the panel, grid cell, toggle, collapsed section or part, or set of tabs that refuses it, are named as you wrote them (`ADF cannot place a comparison inside a panel`, `ADF cannot place a toggle inside a toggle that is itself inside a section`), so a `link` card is a link card, a `comparison` is a comparison, and a `note` is a note, even though ADF would write each as a quote, a table or a panel. In a document built by an `index`, the path counts the parts as blocks of the index (`blocks.0.part.blocks.1.toggle`). Jira limits a description to 32,767 characters of compact JSON, so the export prints a warning with the size when the document is over that.

## Exporting for a Slack canvas

`skaldr report.yaml --export slack` writes the document as the Markdown a Slack canvas takes, to `out/<name>.slack/page.md` (or the folder `--export-dir` names). Nothing is sent anywhere: whatever creates the canvas (`skaldr publish` with a Slack target, see Publishing to Slack, Slack's `canvases.create`, or an agent's Slack connector) uses the `title` in the folder's `.skaldr-export.json` as the canvas title and `page.md` as its body. Like the Notion export, the file holds the body only, since a canvas shows its title above the body. The folder keeps its `.skaldr-export.json` list, with the same overwrite rules as the Markdown exports. `--chunk` does not apply.

| Block | Canvas Markdown |
| --- | --- |
| `heading` | `#`, `##` or `###`; a canvas has no deeper heading, so a heading that would be deeper, such as a level 4 heading or a level 3 heading inside a section, is `###` |
| `text`, and prose in other blocks | a paragraph; tones are dropped |
| a list | a `*`, `1.` or `* [ ]` and `* [x]` list. A canvas list item holds only text and one nested list; a nested list keeps its own kind, so bullets under a numbered step stay bullets. A paragraph in a list item joins the item's text when it comes before the item's nested list. A list item holding anything else, such as a paragraph after its nested list, a code block, table, quote, callout, image, media, diagram, math block, heading, toggle, tabs, divider or a second nested list, fails the export with an error naming the YAML path of the block that holds it, since a canvas could only show it after the whole list, away from its item. A canvas joins two lists in a row into one, even a bullet list and a check list, so a paragraph holding `&nbsp;`, which the canvas stores as a single no-break space, keeps them apart, such as a `fact_strip` right before a `cards` block. A canvas numbers every list from 1 and only with digits, so a numbered list that starts at another number, or a `number` list with `numbering: letters` or `roman`, fails the export with an error naming its YAML path |
| `callout`, `note`, `panel` | a `::: {.callout}` block whose body starts with the tone's icon, or the block's `icon`; a `panel` has no icon, as on the page, so its body starts with its bold title. A canvas callout holds only text, headings, lists, quotes, code blocks and images, so a panel holding a table, a `callout` or `note`, a toggle, tabs or a divider fails the export with an error naming that block's path in the YAML. A `chart`, `comparison`, `matrix` or `swimlane` is written as a table, a request with several cases as tabs, and a request case's verdict as a callout, so a panel holding one fails the same way, naming the block you wrote; move the block out of the panel |
| `code` | a fenced block with its language; a `math` block is a fenced block in `latex`, since a canvas has no math |
| `chart` | its data table in place of the chart, since a canvas cannot draw one: a row per slice with its value and share and a total row for a donut, a row per series for a bar or line chart, and for stacked bars with several series a bold `Total` row of each category's stack |
| `quote` | quoted lines, with the citation on its own line in italics; a quote whose body holds a list is refused, since a canvas quote holds only text; move the list out of the quote, after it |
| `divider` | `---`; a canvas list item, column or callout cannot hold one, so a divider in a walkthrough step, a grid cell or a panel fails the export |
| a collapsed `section` | a heading at its level, then its content |
| `toggle` | its bold title, then its content |
| `tabs`, a multi-case `request` | each tab as a bold title, led by an icon when its tone is info, success, warning or danger, then its content |
| `grid` | a `::: {.layout}` of `::: {.column}` blocks, one per cell; a grid with one cell is that cell's blocks. A canvas layout holds at most three columns, a column has no tone and holds no table, callout or divider, and a canvas cannot show a grid's columns inside a grid cell, so a grid of four or more cells, a toned cell, a cell holding a table, a `callout`, `note` or `divider`, or a grid of two or more cells inside a grid cell fails the export with an error naming its path in the YAML; a `chart`, `comparison`, `matrix` or `swimlane` is written as a table, so a cell holding one fails the same way; split the grid, drop the tone, or move the block out of the grid |
| `table`, `comparison`, `matrix`, `swimlane` | a pipe table under its header row; row and cell tones are shown as in the GitHub-flavored export (the title cell is the first `text` column, or the first `rich` column when there is none; a `muted` row's title text is struck through after any dot, a `danger` row's title is preceded by 🔴, and a cell tone's dot comes before the cell's text), and a `tint_by` tint, a chart slice's or series' tone, column tones and widths are dropped, a `\|` in a cell is escaped, and the lines of a cell are joined with `<br>` |
| a table of contents | nothing, since a canvas has no links to its own headings |
| `image` with a URL | a Markdown image `![alt](url)`, with the caption in italics below it |
| `media` | a link named by the caption, or by the kind (Video, Audio, File or PDF) when there is none |
| badges | the bold label preceded by the dot of the badge's colour, as in the GitHub-flavored export; the badge legend and a `badge_row` write their badges the same way |
| tones on meters, cards and walkthrough steps | the tone's dot before the item's bold label, as in the GitHub-flavored export |
| `**bold**`, `*italic*`, `~~strike~~` | the same marks, except where the characters around a mark would stop a canvas reading it, such as bold text that ends in a bracket right before a letter, or an italic that opens or closes a bold (or a bold an italic); there the text is written without the mark. A mark inside the same mark is written once |
| `++underline++`, `[text]{tone=…}`, `[text]{bg=…}` | refused, since a canvas has no underline, text colour or highlight; write the text without the mark |
| `H~2~O`, `10^3^` | Unicode subscript and superscript characters, `H₂O` and `10³`, since a canvas has no subscript or superscript mark. Digits, `+`, `-`, `=` and brackets have both forms; a superscript also covers every lowercase letter but `q` and the capitals `A B D E G H I J K L M N O P R T U V W`, and a subscript the lowercase `a e h i j k l m n o p r s t u v x`. A subscript or superscript holding any other character, a space included, fails the export with an error naming its text, the first such character and the path in the YAML of the block that holds it, since writing it bare would change its meaning (`10^3^` read as 103); write the text without the mark, or export the document elsewhere |
| `` $`x_i`$ `` inline math | inline code holding the LaTeX |
| `[1 Oct](date:2026-10-01)` | the label as text, `1 Oct`, since canvas Markdown has no date syntax and shows an HTML tag as its literal text; a label of only spaces writes the date as written after `date:`, `2026-10-01` or `2026-10-05/2026-10-09` |
| `[Ada](user:ada)` | a member mention, `![](@U0EXAMPLE1)`, when the person has a `slack` id, which Slack shows as the member's own name in place of the label; otherwise the label as text |
| a same-page `[…](#id)` link | refused, since a canvas cannot link to its own headings; write the heading's name without the link. A section's `fields.links` entry, which skaldr writes, is the linked section's title as text |
| `[the plan](doc:…)` | refused, since skaldr has no address for that document's canvas; link to its https address instead. A link to a part of the same index is refused like a same-page link |

The canvas export refuses:

- a `range`, since a canvas cannot draw a range bar; use a `meter` or a `table`.
- a `flow`, since a canvas cannot draw a diagram; write the steps as a numbered list.
- a `fan`, for the same reason; write the hub and its spokes as a list.
- an `image` with a `data:` source, since a canvas cannot show one; upload the image to Slack and give its permalink.

A canvas table holds at most 300 cells, the header row included, with short rows counted at the table's full width. A document with a longer table fails the export with an error naming its cell count, its path in the YAML and the heading above it, and nothing is written; split the table in two in the YAML, or export the document elsewhere. A `chart`, which a canvas shows as its data table, counts the same way, and the error names the chart; split its data into two charts. A canvas holds at most 1,048,576 characters of Markdown, the limit Slack's `canvases.create` and `canvases.edit` documentation gives as "1 MiB (1,048,576 characters)", so skaldr counts characters, not bytes; a document whose canvas Markdown is longer fails the same way, naming its size in characters, and `skaldr --check --for slack` fails it too, since it writes the canvas in memory to measure it. A walkthrough step is a canvas list item, which holds only text and one nested list, so a `grid` of two or more cells in a step's `detail` fails the export with an error naming its path in the YAML (`blocks.1.walkthrough.steps.1.detail.1.grid`); move the grid out of the step, after the walkthrough. A grid of one cell, in a step or in a grid cell, shows no columns, so it is its cell's blocks and they are checked where it stands. A step's `detail` may hold text and then one list; any other block there, such as a `code`, `callout`, `table`, `image` or `divider`, a second list, or text after the list, fails the same way, naming that block's path (`blocks.1.walkthrough.steps.1.detail.1.code`). A list in a `text`, `callout` or `def_list` body whose item holds two nested lists, such as bullets and then numbers under one item, or a paragraph after its nested list, fails naming the block that holds it (`blocks.3.def_list`); move the second list or the paragraph out of the list.

## What you never write

Colours, CSS, fonts, pixel sizes, HTML, the legend, the TOC, percentages, subtotals, the
provenance footer, or thousands separators. Those are derived or fixed by the design system, so
they can't drift from your data. If a report seems to need markup skaldr doesn't offer, it needs
a component: file it, don't smuggle HTML.
