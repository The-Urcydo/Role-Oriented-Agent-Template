---
name: write-doc
description: Creates or updates a documentation page using the right Diataxis type and a one-sentence summary. Use whenever adding, changing, moving or deleting a doc.
---
# Write a doc

Use this when a change makes documentation wrong or incomplete, or when a reader needs a page that does not exist. Write only what you can verify. If the page describes code and the code disagrees, find out which is right before you write.

1. Pick exactly one type by the reader's need:
   - **tutorial:** a beginner learns by doing; the steps must work every time.
   - **how-to:** someone who knows the basics solves one task; a recipe.
   - **reference:** someone looks up a fact; accurate, complete, no opinions or instructions.
   - **explanation:** someone wants to understand why; context, trade-offs, history.

   If the page needs two types, write two pages and link them.
2. Check the docs index first. Update an existing page rather than adding a near-duplicate.
3. Create the page with the repository's doc tool, so the front matter is valid. Give it a one-sentence summary a stranger can judge it by.
4. Write it from the reader's problem to the outcome: one job per page, split when it passes about 300 lines. Link related pages and code.
5. If it describes code, list the code files in its front matter and set the last-verified date to today.
6. Delete or mark deprecated anything the change makes wrong. A stale page is worse than none.
7. Regenerate the docs index with the repository's tool (never edit it by hand), then run the repository's check.

## Verify

- The page has one type and one job, and the index lists it with its summary.
- Every command, path and link on the page resolves.
- No page the change made wrong is still active.
- The check passes.

## Stop and ask

- The page would need two types: split it instead of guessing.
- The fact is unverified, or the code and the docs disagree and you cannot tell which is right.
- The page would delete something another owner keeps, or contain a secret or a personal path.
