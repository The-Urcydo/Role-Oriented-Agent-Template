---
name: plan-work
description: Turns a brief into an ordered plan and task list with risks, sequence and verification. Use when the work needs more than a few steps, or the brief needs decomposition before anyone builds.
metadata:
  requires: work-tracker
---
# Plan work

**Role:** planner. A small task with a clear brief needs no plan: the brief and `new-work-item` are enough. The plan is the planning artifact; do not start building.

1. Read `brief.md` and its acceptance criteria. If the goal is ambiguous, a criterion is missing or the scope is unbounded, stop and ask (`agents/protocols/escalation.md`) instead of planning around the gap.
2. Restate the goal and the acceptance criteria in your own words. List the constraints, the decisions already made and what is out of scope.
3. Check what the repo already says: `docs/INDEX.md`, `docs/decisions/` and `work/ACTIVE.md`. Do not plan a duplicate. If a design decision must come first, hand it to the architect or record it first.
4. Create the plan and the task list: `python3 tools/item_file.py <id> plan` and `python3 tools/item_file.py <id> tasks`.
5. In `plan.md`, name the approach and the files, components or interfaces involved. List the risks and unknowns, each with a likelihood and a mitigation, and what would make the plan wrong.
6. Sequence the work: what must happen first, what can run in parallel, what must wait for a merge.
7. In `tasks.md`, write ordered tasks. Each is small enough for one session and ends with a check the builder can run.
8. State how the plan will be tested: the commands, the observable behavior and the evidence the reviewer will need.
9. Link the plan from the handoff and name the first task in `next_action`.

## Verify

- The plan names the goal and every acceptance criterion.
- Each risk has a mitigation, and each unknown has a way to resolve it.
- Every task is small enough for one session and has a check.
- The sequence names dependencies and what can run in parallel; out of scope is explicit.

## Stop and ask

- The brief is missing, ambiguous or contradictory, or the scope cannot be bounded without inventing a requirement.
- The plan needs a decision only the human can make (spend, production access, reversing an accepted ADR).
- A task needs a security review that the brief has not decided.
