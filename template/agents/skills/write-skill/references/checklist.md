# Skill checklist

A skill follows the open Agent Skills format. Only the fields below are allowed in `SKILL.md`; a tool-specific field is generated into that tool's copy, never written here.

## Front matter

| Field | Rule |
|---|---|
| `name` | Required. 1 to 64 characters: lowercase letters, digits, single hyphens, no leading or trailing hyphen. Equals the folder name and is unique across all skills. |
| `description` | Required. 1 to 1024 characters: what it does and when to use it. |
| `compatibility` | Optional. 1 to 500 characters: environment requirements only. |
| `metadata.invocation` | Optional, `user` or absent. `user` means only the owner starts it (shared state, spend, approval). Absent means any agent may. |
| `metadata.requires` | Optional, `work-tracker`. Set it when the steps create, read or move work items, or need this template's tools. The installer skips these skills by default. |
| `license` | Optional. Only for an imported skill: the upstream license. |
| `allowed-tools` | Optional, experimental. Space-separated; no commas. |

`metadata` is a map of strings, one level deep.

## Body

- [ ] Opens with what the skill does and when it applies.
- [ ] Steps are ordered and concrete; verification is a command, a check or an observable result.
- [ ] Stop conditions are explicit.
- [ ] About 40 lines; the checker warns above its limit. Detail lives in `references/`.
- [ ] No `TODO` placeholders; relative links resolve from the skill folder.
- [ ] No secret, personal path or machine-specific assumption.
- [ ] No tool's invocation syntax. A neutral skill has no repo commands; a tracker-bound one (`requires: work-tracker`) names them.
- [ ] Routing (who owns an item, which status it moves to) is in the role charter, not here; a fact lives in one place.

## Imported skills

- [ ] A `PROVENANCE.md` beside it holds the source URL, commit, author, license, what changed and the date.
- [ ] The upstream license allows redistribution with this template.
