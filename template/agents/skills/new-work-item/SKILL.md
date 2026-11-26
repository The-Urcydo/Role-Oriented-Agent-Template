---
name: new-work-item
description: Creates and scopes a new work item in this repo's work/items/ folder. Use when asked to start, track, or plan a new piece of work, or when a request arrives in work/inbox/ that has no item yet.
metadata:
  requires: work-tracker
---
# New work item

**Role:** orchestrator or planner.

A one-off change with no follow-up needs no item. A decision that needs the human is a question (`agents/protocols/escalation.md`), not an item.

1. Choose the form. Under about an hour and no design questions: light item. Otherwise a full item. Work that needs a security review (step 3) is a full item: a light item has no place for `security-review.md`.
   ```
   python3 tools/new_item.py <slug> --title "Human readable title"          # full
   python3 tools/new_item.py <slug> --title "Human readable title" --light  # one file
   ```
   The tool prints the path to `handoff.md` (or the single file). The id is `<date>-<slug>`.
2. Write the brief (full items, planner only; the orchestrator skips this and hands over): open `brief.md` in the item folder. Fill goal, why now, acceptance criteria, constraints, out of scope, starting from the requester's own words. Every acceptance criterion must be observable and checkable by someone who was not there: a command, a file or a behavior, not an adjective.
3. Fill the Security review section with `required` or `not needed` and the reason. Required when the work touches authentication or authorization, secrets or personal data, dependencies, infrastructure, or anything exposed to users. The reviewer routes on this line: never leave the placeholder.
4. Check the repo already says nothing on it: skim `docs/INDEX.md`, `docs/decisions/` and `work/ACTIVE.md` for related docs, ADRs and items. Link them in the brief; do not create a duplicate item.
5. Set the first move. A planner with a complete brief moves the item to `planned`, as its charter says. Anyone else leaves it `draft` and names the planner: `python3 tools/transition.py <id> --next "Planner: write brief.md"`.
6. Confirm it shows on `work/ACTIVE.md` and run `python3 tools/check.py`.

Do not invent ids by hand; `new_item.py` handles dates and collisions.

## Verify

- The item has a goal, at least one acceptance criterion and an explicit out of scope, and each criterion can be checked without asking the requester.
- The Security review section is filled, not left as the placeholder.
- The next action names one owner, and the item is on `work/ACTIVE.md`.

## Stop and ask

- The request has two plausible readings or the scope is unbounded: queue the question and block the item on it.
