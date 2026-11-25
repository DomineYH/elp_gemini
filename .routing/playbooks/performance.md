---
id: performance
title: Performance
rule_refs: [QUAL-4, QUAL-7]
report_evidence:
  - baseline, after, delta, range and run count
  - what limits the number now
  - artifact path of the measurements
  - behavior-preservation check result
adapted_from: pstack skills/poteto-mode/playbooks/perf-issue.md @ 005d8f6 (MIT, see NOTICE.md)
---

# Performance

## Steps

1. Capture a baseline with a repeatable command on the path a user waits on; record environment and run count.
2. Find the measured cause from a profile or trace before changing code.
3. Try remedies cheapest first: stop doing the work, stop repeating it, do less, defer it, do it concurrently, make it cheaper. Stop when the target is met.
4. Re-measure with the same harness over alternating runs and confirm behavior is unchanged.

## Notes

A measured number is reported with its baseline, run count, range and what limits it (QUAL-7). Do not treat a single warm run, a different harness, or a type-check as the comparison.
