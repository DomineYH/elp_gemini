---
id: prototype
title: Prototype
rule_refs: [QUAL-11, WF-4]
report_evidence:
  - variants built and the scratch path
  - the observation for each variant
  - tradeoffs and a recommendation
  - a plain statement that the code is throwaway
adapted_from: pstack skills/poteto-mode/playbooks/prototype.md @ 005d8f6 (MIT, see NOTICE.md)
---

# Prototype

## Steps

1. State the decision the prototype exists to make; no decision, no prototype.
2. Build throwaway inside the order's isolated scratch scope, outside product source; no tests, no abstractions.
3. When comparing alternatives, build them side by side behind one switch, each labeled.
4. Observe the thing being decided (output, timing, screenshot) and record it.

## Notes

An exploration prototype is exempt from the delivery QUAL set by design — throwaway code whose deliverable is the decision — and is never adopted without delivery reclassification (QUAL-11, WF-4).
