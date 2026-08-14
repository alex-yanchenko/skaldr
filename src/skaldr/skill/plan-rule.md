# Working plans as live skaldr docs

When you write an implementation or working plan of any substance — a multi-step feature, refactor,
migration, or an investigation you'll act on — author it as a **skaldr YAML doc** (`skaldr --guide`
for the block palette), not a chat dump or a throwaway `.md`, and render it live for the user.

- **It's for _your_ working state, not just shareable output.** The `plan.yaml` on disk is your
  durable, compaction-proof record of the plan: after a context compaction, re-read the file to
  recover full state instead of trusting scrollback — the plan survives where the chat doesn't.
- **Render it live, without a watcher process:** render once with `skaldr plan.yaml -o plan.html
  --live` and let the user open `plan.html`; the page re-reads itself whenever they return to the
  tab, keeping scroll position and open sections. After each edit run `skaldr plan.yaml -o plan.html
  --if-stale`, which is a no-op when the page is already current, so keeping the plan live costs
  nothing per edit. Don't reach for `--watch` here: it needs a process that stays alive, and an agent
  harness reaps background jobs between turns, so it dies and the page goes stale without saying so.
  The YAML is the source of truth; the HTML is just the view.
- **The YAML is the single source of truth.** Every plan or status change goes in it and is
  re-rendered. Never scatter status into sidecar `.md` files: that leaves the rendered doc stale and
  makes the reader hunt across files for the current state.
- **Shape it to the plan:** a `status_list` (done/current/pending/failed/blocked) or `swimlane`
  (done/current/todo/blocked/deferred) of phases/tasks, a `callout` for open questions, a `table` with
  a `rollup` for done-vs-total, and `section.updated` for per-section freshness.
- **Keep it current:** update `plan.yaml` after each significant implementation step, and refresh it
  **before any context compaction**. A plan older than the working tree is drift.

Prose-only musing stays in chat; this is for a plan with structure worth tracking over time — not a
one-line task or a quick answer.
