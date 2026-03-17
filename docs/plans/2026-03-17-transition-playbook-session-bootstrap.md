# Transition Playbook Session Bootstrap

Use this to start the fresh implementation session.

## Implementation Kickoff Prompt

```text
Implement the Transition Playbook plan in this repo.

Read these files first and use them as the source of truth:
- /Users/salmaanrauf/Documents/BD Tool/docs/plans/2026-03-17-transition-playbook-handoff.md
- /Users/salmaanrauf/Documents/BD Tool/docs/plans/2026-03-17-transition-playbook-execution-log.md
- /Users/salmaanrauf/Documents/BD Tool/docs/plans/2026-03-17-transition-playbook-implementation.md

Use the executing-plans skill and follow the implementation plan in batches with review checkpoints.

Important user preferences and guardrails:
- Optimize for clarity and trust, not automation theater.
- Keep the UX lightweight for MDs.
- Use a small structured transition form plus generated prompt preview.
- Keep Deep Research polling.
- Do not show the full Deep Research report inline by default.
- Keep the current generic deep research/chat path intact while building the transition flow.
- Treat the Jennifer Brady move as a synthetic scenario, not a verified public fact.
- Update /Users/salmaanrauf/Documents/BD Tool/docs/plans/2026-03-17-transition-playbook-execution-log.md continuously during implementation with:
  - what changed
  - how it changed
  - why it changed
  - tests run
  - results
  - blockers
  - user-preference tie-ins

Start by critically reviewing the plan for gaps or risks. If the plan looks sound, begin batch 1 and report back after that batch with verification results.
```

## Expected Starting Behavior

The implementation session should:
- load the three plan/handoff files above
- review the plan critically before coding
- execute tasks in batches
- update the execution log throughout
- stop at review checkpoints instead of silently running through the entire plan

## Notes

This bootstrap exists to minimize token waste and avoid losing product/context decisions from the design session.
