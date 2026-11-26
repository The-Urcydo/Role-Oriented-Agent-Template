---
name: record-decision
description: Records a significant technical or process decision as a numbered decision record with options, outcome and consequences. Use when choosing between real alternatives, reversing a past decision, or when asked why something is the way it is and no record exists.
---
# Record a decision

Use this when a choice has real alternatives and a future reader will need the reason. A small reversible choice inside your remit belongs in the pull request, not a record. Write for a reader six months from now who was not here, in active voice: "We will use X because Y."

1. Read the existing records first. Accepted decisions are binding: if the new choice conflicts, propose a superseding record. Never edit an accepted outcome, and never work around one.
2. Check the bar: hard to reverse, costly, security-relevant, affects several parts, or likely to be questioned later. If it does not meet it, put the choice in the pull request and stop.
3. Allocate the next number with the repository's tool. Never pick a number or create the file by hand when a tool exists.
4. Write the record:
   - **Context and problem:** the forces and the question.
   - **Decision drivers:** what matters and why.
   - **Considered options:** at least two, with their real trade-offs.
   - **Outcome:** the chosen option and the reason.
   - **Consequences:** what gets better, what gets worse, what stays neutral.
   - **Confirmation:** how the decision will be checked.
5. Set the status. A significant, costly or irreversible decision starts as `proposed`, and only the human moves it to `accepted`: ask through the repository's escalation route, not in chat. A decision the human already made, or a small reversible one inside your remit, may start as `accepted`.
6. Put a one-sentence summary in the front matter and link the affected docs and code.
7. Run the repository's check and confirm the file name, number, status and date are valid.

## Verify

- The record has context, at least two options, an outcome and consequences.
- The number is unique and the status matches who approved it.
- A reader six months from now understands why without asking anyone.
- The check passes.

## Stop and ask

- The decision is irreversible, costly or security-relevant, or reverses an accepted record.
- Two accepted records conflict.
- The record would include a secret or a personal path.
