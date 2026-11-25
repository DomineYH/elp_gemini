---
id: refactor
title: Refactor
rule_refs: [QUAL-3, QUAL-4, QUAL-7]
report_evidence:
  - the pin and its result before and after
  - the structure that changed and what it removed
  - equivalence proof
  - what was tried and reverted
adapted_from: pstack skills/poteto-mode/playbooks/refactoring.md @ 005d8f6 (MIT, see NOTICE.md)
---

# Refactor

## Steps

1. Pin current behavior first: run existing protection; where it is missing add a characterization test, snapshot or old-vs-new equivalence script. Type-check and lint are not a pin.
2. State the target shape from the design_note; the reshape must delete branches, layers or invalid states, not add indirection.
3. Subtract first: delete dead code, collapse one-caller wrappers, drop redundant validation.
4. Move in small behavior-preserving steps with the pin green after each; migrate every caller and delete the old API in the same change; check renames in strings, docs and config.
5. Prove equivalence on the real artifact. A bug or missing feature found on the way is reported, not fixed in this order.

## Notes

This playbook preserves observable behavior. It is not a feature and not a bug fix. Improvements or defects found during the reshape stay out of the diff unless the current order already covers them (QUAL-3, VER-11).
