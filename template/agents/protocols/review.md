---
title: Review protocol
type: reference
status: active
summary: How the reviewer verifies a work item independently and how findings are reported and ranked.
owner_role: architect
---
# Review protocol

Independent review is the main quality gate in a repo with no human in the loop for every change.

## Independence

- The reviewer is never the role that built the item. With a single model playing both roles, use a fresh session with no memory of the build, and read the brief before the builder's summary.
- The reviewer does not fix findings. Fixing makes the reviewer a second builder and removes the second pair of eyes.
- The author of an item's brief is not its only independent reviewer. An important item (one that changes tools, workflows, the agent harness or root rules) is also reviewed by a fresh session that did not write or shape the brief. That reviewer recomputes every count and file list in the brief, the handoff and the description from the repository.

## Procedure

1. Read `brief.md`, then `handoff.md`, then the diff. Note anything the diff changes that the brief did not ask for. If the brief's Security review section says `required`, route the item to security before any verdict (the "Route before any verdict" section of `roles/reviewer/ROLE.md`).
2. Run the checks yourself: `python3 tools/check.py` and the project's tests.
3. For each acceptance criterion: verify it, and record the evidence. "Looks right" is not evidence.
4. Check the rules: ADRs respected, ownership respected, generated files in sync, and the builder's `Docs for the scribe:` line holds against the diff. Docs and the changelog are the scribe's job after the review.
5. Write `review.md` (template: `work/_templates/review.md`).

## Findings

| Severity | Meaning | Effect |
|---|---|---|
| blocker | Wrong, unsafe, or breaks a rule or ADR | Must fix before verified |
| major | Meets the letter but misses the intent, or is fragile | Must fix or be accepted by the human |
| minor | Style, naming, small improvements | Fix now or log a new item |

Each finding states: what, where (file and line), why it matters, and a recommended fix. Do not inflate a style preference into a blocker, and do not soften a data-loss risk into a minor.

## Verdicts

- **approve**: move to `verified` with evidence.
- **changes requested**: move back to `in-progress` with the builder as owner and `--next "fix findings in review.md"`.
- **reject**: the approach is wrong; move to `blocked`, `draft` (to re-plan), or `canceled` (to drop it) with an explanation in `--next`.

A second review is needed after changes requested if any blocker was found.

## Routing

Where the item goes before the verdict (security first when the brief requires it) and after it (the scribe or the orchestrator after `approve`, the builder after `changes requested`, planning after `reject`) is in the reviewer's `ROLE.md`. The `review-work` skill is the method.
