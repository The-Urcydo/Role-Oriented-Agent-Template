---
name: write-skill
description: Creates or revises an agent skill. Use when a procedure should become a skill, when fixing an existing skill, or when asked how to write one.
---
# Write a skill

Use this when a procedure should become a skill. A skill is a procedure: not a fact every session needs, not a role rule, not a one-off.

1. Confirm the content is a skill. Facts every session needs go in the root agent rules. Who owns an item, its status moves and a role's limits go in the role's charter. A one-off change belongs in the pull request. If an existing skill already covers the job, improve it instead of adding a near-duplicate.
2. Read `references/checklist.md` for the front matter and the quality rules.
3. Create the folder `<name>/SKILL.md` in the project's skills folder. The name is lowercase letters, digits and single hyphens, and equals the folder name.
4. Write the description first. It says what the skill does and when to use it; it is the only text an agent sees before it loads the body.
5. Write the body in about 40 lines: ordered steps, how to verify the result, and when to stop and ask. Say who uses it only if the steps differ by role; the role charters list the skills they use.
6. Move long detail, templates and commands to `references/`, `scripts/` or `assets/`, linked relative to the skill folder, so the skill stays portable.
7. Write for any agent: no tool's invocation syntax and no secret or personal path in the skill. If the steps need this repo's work tracker, say so with `metadata.requires: work-tracker` and write them concretely; otherwise keep them neutral.
8. A skill that changes shared state or spends money gets `metadata.invocation: user`, and the owner approves it.
9. Run the repository's check and fix what it reports.

## Verify

- The check passes, and every item in `references/checklist.md` holds.
- Starting from the description alone, an agent can tell when to use the skill.
- The body fits in about 40 lines, and every link resolves from the skill folder.

## Stop and ask

- The request is a fact, a role rule or a one-off.
- The skill would need a secret, a personal path or network access nobody has documented.
- The skill is imported from elsewhere: keep its provenance (source, commit, license) beside it.
