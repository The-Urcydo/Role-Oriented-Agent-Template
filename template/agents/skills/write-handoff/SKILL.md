---
name: write-handoff
description: Updates a work item's handoff.md and moves its status so a fresh session or another role can continue. Use before stopping work, when switching roles, or whenever a work item changes state.
metadata:
  requires: work-tracker
---
# Write a handoff

**Role:** any role holding the item. `handoff.md` is the one item file every role edits. The next session has no memory: make `handoff.md` the only thing it needs.

1. Open `work/items/<id>/handoff.md` (or the single-file item) and update the body, keeping it under about 60 lines:
   - **Current state**: one paragraph on where things stand right now.
   - **Decisions made**: choices that must not be re-litigated, with a pointer to the ADR if there is one.
   - **Dead ends already tried**: so nobody repeats them.
2. Set the `do_not` list in the front matter for anything the next role must avoid.
3. Builder only: write the docs line, every time, because the reviewer routes on it. At the end of **Current state** (a light item: in its `## Docs for the scribe` section):
   - `Docs for the scribe: none, behavior unchanged.` when you changed no behavior and no doc describes what you touched (for each changed path, `git grep -n -F "<path>" -- docs` finds nothing);
   - otherwise `Docs for the scribe: <the docs to update, and the CHANGELOG.md line>`.

   Later roles read the line and never rewrite it.
4. Move the status with the tool; do not edit `status` by hand:
   ```
   python3 tools/transition.py <id> <status> --by <role> --next "<one sentence for the next role>" [--owner <role>] [--evidence "<command or link>"]
   ```
   `in-review`, `verified` and `done` need `--evidence`. `blocked` needs `--next` saying what unblocks it. To change only the next step, owner or evidence, leave the status out: `python3 tools/transition.py <id> --next "..."`.
5. Run `python3 tools/check.py`. It must pass before you stop.

Evidence is what you ran or a link, not "tests pass". If the tool refuses a move, read its message: it names the missing rule.

## Verify

- A reader can name the next action without the old conversation, and knows what is decided, what has failed and what must not happen next.
- Every claim has evidence or a file path, `do_not` is current, and the status was set by the tool.
- The builder's docs line is present.

## Stop and ask

- The tool refuses the move and you cannot meet the rule it names.
- The next action depends on a decision the human has not made.
- The handoff would contain a secret or a personal path.
