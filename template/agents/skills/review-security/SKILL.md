---
name: review-security
description: Reviews a change for security and privacy risk and writes security-review.md with findings ranked by severity. Use when acting as the security role, or when asked for a security review of a diff or work item.
metadata:
  requires: work-tracker
---
# Review security

**Role:** security. This skill is the method. The security `ROLE.md` holds when you run, how the item goes back to the reviewer, and what you must never do (paste a secret, above all). Follow both.

Use this for changes that add inputs, trust boundaries, secrets, dependencies, permissions or user-facing surface. It is a focused review, not a substitute for the repo's tests.

1. Read the brief and the diff. Map what the change adds or alters: inputs, data flows, trust boundaries, secrets, dependencies, permissions and error paths.
2. Compare against the threat model in `docs/security/`. If the change adds surface the model does not cover, update the model.
3. Look for the common failures:
   - untrusted input reaching a shell, query, path or template;
   - secrets in code, logs, fixtures or error messages;
   - missing authorization, not just missing authentication;
   - unsafe defaults, permissive CORS or broad tokens;
   - dependencies with known vulnerabilities or unexpected install scripts;
   - personal data collected, logged or kept without a reason.
4. Create `security-review.md` with `python3 tools/item_file.py <id> security-review`, then fill it: findings ranked blocker (must fix before approval), major (must fix or the human accepts) or minor (fix now or log it), each with impact, evidence and a recommended fix. If the file already exists (the item came back for a second look), add a dated section to it: the tool will not overwrite it.
5. If a finding needs the human (risk acceptance, disclosure, spend), ask with `python3 tools/question.py ask`, giving a recommendation and the cost of guessing wrong.
6. Report; do not fix.

## Verify

- The review names the change and the surfaces it adds.
- Every finding has impact, evidence and a fix; secrets are described by location, never by value.
- The threat model is current, or the update is listed.
- The human, not you, owns any accepted risk.

## Stop and ask

- You find an exposed secret, a data-loss risk or a privacy issue.
- A finding needs disclosure or risk acceptance.
- The change needs production access or spend to verify, or you cannot tell whether the behavior is intended.
