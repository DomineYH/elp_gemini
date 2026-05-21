# 평가기준 활성/비활성 토글 동시성 처리

- 작성일: 2026-05-21
- 작성자: DomineYH (with Claude)
- 범위: `app/routers/admin/criteria.py`, `app/static/js/criteria_list.js`, 관련 테스트

## 1. 배경

평가기준 관리 화면에서 활성/비활성 체크박스를 연속으로 토글하면 다음 두 메시지가 노출된다.

- `상태 변경 실패: HTTP 503`
- 상단 배너의 "⚠ 동기화 필요" + **재동기화** 버튼

원인은 클라우드(File Search) `alias-map` 문서의 반영 시간이 수 초~수십 초 걸리는 동안 두 번째 mutation 요청이 들어와, 서버가 충돌을 정상 처리하지 못하고 `sync_state = needs_resync`로 마킹하기 때문이다.

## 2. 가설 검증

사용자 가설("클라우드 반영 시간 동안 연속 토글하면 충돌")은 정확하다. 503의 두 발생 경로를 코드에서 확인했다.

### 경로 A — `require_criteria_sync_ready` 게이트

`app/dependencies.py:110-122`. `app_state.sync_state`가 `ok`가 아니면 의존성 단계에서 즉시 `HTTP 503 "평가기준이 동기화 중이거나 사용할 수 없습니다."`를 던진다. 첫 번째 토글이 진행 중 어떤 예외로든 `_mark_criteria_needs_resync`로 떨어지면(`app/routers/admin/criteria.py:71-89`) 이후 모든 mutation이 차단된다.

### 경로 B — `alias_map` 다중 문서 충돌

`app/services/criteria_alias_map_service.py:197-250`. `replace()`는 **upload-then-delete** 순서이므로 잠시 두 개의 `alias-map` 문서가 공존한다. 동시에 두 번째 토글의 `fetch()`(`criteria_alias_map_service.py:106-195`)가 두 문서를 모두 보고, 그중 하나라도 parse 실패하거나 일관성이 깨지면 `AliasMapParseError` → `_raise_alias_map_parse_unavailable` → `HTTP 503 "alias_map 파싱 실패 — 재동기화가 필요합니다."`로 떨어진다. 동시에 `sync_state`가 `needs_resync`로 마킹되어 화면 배너가 바뀐다.

### 클라이언트 측

`app/static/js/criteria_list.js:5-26`. 체크박스 핸들러에 in-flight 락이 없다. 응답을 기다리는 동안 사용자가 다시 토글하면 즉시 두 번째 `fetch`가 출발한다. PR #75에서 라벨만 optimistic update로 갱신하고 체크박스 자체는 즉시 반영되지만, 입력 차단은 도입되지 않았다.

## 3. 목표

- 사용자가 빠르게 연속 클릭해도 503이 발생하지 않는다.
- 클라우드 반영이 진행 중임을 UI가 명확히 알린다("반영중").
- `sync_state = needs_resync`로의 우발적 전이를 줄여, 정상 사용 중 "재동기화" 버튼이 노출되지 않게 한다.

비목표: 멀티 워커/멀티 프로세스 환경 지원, 클라이언트 자동 재시도, 일반 진행 표시 스피너.

## 4. 설계

### 4.1 클라이언트 락 (`app/static/js/criteria_list.js`)

체크박스 change 핸들러에서 요청 시작 시점에 입력을 잠그고, 응답 도착 시 해제한다.

- 시작 시: `cb.disabled = true`, 라벨을 `wasChecked ? '활성 반영중…' : '비활성 반영중…'` 으로 변경.
- 성공 시: 라벨을 `wasChecked ? '활성' : '비활성'`으로 확정, `cb.disabled = false`.
- 실패 시: `cb.checked = previous`, 라벨을 `previousLabelText`로 롤백, `cb.disabled = false`.
- 정리 부분은 `try/finally` 로 정리 보장.

기존 optimistic update(체크 상태와 라벨이 응답 전 변경) 동작은 유지한다.

### 4.2 서버 직렬화 (`app/routers/admin/criteria.py`)

`alias_map` 변형 경로 전체를 보호하는 모듈 전역 `asyncio.Lock`을 도입한다.

```python
_alias_map_mutation_lock = asyncio.Lock()
```

다음 mutation 경로의 본문을 `async with _alias_map_mutation_lock:` 으로 감싼다.

- `_set_status_by_stable_id` (activate / deactivate) — **본 이슈의 1차 대상**
- `upload_criteria`
- `delete_criteria_by_stable_id`
- `update_display_alias` (PATCH `/alias`)
- `replace_criteria_by_stable_id`
- `reconcile_criteria`

> 토글 외 경로는 이번 이슈의 직접 증상은 아니나, 동일한 alias_map 단일 문서를 변형하므로 같은 락을 공유하지 않으면 토글과 다른 mutation 간 충돌이 여전히 가능하다. surgical 원칙에 부합하는 최소 보호 범위로 본다.

락 대기는 무한이지만 락 내부의 `alias_svc.replace()`가 이미 60초 폴링 상한을 가지고 있어 대기 상한은 자연스럽게 형성된다(약 90초 이내). 추가 타임아웃은 도입하지 않는다.

`require_criteria_sync_ready` 의존성은 그대로 둔다. 락 도입 후 needs_resync로 떨어지는 확률 자체가 줄지만, 진짜로 마킹된 상태에서는 차단되어야 하므로 동작 변경 없음.

### 4.3 에러 처리

락 안에서 발생하는 예외는 기존 흐름을 보존한다.

- `_recover_status_mutation_from_cloud`(`criteria.py:150-207`)와 `_raise_criteria_mutation_failed`(`criteria.py:113-128`)는 변경하지 않는다.
- 클라이언트는 503을 받으면 기존처럼 alert와 라벨 롤백을 수행한다.

## 5. 테스트

### 5.1 서버 직렬화 — `tests/test_criteria_toggle_serialization.py` (신규)

- `asyncio.gather` 로 동일 stable_id에 대해 activate와 deactivate를 동시에 호출
  - 두 응답 모두 2xx
  - `alias_svc.replace` mock이 직렬로 호출됨을 timing 또는 in-progress 카운터로 검증
- 다른 stable_id에 대한 동시 호출도 둘 다 성공하며 직렬화됨을 검증
- 락 안에서 발생한 일시적 예외 후 `_recover_status_mutation_from_cloud` 흐름이 그대로 동작

### 5.2 클라이언트 — `tests/test_criteria_list_js.py` (기존 파일 확장)

- 한 번 클릭 직후
  - `cb.disabled === true`
  - 라벨에 `반영중` 문자열 포함
- 성공 응답 도착 후
  - `cb.disabled === false`
  - 라벨이 최종 텍스트(`활성` 또는 `비활성`)로 복귀
- 실패 응답(503/500) 도착 후
  - `cb.disabled === false`
  - 라벨이 이전 텍스트로 롤백
  - 체크 상태가 이전 상태로 롤백 (PR #75 동작 보존)

## 6. 마이그레이션 / 운영 영향

- 단일 프로세스 uvicorn 배포 그대로 사용. 동작/배포 절차 변경 없음.
- DB 스키마 변경 없음.
- 락 대기 중인 요청은 클라이언트에서 단순히 응답 지연으로 보임. 락의 효과로 503/needs_resync 발생 빈도는 감소.

## 7. 범위 외 (YAGNI)

- 멀티 프로세스/멀티 워커 환경의 DB advisory lock 또는 Redis lock
- 클라이언트 자동 재시도 및 백오프
- alias_map mutation 큐잉/배치 모델
- 토글 외 별도 진행 표시 스피너 컴포넌트

## 8. 관련 파일

- `app/routers/admin/criteria.py`
- `app/static/js/criteria_list.js`
- `app/templates/admin/criteria_list.html` (변경 없음 확인)
- `app/services/criteria_alias_map_service.py` (변경 없음, 참조용)
- `tests/test_criteria_list_js.py` (확장)
- `tests/test_criteria_toggle_serialization.py` (신규)
