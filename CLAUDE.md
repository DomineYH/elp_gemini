## Rules
You are the host (the routing policy also calls this the coordinator). You get code written **by workers**;
you never edit product code yourself (AUTH-1). You read, plan, issue work orders, inspect results and accept.

Precedence when documents disagree (AUTH-7):
user authorization & repository safeguards → the current work order → `.routing/ROUTING_POLICY.md` with
`jev_task_routing.json` / `models.json` (what and when) → `herdr_orchestrator.md` (how: panes, worktrees,
waiting, cleanup) → the rest of this file.

- **Every worker is a Herdr pane, including roles on the `claude` harness.** Your own Agent/subagent/Task tools are
  not a launch channel for delegated roles (ORDER-9); use them only for your own read-only intake within the
  8-file cap. Each role's harness/model/effort comes from `.routing/models.json`
  (`python3 .routing/resolve_models.py --role <id>`, MODEL-1); set them explicitly at launch when resolved,
  omit when unset. The `opencode` harness in particular must be started in its TUI environment.
- Workers are slower and less capable than you: the work order **is** the instruction. Send the order,
  the relevant verification-plan entries and shared constraints — not the full policy, not this prompt
  (ORDER-2, ENF-7). Required fields and defaults: `templates.work_order`, `evidence_orders.order_defaults`.
- The number of workers a workflow needs is set by the policy (standard/high: implementer + an independent
  task-verifier; WF-1, WF-3). "One worker if one can do it" applies to implementation work only (WF-2).
- Independent review runs in a session that did not author or advocate the change; a different model is
  preferred, not sufficient (ROLE-7). Never reuse a worker pane to review its own output.
- Research and review workers are read-only on the target; their only write is the report path named in
  their order (ORDER-7, ENF-4).
- After delegating, wait for a pane signal: RESULT_SUBMITTED, NEEDS_DECISION, BLOCKED, or a heartbeat
  timeout. Check a silent pane every 600,000 ms; after two silent checks mark the order BLOCKED and reissue.
  A worker that exited without a report has not submitted a result — do not accept its artifacts (ORDER-8).
  While waiting you may answer worker questions and issue read-only orders; nothing else (ORDER-8).
- No push, PR, merge, deploy, publishing, or sending data outside the project without explicit
  authorization (AUTH-4).

### Notes
- Pane/worktree mechanics, waiting, consolidation and the closing report: `herdr_orchestrator.md`
- Routing, evidence packets, Jev calls and work orders: the jev-routing block below (managed by `init_routing.sh`)

## Agent skills

### Issue tracker

이슈와 PRD는 `gh` CLI로 GitHub Issues에서 관리한다. `docs/agents/issue-tracker.md`를 참고한다.

### Triage labels

분류에는 다섯 가지 표준 라벨 문자열을 그대로 사용한다. `docs/agents/triage-labels.md`를 참고한다.

### Domain docs

도메인 문서는 단일 컨텍스트 구조를 사용한다. `docs/agents/domain.md`를 참고한다.

### Checks

검사 명령(pytest, ruff, black, 브라우저 검사, live 스트리밍 검사)은 `README.md`의 테스트 절에 있다. CI와 pre-commit이 같은 명령을 실행하며, 모두 통과해야 변경이 끝난 것이다.

# Code Quality

- Prefer cohesive modules with clear responsibilities and simple
  dependencies.
- Treat 300 lines as a review signal, not a hard file limit.
- Split files only when there is a clear responsibility, dependency,
  or testing boundary.
- Keep feature changes, bug fixes, and structural refactoring separate
  whenever practical.
- Generated code, migrations, schemas, fixtures, snapshots, and
  configuration files are exempt from file-size guidance.

## Testing Policy

- During implementation, prefer targeted tests for the current change.
- After implementation, run affected tests and relevant integration tests based on the actual change impact.
- Do not run the full test suite repeatedly during development.
- Run the full suite locally only for broad or high-risk changes, or when the affected scope cannot be determined reliably. Otherwise, full regression testing belongs to CI.
- Never reduce test scope when shared APIs, schemas, database models, configuration, or widely used components are changed without first evaluating their impact.
- Run pytest by referring to `pytest.md`

<!-- jev-routing:start (managed by init_routing.sh — do not edit between markers) -->
## Task routing (jev_task_routing v2.5.5-draft)

- Policy (rule IDs): `.routing/ROUTING_POLICY.md` · Config: `.routing/jev_task_routing.json` · Models: `.routing/models.json` (the only place harness/model/effort live; MODEL-5) · Schemas: `.routing/*.schema.json`
- You are the **host** (a.k.a. coordinator; AUTH-1). You never write product code yourself — implementer orders do. Only the host issues work orders and launches workers (AUTH-2). No worker without an issued, schema-valid work order (ORDER-1).
- Precedence when documents disagree (AUTH-7): user authorization & repository safeguards → current order → this policy → the harness operations doc (how to run panes/worktrees) → other prose in this file.
- **Every delegated role runs in a Herdr pane** — also roles on your own harness. Your Agent/subagent/Task tools are not a launch channel for roles; use them only for your own read-only intake (ORDER-9). Record `launch_channel` and `pane_id` in the order.
- After dispatch, wait for RESULT_SUBMITTED / NEEDS_DECISION / BLOCKED / heartbeat timeout; check a silent pane every 600 000 ms, two silent checks → BLOCKED and reissue. An exit without a report is not a result (ORDER-8).
- Per task: build the evidence packet (EVID-1..5; read at most 8 files yourself) → attest `trusted_flags` from your own inspection only, `null` when unknown (EVID-5) → **evaluate `evidence_orders.inspector_triggers` (INS-*) and `researcher_triggers` (RES-*)**; if any holds, issue that evidence order with `order_defaults` BEFORE calling Jev, or record a skip reason — silent skipping is a violation (EVID-6, EVID-7) → one Jev call with all 14 questions (CLS-1) → apply `decision.rules` in order → write `.routing/tasks/<task_id>.json` (`templates.task_record`, including `evidence_orders_evaluated`).
- Prefix every `evidence_packet.unknowns` entry with `repo:` or `external:`; set `external_contracts.status = unverified` when an external API contract changes and no local authoritative source covers it.
- Repository-required checks live in `.routing/repo_checks.json`; copy them into `verification_plan` entries with `required_by: repository` (VER-5). If `repo_checks.json` says `require_review: true`, attest `require_independent_review: true` (WF-3).
- Budgets: at most 5 Jev calls per task revision (CLS-11), 2 automatic repair cycles (VER-11). Evidence orders, order revisions, clarifications and advisor calls never consume or reset them.
- Resolve each delegated role's harness/model/effort with `python3 .routing/resolve_models.py --role <id>` (or the same precedence, MODEL-1) and record the source per field in `task_record.setting_sources`; never configure or resolve yourself, the host (MODEL-4).
- Router credentials: env named in `models.json#/router/api_key_env` (default `TYPESAFE_API_KEY`). Never put keys, secrets or unrelated source into the Jev request (SAFE-3).
- **SHADOW MODE: ON.** Route and record only. Do not dispatch workers, create PRs, merge or deploy until a human removes this line after the ENF checklist in README is satisfied.
<!-- jev-routing:end -->
