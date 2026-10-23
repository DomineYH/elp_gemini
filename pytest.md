### Local pytest Parallel Execution

- Follow the existing Testing Policy when selecting test scope. Use targeted tests during implementation, affected tests and relevant integration tests after changes, and the full suite when required by risk or impact. Parallel execution must not expand or reduce that scope by itself.

- Keep serial execution until `pytest-xdist` is declared in the development dependencies and lockfile, and parallel execution has been validated for the selected scope. Do not enable parallel execution globally through default pytest options.

- Start validation with two workers. Do not use `-n auto` by default. Account for CPU and memory consumed by coding agents, browsers, and other test processes. Increase the worker count only after measuring runtime, resource usage, and reliability.

- Verify isolation of databases, temporary files, ports, accounts, and other shared resources before parallel execution. Keep the tested worktree fixed during the run. Separate processes or file-based scheduling do not guarantee isolation. Run tests that cannot be safely isolated in an explicit serial group without omitting them.

- Compare serial and parallel execution using the same code, environment, and selected scope. Verify that collected and executed test IDs, including parametrized cases, have no omissions or duplicates. Do not weaken assertions or introduce skips or xfails to make parallel execution pass. Claim full-suite parallel support only after full-suite equivalence has been verified; this comparison is not required after every edit.

- If parallel execution fails, hangs, or exhausts resources, preserve its logs and rerun the same scope serially for diagnosis. A serial pass does not resolve or invalidate a parallel failure. Keep the affected scope serial until the cause is fixed and parallel execution is revalidated. Do not hide failures with unconditional retries.

- Reuse valid verification evidence according to `verification_policy.evidence_reuse`; do not repeat identical checks solely because another role is performing the work. The same commit SHA alone is insufficient. Check uncommitted changes, shared APIs, fixtures, schemas, dependencies, configuration, environment, and integration targets. Rerun any scope whose evidence has been invalidated.

- Preserve required CI checks and independent verification gates. Local parallel execution and evidence reuse do not replace them.

- Report the tested revision and worktree state, environment, exact command, selected scope, worker count, collected and executed test counts, outcomes, elapsed time, log locations, and any untested scope with reasons. Distinguish fresh results from reused evidence.

Example command, only after the selected scope has passed parallel-safety validation:

```sh
uv run --frozen python -m pytest -q -n 2 --dist loadfile \
  tests/test_comparison_conversations.py \
  tests/test_comparison_conversation_migration.py
```

The paths above are examples, not a declaration that these files are parallel-safe. `--dist loadfile` assigns entire files to workers; it does not guarantee isolation, and selecting only one file may leave other workers idle.
