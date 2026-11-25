---
id: bug_fix
title: Bug fix
rule_refs: [QUAL-4, QUAL-5, QUAL-7]
report_evidence:
  - reproduction command and the broken behavior
  - root cause with file:line
  - failing-then-passing reproduction output, verbatim
  - other instances of the same fault
adapted_from: pstack skills/poteto-mode/playbooks/bug-fix.md @ 005d8f6 (MIT, see NOTICE.md)
---

# Bug fix

## Steps

1. Reproduce the defect on the surface where it was observed before changing code; if it will not reproduce, tighten conditions or add instrumentation, then return NEEDS_DECISION with what was tried.
2. Narrow the cause by elimination: list candidate causes, take the split that removes the most, decide each with runtime evidence rather than by reading alone.
3. Fix at the first place the system went wrong, with the smallest change the evidence justifies; revert anything a refuted hypothesis motivated.
4. Re-run the original reproduction on the same surface; it must now pass. Unit tests alone show branch behavior, not absence of the defect.
5. Keep a regression check; under test_first, commit the failing check before the fix.

## Notes

An environment failure is not a reproduced defect. "Might help" extra guards do not ship (QUAL-3, QUAL-5). Fix the same fault elsewhere only when it is inside the write scope; report out-of-scope instances.

Where a step and the accepted `testing_mode` disagree on test order, `testing_mode` governs and the reproduction evidence is still required (QUAL-1). Under `test_first`, do not invent a heavy, brittle, or integration-only test merely to stage a red; use the closest executable regression check (VER-2).
