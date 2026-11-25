# Playbooks

이 디렉터리가 playbook의 **유일한 출처**다(v2.5.7부터). `jev_task_routing.json`의 `playbooks`에는 선택 규칙(`select`), 비개입 원칙(`non_override`), id → 파일 경로(`catalog`)만 있고 단계와 보고 증거는 없다. `init_routing.sh`가 이 폴더를 프로젝트의 `.routing/playbooks/`로 복사하고 파일별 sha256을 `.routing/INSTALLED.json`에 기록한다.

## 파일 형식

```markdown
---
id: bug_fix                     # 파일 이름·catalog 키와 같아야 함
title: Bug fix
rule_refs: [QUAL-4, QUAL-5]     # ROUTING_POLICY.md에 정의된 규칙 ID
report_evidence:                # 워커 보고서에 반드시 들어갈 증거
  - reproduction command and the broken behavior
adapted_from: 출처와 리비전
---

# Bug fix

## Steps

1. 한 줄에 한 단계. 6단계 이하, 단계당 260자 이하.

## Notes

호스트가 지시서를 쓸 때 참고하는 내용. 워커에게 보내지 않는다.
```

frontmatter는 위 다섯 키만 쓴다. 값은 한 줄 문자열, `[a, b]` 목록, 또는 `  - 항목` 목록이다. `verify_routing.py`가 형식·id·규칙 ID·단계 수와 길이를 검사한다.

## 호스트가 쓰는 방법 (QUAL-1)

1. `playbooks.select`에서 처음 맞는 항목으로 playbook id를 정한다. 선택 조건은 JSON에만 있다.
2. `.routing/playbooks/<id>.md`를 읽어 `## Steps`는 그대로, `report_evidence`는 목록으로 구현 지시서에 넣는다(`playbook_ref` = id).
3. `task_record.playbook_id`와 `task_record.playbook_sha256`(그 파일의 sha256)을 기록한다.
4. `## Notes`는 지시서를 쓸 때 반영하고 워커에게 그대로 보내지 않는다.

playbook은 `testing_mode`, 워크플로, 역할, 리스크를 고르거나 덮어쓰지 않는다. 테스트 순서가 충돌하면 `testing_mode`를 따르고, playbook이 요구하는 증거(예: 재현)는 그대로 필요하다.

## Catalog

| 파일 | 선택 조건 (`playbooks.select`) |
| --- | --- |
| [bug_fix.md](bug_fix.md) | `task_type == bug_fix` |
| [feature.md](feature.md) | `task_type` in [feature, ui_ux, api_integration, database, security] |
| [refactor.md](refactor.md) | `task_type == refactor` |
| [performance.md](performance.md) | `task_type == performance` |
| [investigation.md](investigation.md) | `work_mode == exploration` (프로토타입이 아닐 때) |
| [prototype.md](prototype.md) | `work_mode == exploration` AND `change_kind == disposable_prototype` |
| (없음) | `work_mode == emergency`, 또는 docs / tests / dependency_update / infrastructure (delivery의 analysis·mixed·other는 이 단계 전에 CLS-7b·CLS-8·CLS-5에서 멈춤) |

작업 유형별 검증 요구(UI는 렌더링 확인, DB는 비운영 데이터로 마이그레이션 등)는 playbook이 아니라 `jev_task_routing.json`의 `modifiers`에 있다.

## 고치는 방법

- 단계·보고 증거·노트는 이 폴더의 파일만 고친다. JSON은 건드리지 않는다.
- 새 playbook을 추가하면 네 곳을 함께 고친다: 이 폴더의 `<id>.md`, `jev_task_routing.json#/playbooks/catalog`(경로)와 `select`(선택 조건), `jev_task_routing.schema.json#/$defs/playbookId`의 `enum`(id 추가). `build_config.py`도 같은 내용으로 맞춘다. `verify_routing.py`가 catalog와 enum이 다르면 FAIL을 낸다.
- 고친 뒤 설치한 프로젝트에서 `python3 .routing/verify_routing.py`로 확인한다.

출처 고지: [NOTICE.md](NOTICE.md)
