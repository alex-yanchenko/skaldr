# Working plans as live skaldr docs

When you write an implementation or working plan of any substance — a multi-step feature, refactor,
migration, or an investigation you'll act on — author it as a **skaldr YAML doc** (`skaldr --guide`
for the block palette), not a chat dump or a throwaway `.md`, and render it live for the user.

- **It's for _your_ working state, not just shareable output.** The `plan.yaml` on disk is your
  durable, compaction-proof record of the plan: after a context compaction, re-read the file to
  recover full state instead of trusting scrollback — the plan survives where the chat doesn't.
- **Render it live:** start `skaldr --watch plan.yaml -o plan.html` in the background so the user
  watches progress as you work. `--watch` re-renders on every save, so keeping the plan current costs
  nothing per edit — the YAML is the source of truth, the HTML is just the live view.
- **Shape it to the plan:** a `status_list` or `swimlane` of phases/tasks carrying state
  (done/current/pending/failed/blocked), a `callout` for open questions, a `table` with a `rollup` for
  done-vs-total, and `section.updated` for per-section freshness.
- **Keep it current:** update `plan.yaml` after each significant implementation step, and refresh it
  **before any context compaction**. A plan older than the working tree is drift.

Prose-only musing stays in chat; this is for a plan with structure worth tracking over time — not a
one-line task or a quick answer.
