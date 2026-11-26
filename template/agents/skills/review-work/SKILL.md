---
name: review-work
description: Independently verifies a finished work item against its brief and writes review.md with evidence. Use when acting as the reviewer, or when asked to review, verify, or sign off on work someone else built.
metadata:
  requires: work-tracker
---
# Review work

**Role:** reviewer. This skill is the method. The reviewer's `ROLE.md` holds the routing: where the item goes before the verdict (the Security review section) and after it (who acts after `verified`, or back to the builder). Follow both.

You must not be the role that built the item. If you were, stop and hand it to a fresh session. The review is a different mind from the build: that is the point.

1. Read the brief first, then the handoff, then the diff (for a light item, its single file is both). Do not start from the builder's summary.
2. Read the brief's Security review section and route on it before any verdict, as the reviewer's `ROLE.md` says. If the item came back from security, read `security-review.md` before step 3.
3. Run the checks yourself. Do not trust pasted output:
   ```
   python3 tools/check.py
   <the project's test command>
   ```
4. For each acceptance criterion, verify it and record the evidence (command, output, file path). "Looks right" is not evidence.
5. Check the rules: accepted ADRs and file ownership respected, generated files in sync, and the builder's `Docs for the scribe:` line holds against the diff. Docs and the changelog are the scribe's job, not part of the review.
6. Look for what the criteria do not cover: files the brief did not mention, half-finished sections, leftover placeholders, secrets, unintended deletions, tests that pass for the wrong reason.
7. Create `review.md` with `python3 tools/item_file.py <id> review`, then fill it: a verdict (approve / changes requested / reject), per-criterion results and findings ranked by the severity scale in `agents/protocols/review.md`. Each finding says what, where, why it matters and a recommended fix. A light item has no `review.md`: fill its `## Review` section instead.
8. Move the item as the reviewer's `ROLE.md` says for your verdict; a `reject` is routed there too.
9. Do not fix findings yourself.

## Verify

- The review names the exact commit or diff it checked, and the verdict matches the findings.
- Every acceptance criterion has evidence, and you ran the checks yourself.
- Findings are ranked and actionable.
- The security-review decision and the docs line were checked against the brief and the diff.

## Stop and ask

- You built the change, so you are not independent.
- The acceptance criteria are missing or wrong.
- You find a security, data-loss or irreversible problem.
- The diff changes files the brief did not mention, and the change is not explained.
