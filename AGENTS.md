# skaldr — agent guide

skaldr renders **one YAML content file** into **one self-contained HTML report page**. You write
*what* the report says; skaldr owns all design. This file is the fast on-ramp when you open the
repo cold; the full authoring contract comes from the tool (`skaldr --guide`), not from here.

## Run it

skaldr is a CLI. Install once, or run from this checkout:

```bash
uv tool install skaldr      # or: pipx install skaldr   (needs Python ≥ 3.10)
# In a sandbox that can't fetch a managed interpreter, run from the checkout instead:
uv run skaldr ...           # uv uses the system Python ≥ 3.10
# or: pip install -e . && skaldr ...
```

## Author a report

1. **Load the contract from the tool** (matches the installed version — trust it over memory):
   `skaldr --guide` (the authoring guide: blocks, rules, the `table`, a complete example) and
   `skaldr --write-schema /tmp/s.json` (exact fields).
2. **Write the YAML from real evidence** — never invent numbers to fill the template.
3. **Render:** `skaldr report.yaml -o report.html`.
4. **Done = skaldr prints `OK` and the output file exists.** A structural mistake fails the build
   with a precise path (`blocks.3.items.2.value: ...`); read it, fix, re-run.

## Don't

- Don't hand-write HTML/CSS or hunt for a source generator — skaldr owns rendering; just run it.
- Don't restate the block catalog from memory — `skaldr --guide` is the source of truth, and it
  tracks the installed version.

The installable Claude skill (same guidance, auto-loaded when a user asks for a report) is
[`src/skaldr/skill/SKILL.md`](src/skaldr/skill/SKILL.md); install it with `skaldr --install-skill`.
