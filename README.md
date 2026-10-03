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
brew install alex-yanchenko/tap/skaldr     # recommended (Apple silicon Macs and Linux)
uv tool install skaldr                     # or, with uv
pipx install skaldr                        # or, with pipx
```

All three put a `skaldr` command on your PATH. (From a checkout, `uv run skaldr …` works without
installing.)

## Use

```bash
skaldr report.yaml                 # → out/report.html
skaldr report.yaml -o review.html  # choose the output path
skaldr report.yaml --watch -o review.html  # re-render on every save (live edit→preview; Ctrl-C to stop)
skaldr report.yaml --pdf report.pdf  # a ready-to-share PDF (drives a headless Chrome/Chromium)
open review.html                   # a self-contained file — open it, host it, or share it
```

**Live preview without a watcher process.** `--watch` needs a process that stays alive, which an
agent harness will not give you: Claude Code reaps background jobs between turns, so the watcher
dies and the HTML goes quietly stale. Two flags cover the same ground with no daemon:

```bash
skaldr report.yaml -o review.html --live      # the page re-reads itself when you return to the tab
skaldr report.yaml -o review.html --if-stale  # a no-op when the HTML is already current
```

Render once with `--live`, open the file, and leave the tab. Re-render after every edit with
`--if-stale` (free when nothing changed), and the open tab picks it up on focus with your scroll
position and open sections intact. `--live 2000` also polls every two seconds, for a second monitor
where the tab never loses focus. A small "live" badge marks a self-refreshing page and turns it off
when clicked.

The page cannot poll for changes: its own CSP is `default-src 'none'`, which blocks every scripted
network request, and a `file://` page could not fetch its own source anyway. So `--live` reloads on
a signal it already has, which is you looking at the tab.

That's the whole tool: point it at a content file, get an HTML page (or a PDF). A few more commands
help you write the content file and share the result:

```bash
skaldr --guide                     # the authoring guide: every block, the rules, a full example
skaldr --write-schema page.schema.json   # JSON Schema for your editor's YAML language server
skaldr report.yaml --embed -o out.html   # Artifact-ready fragment (no <html> skeleton) to publish as a claude.ai Artifact
skaldr --check report.yaml         # validate against the schema, write nothing (exits non-zero on error)
skaldr --check reports/*.yaml      # validate a whole set at once — for a pre-commit hook or CI
skaldr --check report.yaml -o report.html   # gate the render on the check: nothing reaches disk unless it passes
skaldr --emit-json report.yaml     # print the normalised model as JSON on stdout (for tooling/agents)
skaldr --extract-source report.html  # recover the YAML source embedded in a render (a file or an http(s) URL)
```

For a **PDF**, use `--pdf` (above): it prints the page's print styling with a headless browser you
already have — the reliable way to a shareable PDF. (Printing a published Artifact doesn't work: it's
a sandboxed frame the browser flattens to a snapshot, so the print CSS never applies.) `--pdf` needs
a Chrome/Chromium/Edge on the machine; set `SKALDR_BROWSER` to point at one if it isn't auto-found.

**Markdown for another tool.** `--export` writes the document as Markdown instead of HTML, to `out/<name>.<target>/page.md` or to the folder `--export-dir` names:

```bash
skaldr report.yaml --export markdown               # GitHub-flavored Markdown for a README, a PR body or a wiki
skaldr report.yaml --export notion                 # Notion-flavored Markdown for a Notion page
skaldr report.yaml --export notion --chunk 20000   # page.00.md, page.01.md, … of at most 20000 characters each; a longer section stays whole
```

Every block has a Markdown form. Flows, fans, donut charts, and unstacked bar or line charts with one series become Mermaid diagrams, which GitHub and Notion both draw. A chart drawn as a diagram keeps its data table under it, and a donut's table lists each slice's value and share and the total. A chart with several series, or a stacked bar chart, is its data table alone. In GitHub-flavored Markdown a callout is a quote led by an icon, a tab or a collapsed section is a titled block of its content, and a badge is a bold label. The Notion form keeps what Notion has natively: tabs, toggles, columns, callouts and coloured table cells. A Notion page takes its title from the page itself, so the Notion export holds the body only, while the GitHub-flavored file starts with the title as its heading. The folder keeps a `.skaldr-export.json` list of the files skaldr wrote there, and a re-export removes only those an earlier run wrote and this one no longer needs. skaldr only writes the files; it never calls Notion.

There are no styling flags — everything is in the content file.

## Sign in to Notion and Jira

`skaldr auth` stores the credentials skaldr uses to talk to Notion and Jira. It needs the `publish` extra. The Homebrew formula includes it and runs on Apple silicon and Linux; on an Intel Mac, install with uv or pipx instead:

```bash
uv tool install 'skaldr[publish]'   # or: pipx install 'skaldr[publish]'
skaldr auth notion                  # OAuth in your browser, through your own Notion connection
skaldr auth jira                    # your Atlassian account email and an API token
skaldr auth status                  # who each service is signed in as, and where the credentials live
skaldr auth logout notion           # revoke the Notion token and remove it (removed even if Notion refuses)
skaldr auth logout jira             # remove the Jira token; revoke it on Atlassian's API tokens page
```

**Notion.** A public tool cannot ship a client secret, so you register your own connection once. At https://www.notion.so/profile/integrations create a new connection, choose the public (OAuth) type, and add the redirect URI `http://localhost:8765/callback` (Notion does not accept an IP address there). `skaldr auth notion` asks for its client ID and client secret (the secret is read without echo), or takes them from `NOTION_CLIENT_ID` and `NOTION_CLIENT_SECRET`. It then opens Notion's consent screen, where you choose the pages skaldr may use, and catches the redirect on port 8765 of both loopback addresses, `127.0.0.1` and `::1`, so it arrives whichever one your browser resolves `localhost` to. Any other request to that port is turned away, a refusal without the sign-in's `state` included, and the sign-in keeps waiting for Notion's own answer. Text that Notion or Jira send back, such as an error, a workspace name or a display name, is printed without its control characters. If the port is taken, register a different one and pass `--port`.

**Jira.** Create an API token at https://id.atlassian.com/manage-profile/security/api-tokens. `skaldr auth jira` asks for your site (`https://<site>.atlassian.net`), your account email and the token, and checks them against Jira's `/rest/api/3/myself` before saving anything. The site must be a Jira Cloud host ending in `.atlassian.net`. A pasted page URL is cut back to its site, and a site that carries a user name, password, query, fragment or backslash is refused, so the token only ever goes to the host you named. `JIRA_SITE` is held to the same rules. Use a token created without scopes: a scoped token only works against `api.atlassian.com`. Atlassian tokens expire after at most a year, so when Jira starts refusing it, create a new one and sign in again.

Secrets go to the system keychain (macOS Keychain, Windows Credential Locker, or the Secret Service on Linux) and never to a file, a log or a command-line argument. skaldr refuses the `keyrings.alt` backends, because they store secrets where skaldr cannot vouch for them, and `keyring.backends.null` and `keyring.backends.fail`, which store nothing. That includes a subclass of one of them and one that sits in keyring's chain of backends. The refusal names the backend so you can choose a secure one with `PYTHON_KEYRING_BACKEND` or keyring's `keyringrc.cfg`. Before a sign-in asks for anything or opens the browser, skaldr checks the backend and reads its own entry once, which catches a refused, locked or unreadable keychain before Notion issues a token. A keychain that reads but then refuses the write is only found when saving; skaldr then revokes the token Notion just issued, and if that fails too, it tells you to remove the connection in Notion yourself.

For CI or a secrets manager, environment variables take precedence over the keychain: `NOTION_ACCESS_TOKEN` (with `NOTION_CLIENT_ID` and `NOTION_CLIENT_SECRET` as an optional pair: one without the other is refused), or `JIRA_SITE`, `JIRA_EMAIL` and `JIRA_API_TOKEN` together. For credentials from the environment, `skaldr auth status` names the variables and the Jira site, never the account email, so its output can go to a build log.

## The content file

```yaml
version: 1
meta:
  title: "Q3 Warehouse Inventory Count — Discrepancies & Fixes"
  subtitle: ["Reconciled review of the 10,000-unit cycle count."]
  source: "WMS export"          # optional; feeds the provenance footer
  date: "Q3 2026"               # optional; never auto-now (builds are reproducible)
  toc: true                     # optional; auto table-of-contents from level-2 headings
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
`~~strike~~`, links) plus `++underline++`, `H~2~O` and `10^3^`, `[text]{tone=danger bg=warning}` colour and highlight, and `` $`x_i`$ `` inline math; a `math` block shows a display equation, rendered as MathML at build time. Raw HTML is never interpreted.

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

skaldr ships Claude skills, so you can skip the YAML and just ask. Install them once:

```bash
skaldr --install-skill      # copies skaldr's skills into ~/.claude/skills (survives upgrades)
skaldr --install-plan-rule  # optional: also have the AI keep its working plans as live skaldr docs
```

`--install-skill` installs the core authoring skill **and** task-specific ones: a **presentation
builder** (`skaldr-presentation`) that writes a word-for-word teleprompter runbook (with color-coded
live/recording cues) and drives the audience deck into the org's real brand template, and a
**reflection** helper (`skaldr-reflect`) that turns your experience of authoring with skaldr into a
ranked, actionable pain-points report for the maintainer. Each lands in its own `~/.claude/skills/<name>/`.

**Skills keep themselves current.** After a `brew upgrade skaldr`, an installed skill refreshes itself
the next time you run `skaldr` — no need to re-run `--install-skill`. It only ever refreshes a skill
you already installed (never creates one), never touches a symlinked skill (a contributor's live-edit
link), and never interferes with a render. Set `SKALDR_SKILL_SYNC=0` to turn the auto-refresh off.

`--install-plan-rule` is a separate, optional step: it adds a short, marker-delimited rule to
`~/.claude/CLAUDE.md` that steers the AI to author its working plans as live skaldr docs (rendered
with `--watch` so you can follow along). Delete that `skaldr:plan-rule` block to opt out; re-running
it refreshes the block in place. `--install-skill` never touches `CLAUDE.md` on its own.

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
