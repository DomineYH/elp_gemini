# Herdr Operating Rules (harness operations document)

This document covers only **how** workers are launched, waited on and wound down. What to assign to whom, when, and how results are verified and accepted is set by `.routing/ROUTING_POLICY.md`; where this document disagrees with it, the policy wins (AUTH-7). Rule IDs below refer to that policy.

## 1. Before starting
- Check the workers, panes and working directories available in the current Herdr server and session.
- Resolve each role's harness/model/effort with `python3 .routing/resolve_models.py --role <id>` and set them explicitly when launching the pane (MODEL-1). For any field that resolves to nothing, omit the argument and let the harness default apply. The `opencode` harness must always be started in its TUI environment.
- Confirm that the pane has the tools the role needs (file read/search; web access for researcher) — see `evidence_orders.tool_preflight`. If a tool is missing, that role is BLOCKED; the host does not answer the gap from memory instead (EVID-7).

## 2. Reusing and splitting workers
- An existing pane may be reused for new work. It is **never** reused to review its own output (ROLE-7).
- Split implementation work only into pieces that can move independently. If one implementer can finish the work, use one. This "minimum" applies to implementation workers only; it never reduces the reviewers and testers the workflow requires (WF-2, WF-3).
- Give each worker that writes concurrently to a Git repository its own worktree. Two writers never share a checkout (SAFE-4).

## 3. Handing over instructions
- What goes to a pane is a single work order: the required fields of `templates.work_order` (objective, acceptance criteria, input refs and version, read/write scope, allowed actions, constraints and local discretion, stop conditions, deliverable, report route), the relevant verification-plan entries and shared constraints only (ORDER-2). Never send the full policy, this document or the host prompt (ENF-7).
- Evidence roles (inspector/researcher) use `evidence_orders.order_defaults`: read-only on the target repository, a single write path `.routing/evidence/<order_id>.json` (ORDER-7).
- Never ask a worker to relay anything to another pane. All relaying is done by the host (AUTH-2).

## 4. Waiting and liveness (ORDER-8)
- After delegating, wait for a signal from the pane. There are four: `RESULT_SUBMITTED`, `NEEDS_DECISION`, `BLOCKED`, or a heartbeat timeout.
- If 600,000 ms pass with no signal, check the pane's state (still running, or exited). After two consecutive silent checks, record the order as BLOCKED and reissue it or escalate to the user.
- A worker that exited without a report has **not** submitted a result. Do not accept whatever it left behind; inspect it only for diagnosis, then reissue under a new revision (AUTH-5).
- While waiting, the host may: answer a worker's `NEEDS_DECISION` (Q-2), issue read-only evidence or consultation orders, inspect reports and artifacts already returned, record state. The host may not: edit product code, put a second writer on the same resources, or accept the task.

## 5. Handling reports
- Worker reports are short: outcome, commit or artifact location, verification results, open issues. Full logs never go into the main conversation.
- After reading a report, always inspect the actual diff, screenshots or artifacts yourself. A completion message or a reviewer's PASS is an input to acceptance, not acceptance (AUTH-5, VER-7).
- When independent review is needed, have a worker in a **different session** — one that neither authored nor advocated the change — inspect a pinned commit or artifact version. A different model is better still, but is not by itself independence (ROLE-7).
- Resolve factual disagreements with tests or verifiable evidence. The judgement is the host's (Q-2).

## 6. Consolidation
- Gather accepted changes into one checkout and integrate there. Integration is a new target, so rerun the required current-head checks under the policy's revalidation rule (VER-10 `target_or_contract_change`). Evidence whose validity is established may be reused under VER-9, labelled `reused` / `revalidated_from_prior_revision`.
- Unless the user has explicitly authorized it, do not push, open a PR, merge, deploy, publish, touch production or send sensitive data outside (AUTH-4). Without authorization, report "ready to merge" and stop.

## 7. Cleanup and closing
- Release the panes, worktrees and temporary resources created for this task once they are no longer needed. Preserve existing work and any artifacts not yet delivered.
- Close with four items: what was completed / verification evidence (commands, target revision, result refs) / open or unverified items / panes and worktrees still held.
