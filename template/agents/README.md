---
title: Agents
type: meta
status: active
summary: The tool-neutral agent harness (roles, protocols and skills) and the dispatch table that routes work items to roles.
owner_role: architect
---
# agents/

The harness that tells any AI agent how to work in this repo. It is plain Markdown, so agents built on Claude, DeepSeek, Codex, Cursor or anything else can follow it.

| Folder | What it is |
|---|---|
| `roles/` | One folder per role with its charter `ROLE.md`: mission, what it reads, which skills it uses, which item files it writes, what it must never do |
| `protocols/` | The rules between roles: handoff state machine, escalation and grants, definition of done, review, parallel work |
| `skills/` | Every skill, one folder each, in the open Agent Skills format (`SKILL.md` per folder). A charter's `skills:` lists the ones its role uses |
| `adapters/` | Config for generating tool-specific files (Claude Code; optional Cursor, Copilot and Gemini) from the above |
| `ROSTER.md` | Generated table of roles, the skills each uses and what each owns |

## Roles and sessions

Roles come in three tiers. Flow roles own a status in the state machine: orchestrator, planner, builder, reviewer and the scribe. Advisory roles produce an artifact on request: architect and researcher. Optional modules are cut as one unit: security today, the role with its `review-security` skill.

A role runs as a hat by default: the session that holds the item reads the charter and acts as that role. A separate session is required only for review, and for security when installed: the reviewer never runs in the session that built the item. A role that needs its own context window, such as the researcher or a builder in a worktree, may run isolated; that is a choice of the session, not a status change.

## Dispatch table

The orchestrator reads `work/ACTIVE.md` and routes each item by status. `tools/transition.py` sets the default owner shown here; override it with `--owner`.

| Status | Meaning | Default next owner | What that role does |
|---|---|---|---|
| `draft` | Request captured, no plan yet | planner | Write `brief.md` (goal, acceptance criteria) and a plan if needed |
| `planned` | Brief and plan exist | builder | Implement; or architect first if the brief calls for a design or ADR |
| `in-progress` | Being built | builder | Build, test, keep the handoff current |
| `in-review` | Built, awaiting verification | reviewer (or `security` while a required security review is out) | Verify against the acceptance criteria, write `review.md`. If the brief's Security review section says `required`, the reviewer first lends the item to security (`--owner security`, status stays `in-review`) and takes it back with `security-review.md` |
| `verified` | Reviewer signed off | scribe (the reviewer passes `--owner orchestrator` when the builder's `Docs for the scribe:` line says `none, behavior unchanged.` and the diff agrees) | Scribe: update docs and `CHANGELOG.md`, then hand to orchestrator. Orchestrator: mark `done` |
| `done` | Finished | orchestrator | Archive with `tools/archive_item.py` |
| `canceled` | Dropped without shipping | orchestrator | Archive with `tools/archive_item.py` |
| `blocked` | Waiting on something | orchestrator | Resolve it, or raise a question to the human |
| `stale` | Idle too long | orchestrator | Re-triage: continue, re-plan, or cancel |

Full rules for each transition: `protocols/handoff.md`.

## Working with non-Claude agents

Any agent that can read files and run shell commands can use this harness: point it at `AGENTS.md`, tell it which role it plays, and have it read `roles/<role>/ROLE.md` plus the skills named in its `skills:` field (`ROSTER.md` lists them). Claude Code additionally gets generated subagents and skills under `.claude/` (see `adapters/README.md`). Cursor, GitHub Copilot and Gemini CLI adapters can be switched on in `adapters/targets.json`; for any other tool's native format, add a target there and extend `tools/sync_agents.py`.
