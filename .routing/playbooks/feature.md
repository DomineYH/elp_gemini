---
id: feature
title: Feature
rule_refs: [QUAL-2, QUAL-4, QUAL-6, QUAL-7, QUAL-8]
report_evidence:
  - each acceptance criterion mapped to a check and result ref
  - choices made within local discretion and why
  - units with the check run after each
  - open decisions
adapted_from: pstack skills/poteto-mode/playbooks/feature.md @ 005d8f6 (MIT, see NOTICE.md)
---

# Feature

## Steps

1. Trace the affected subsystem: entry points, callers, the data that flows through.
2. Build to the order's design_note; if the code contradicts it, stop and return NEEDS_DECISION instead of improvising another shape.
3. Work in verifiable units, each ending in a check and a commit; write tests per the accepted testing_mode against observable behavior.
4. When a shared primitive changes, update every consumer and verify each.
5. Verify on the matching surface, self-review the diff, leave small ordered commits.

## Notes

A `design_note` is required when `code_quality.design_note.required_when` holds (delivery, risk in [standard, high], change_kind in [change_behavior, preserve_behavior]) — QUAL-2. Expected results come from the requirements or an independent contract, not from transcribing the new implementation (QUAL-6, VER-2).

Do not open a PR unless the order and the user authorize it (AUTH-4). PR form, when authorized, is `code_quality.pr_body` (QUAL-10).
