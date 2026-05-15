# Cloud-Sourced Evaluation Criteria — Design

**Date:** 2026-05-15
**Status:** Draft for review
**Owner:** TBD
**Related work:** `2026-05-12-criteria-display-alias-design.md` (display_alias feature, DB-only)

## 1. Problem

평가기준 데이터는 현재 로컬 SQLite (`criteria` 테이블) + 로컬 디스크 (`data/uploads/criteria/`) + Gemini File Search (`rubric-store`)에 흩어져 있다. 클라우드 인덱스는 사실상 API key에 종속되지만 로컬 상태는 API key와 독립적으로 유지된다. 결과적으로:

- 운영자가 `.env`의 `GOOGLE_API_KEY`를 변경한 뒤 앱을 재시작하면, 로컬 DB는 옛 key의 `document_id`를 가리키고 있어 새 key의 클라우드와 모순된다.
- 새 key의 클라우드에 이미 평가기준이 있더라도 로컬은 인식하지 못한다.
- `display_alias`는 로컬에만 존재하므로 key 교체 시 손실된다.

## 2. Goals

- 평가기준은 **클라우드를 진실의 원천**으로 한다. 로컬 SQLite와 디스크는 머티리얼라이즈드 뷰다.
- API key가 변경되면 로컬 평가기준을 폐기하고 새 key의 클라우드 상태로 재구성한다.
- 평가기준의 `title`과 `display_alias`를 클라우드에도 보존하여 key 교체 후에도 인간이 정한 이름을 잃지 않는다.
- 클라우드 동기화 실패 시 앱은 정상 부팅하되 평가기준 기능만 비활성화한다.

## 3. Non-Goals

- 다중 사용자(Multi-tenant) 격리. 시스템은 단일 관리자 모델을 유지한다.
- API key UI 입력. 변경 경로는 기존대로 `.env` 수정 + 앱 재시작이다.
- 평가기준 PDF의 클라우드 백업. Gemini File Search는 임베딩만 보관하므로 원본 PDF는 재업로드가 필요하며, 본 설계는 이를 수용한다(로컬 PDF는 캐시일 뿐 진실 아님).
- 주기적 폴링 기반 자동 reconcile. 트리거는 부팅/관리자 수동/CRUD 실패 후 재시도 3가지뿐.

## 4. Architecture Overview

### 4.1 클라우드 객체 (Gemini File Search)

| Store | 역할 | 변경 |
| --- | --- | --- |
| `rubric-store` (기존, 이름은 `FS_RUBRIC_STORE_NAME`) | 평가기준 문서 콘텐츠. 검색/RAG에 사용. | 없음 |
| `rubric-metadata-store` (신규, `FS_RUBRIC_METADATA_STORE_NAME`) | 매니페스트 단일 JSON 문서. 검색에 사용하지 않음. | 신규 |

### 4.2 로컬 상태

| Storage | 역할 | 변경 |
| --- | --- | --- |
| SQLite `criteria` | 평가기준 행. 매니페스트의 머티리얼라이즈드 뷰. | 컬럼 변경 없음 |
| SQLite `app_state` (신규) | sync 상태 key-value. | 신규 |
| `data/uploads/criteria/<basename>.pdf` | PDF 업로드 캐시. | key 변경 시 전원 삭제 |

### 4.3 컴포넌트

| 컴포넌트 | 위치 | 책임 |
| --- | --- | --- |
| `AppStateRepository` (신규) | `app/repositories/app_state_repository.py` | `app_state` 테이블 read/write. |
| `CriteriaManifestService` (신규) | `app/services/criteria_manifest_service.py` | 매니페스트 build / fetch / publish. |
| `CriteriaReconciliationService` (신규) | `app/services/criteria_reconciliation_service.py` | 해시 비교, wipe, 매니페스트 기반 재구성. 동시 실행 lock 보유. |
| `require_criteria_sync_ready` (신규) | `app/dependencies.py` | FastAPI dependency. `sync_state != ok` 시 503. |
| `CriteriaService` (수정) | 기존 서비스/라우터 | 모든 mutation 직후 `manifest_svc.publish_from_db()` 호출. |
| `app/main.py` lifespan (수정) | startup hook | `asyncio.create_task(reconcile_on_startup())` 으로 비차단 실행. |
| Admin UI (수정) | `app/templates/admin/criteria.html` + JS | 동기화 배지, 재동기화 버튼, 비활성 표시. |
| QnA 인용 경로 (수정) | 기존 QnA 응답 코드 | `sync_state != ok` 시 평가기준 인용 비활성. |

## 5. Data Model

### 5.1 신규 테이블 `app_state`

```sql
CREATE TABLE IF NOT EXISTS app_state (
    key VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

부팅 시 마이그레이션은 기존 startup migration 패턴(예: `criteria.display_alias` 컬럼 추가와 동일한 위치)에 추가한다.

| key | value 형식 | 비고 |
| --- | --- | --- |
| `criteria_api_key_hash` | hex sha256, 길이 64 | 현재 활성 API key의 해시 |
| `criteria_last_synced_at` | ISO-8601 UTC | 마지막 정상 reconcile 시각 |
| `criteria_sync_state` | `ok` \| `needs_resync` \| `error` | UI 배지 / feature gate |
| `criteria_sync_error` | string (nullable) | 마지막 실패 메시지(관리자 노출용) |

### 5.2 `criteria` 테이블

컬럼 변경 없음. 모든 행은 reconcile 시 truncate/insert 되므로 `id`는 새로 생성된다. 외부에서 `criteria.id`로 참조하는 코드가 없는지 Wave 3 작업 시 확인하고, 있다면 `document_id` 기반 lookup으로 대체한다.

### 5.3 매니페스트 JSON 스키마

`rubric-metadata-store`에 단일 문서 `rubric-manifest.json` 으로 업로드.

```json
{
  "schema_version": 1,
  "generated_at": "2026-05-15T03:21:00Z",
  "criteria": [
    {
      "document_id": "files/abc123def",
      "title": "2024-1학기 수업평가기준.pdf",
      "display_alias": "1학기 평가기준",
      "status": "active",
      "created_at": "2026-05-12T08:15:00Z",
      "activated_at": "2026-05-12T08:20:00Z"
    }
  ]
}
```

필드 정의:

- `schema_version` (int, required). 현재 `1`. 미지원 버전이면 `sync_state=error`, wipe 하지 않음.
- `generated_at` (ISO-8601, required). 디버깅용.
- `criteria[]` (array, required, 빈 배열 허용).
  - `document_id` (string, required). Gemini File Search 문서 ID.
  - `title` (string, required). 원본 파일명 / 불변 명칭.
  - `display_alias` (string, nullable). 사용자 편집 이름.
  - `status` (string, required). `uploaded` | `active` | `archived`.
  - `created_at`, `activated_at` (ISO-8601, nullable).

Pydantic 모델 `Manifest` / `ManifestEntry` 로 build/parse 양쪽 모두 검증한다.

## 6. Reconciliation Flow

### 6.1 트리거

| 트리거 | 호출자 |
| --- | --- |
| 앱 부팅 | `app/main.py` lifespan에서 `asyncio.create_task(reconcile())` |
| 관리자 수동 재동기화 | `POST /api/admin/criteria/reconcile` 신규 엔드포인트 |
| CRUD 후 publish 실패 복구 | 관리자가 위 엔드포인트 호출 |

세 트리거 모두 동일한 `CriteriaReconciliationService.reconcile()` 에 진입한다.

### 6.2 reconcile() 의사코드

```python
async def reconcile() -> ReconcileResult:
    async with _reconcile_lock:
        current_hash = sha256_hex(settings.GOOGLE_API_KEY)
        stored_hash  = await app_state.get("criteria_api_key_hash")
        stored_state = await app_state.get("criteria_sync_state")

        key_changed = stored_hash != current_hash
        if not key_changed and stored_state == "ok":
            return ReconcileResult(skipped=True)

        try:
            manifest = await manifest_svc.fetch()
            cloud_doc_ids = await content_svc.list_ids()
        except CloudUnavailable as e:
            if key_changed:
                await _wipe_local_state()
                await app_state.set_many({
                    "criteria_api_key_hash": current_hash,
                    "criteria_sync_state": "error",
                    "criteria_sync_error": str(e),
                })
            else:
                await app_state.set("criteria_sync_state", "needs_resync")
                await app_state.set("criteria_sync_error", str(e))
            return ReconcileResult(error=str(e))

        merged = _merge(manifest, cloud_doc_ids)
        async with db.begin():
            await criteria_repo.truncate()
            await criteria_repo.bulk_insert(merged.criteria_rows)
        _wipe_upload_dir()

        if merged.manifest_dirty:
            await manifest_svc.upload(merged.repaired_manifest)

        await app_state.set_many({
            "criteria_api_key_hash": current_hash,
            "criteria_last_synced_at": now_iso(),
            "criteria_sync_state": "ok",
            "criteria_sync_error": None,
        })
        return ReconcileResult(ok=True, count=len(merged.criteria_rows))
```

### 6.3 교차 검증 (`_merge`)

1. `manifest_doc_ids = {c.document_id for c in manifest.criteria}`.
2. `cloud_doc_ids = set(...)` (콘텐츠 store list 결과).
3. `orphans_in_manifest = manifest_doc_ids - cloud_doc_ids`. 해당 항목은 skip + WARN 로그.
4. `orphans_in_cloud = cloud_doc_ids - manifest_doc_ids`. 자동으로 매니페스트 추가 항목으로 합성: `title=cloud_displayName`, `display_alias=null`, `status=uploaded`. `manifest_dirty=True` 로 표시하여 reconcile 끝에 매니페스트 재업로드.
5. 로컬 DB에는 `manifest_doc_ids ∪ orphans_in_cloud - orphans_in_manifest` 가 insert된다.

### 6.4 잠금

`_reconcile_lock = asyncio.Lock()` 모듈 싱글톤. 동일 워커 내 동시 호출 직렬화. 다중 워커는 idempotent 보장(같은 매니페스트 → 같은 결과).

### 6.5 부팅 비차단

lifespan 내부에서 `await`하지 않고 `asyncio.create_task` 로 예약. reconcile 완료 전 평가기준 mutation 라우터에는 `require_criteria_sync_ready` dependency가 부착되어 503으로 응답한다. QnA 응답 경로는 503을 반환하지 않고 내부에서 `sync_state != ok` 를 확인하여 평가기준 인용만 비활성화한다(섹션 7.3). 사용자 일반 페이지/대시보드는 영향 없다.

### 6.6 시간 예산

매니페스트 fetch + 콘텐츠 list + DB truncate/insert + (필요 시) 매니페스트 재업로드 합산 3–5초 가정. 부팅 비차단이므로 사용자 영향 없음. 관리자 버튼은 spinner + 결과 토스트.

## 7. CRUD Behavior

### 7.1 변경 패턴

각 mutation의 끝에 다음 한 줄을 추가한다:

```python
await criteria_manifest_service.publish_from_db()
```

`publish_from_db()` 시멘틱:

- SQLite의 `criteria` 테이블을 읽어 Pydantic `Manifest` 모델로 빌드하고 `rubric-metadata-store`에 single-doc replace 패턴으로 업로드.
- 실패 시 호출자에게 예외 전파 + `app_state.criteria_sync_state = needs_resync` + `criteria_sync_error` 기록. **로컬 DB 변경은 롤백하지 않는다.** 다음 reconcile에서 자가복구.
- 트랜잭션 아님. 단일 admin 모델을 가정하므로 race condition은 마지막 publish가 이긴다.

### 7.2 영향 받는 라우터

| 라우터 | 변경 |
| --- | --- |
| `POST /api/admin/criteria` (업로드) | `vector_service.upload_document()` 성공 → `criteria_repo.insert()` → `publish_from_db()`. |
| `POST /api/admin/criteria/{id}/activate` | `activate_criteria()` 후 `publish_from_db()`. |
| `PATCH /api/admin/criteria/{id}/display-alias` | `update_display_alias()` 후 `publish_from_db()`. |
| `DELETE /api/admin/criteria/{id}` | `_recreate_criteria_store()` → `criteria_repo.delete()` → `publish_from_db()`. |
| `GET /api/admin/criteria` | sync 메타(`sync_state`, `last_synced_at`, `criteria_sync_error`) 응답 포함. |
| `POST /api/admin/criteria/reconcile` (신규) | `reconcile()` 호출 → 결과 반환. |

위 mutation 라우터 모두 `Depends(require_criteria_sync_ready)` 부착. 읽기 엔드포인트(`GET /api/admin/criteria`, `GET /api/admin/criteria/sync-status`)는 게이트 통과 허용.

### 7.3 QnA 인용 경로

평가기준 인용을 사용하는 QnA 응답 코드는 `sync_state != ok` 일 때 인용 비활성, 응답 본문에 "평가기준 동기화가 필요합니다" 한 줄을 포함한다. 다른 QnA 동작은 변경 없음.

## 8. Admin UI

상단 동기화 배지:

```
[●] 동기화 완료 — 마지막 동기화 2026-05-15 03:21 UTC
[⚠] 동기화 필요 — [재동기화]
[✗] 클라우드 동기화 실패 — 평가기준 기능 비활성 — [재동기화]
   에러 메시지: "..."
```

- 데이터 소스: `GET /api/admin/criteria` 응답 또는 신규 `GET /api/admin/criteria/sync-status`.
- 페이지 로드 시 1회, mutation 직후 자동 새로고침.
- 자동 폴링 없음.

`sync_state == error` 시 업로드/활성화/alias 편집/삭제 버튼을 모두 disabled, "API key 변경이 감지되었으나 클라우드 동기화에 실패했습니다. 재동기화 후 사용 가능합니다." 안내.

기존 `cloud_sync_validator.validate_rubricstore_sync()` 는 보조 헬스체크로 유지하되 본 설계의 `sync_state` 와는 독립이다.

## 9. Error Handling

| 상황 | 처리 |
| --- | --- |
| `GOOGLE_API_KEY` 미설정 | reconcile skip, `sync_state=error`, 메시지 "API key not configured", 기능 비활성 |
| 매니페스트 store 미존재 | 빈 매니페스트로 가정 → orphans_in_cloud 경로로 자가복구 |
| 매니페스트 fetch 실패 (네트워크/5xx) | key 변경됨이면 (가): wipe + `sync_state=error`. 동일이면 `sync_state=needs_resync` |
| 매니페스트 JSON 파싱 실패 | `sync_state=error`, 메시지 "manifest invalid: <reason>", wipe **하지 않음** |
| `schema_version` 미지원 | `sync_state=error`, 메시지 "manifest schema vN unsupported", wipe 하지 않음 |
| 콘텐츠 store list 실패 | 매니페스트 fetch 실패와 동일 처리 |
| DB truncate/insert 실패 | 트랜잭션 롤백, `sync_state=error`, 다음 호출에서 재시도 |
| `publish_from_db()` 실패 (CRUD 후) | DB 변경 유지, `sync_state=needs_resync`, 5xx + 안내 메시지 |
| 업로드 디렉토리 wipe 실패 | `sync_state=error`, 메시지 "local cache wipe failed" |

보안 가드:

- `_wipe_upload_dir()`: `Path.resolve(strict=True) == settings.CRITERIA_UPLOAD_DIR.resolve()` 검증. symlink 거부.
- 해시 비교: sha256 hex, 길이 64 검증.
- 매니페스트 업로드 직전 Pydantic 자체 검증.
- `POST /api/admin/criteria/reconcile` 은 기존 admin auth 미들웨어 그대로 사용.

## 10. Observability

- 모든 reconcile 호출에 `request_id` 부여, 시작/종료/실패 INFO 로그.
- 로그 필드: `event`, `trigger`(`startup`|`admin`|`crud_followup`), `key_changed`, `criteria_count_before/after`, `duration_ms`, `error_class`.
- 매니페스트 publish 실패는 ERROR 로그 + `app_state.criteria_sync_error` 기록.
- 기존 `cloud_sync_validator` 로그 포맷 재사용.

## 11. Testing Strategy

기존 패턴(SQLite in-memory + mocked Gemini 클라이언트)을 따른다.

P1 신규 테스트 파일:

- `tests/services/test_criteria_reconciliation_service.py`
  - `test_reconcile_skips_when_hash_unchanged_and_state_ok`
  - `test_reconcile_wipes_and_repopulates_on_key_change`
  - `test_reconcile_on_cloud_unavailable_with_key_change_wipes_and_sets_error`
  - `test_reconcile_on_cloud_unavailable_without_key_change_marks_needs_resync`
  - `test_reconcile_self_heals_orphans_in_cloud`
  - `test_reconcile_skips_orphans_in_manifest_and_warns`
  - `test_reconcile_first_run_with_empty_manifest_store_succeeds`
  - `test_reconcile_unsupported_schema_version_sets_error_without_wipe`
  - `test_reconcile_lock_serializes_concurrent_calls`
- `tests/services/test_criteria_manifest_service.py`
  - `test_publish_from_db_uploads_manifest_replacing_existing`
  - `test_fetch_returns_empty_manifest_when_store_missing`
  - `test_manifest_schema_validation_rejects_invalid_status`
- `tests/routers/test_criteria_router_with_sync_gate.py`
  - `test_mutation_blocked_when_sync_state_not_ok`
  - `test_read_endpoints_include_sync_metadata`
  - `test_reconcile_endpoint_invokes_service_and_returns_state`
- `tests/test_criteria_crud_publishes_manifest.py`
  - `test_upload_triggers_manifest_publish`
  - `test_activate_triggers_manifest_publish`
  - `test_alias_patch_triggers_manifest_publish`
  - `test_delete_triggers_manifest_publish`
  - `test_publish_failure_marks_needs_resync_but_keeps_db_change`
- `tests/test_startup_reconcile.py`
  - `test_lifespan_schedules_reconcile_task`
  - `test_lifespan_does_not_block_when_reconcile_slow`

기존 QnA 테스트에 1건 추가:

- `test_qna_disables_criteria_citation_when_sync_state_not_ok`

## 12. Rollout

| Wave | 내용 | 검증 | 사용자 영향 |
| --- | --- | --- | --- |
| 1 | `app_state` 테이블 + 마이그레이션 + `AppStateRepository` | unit test, startup smoke | 없음 (dark) |
| 2 | `CriteriaManifestService` (build/publish/fetch) | unit test, mocked Gemini | 없음 (dark) |
| 3 | `CriteriaReconciliationService` + `require_criteria_sync_ready` dependency | reconcile test 매트릭스 | 없음 (dark) |
| 4 | CRUD 후처리 (`publish_from_db()`) + 라우터 dependency 부착 | 라우터 통합 테스트 | mutation 후 매니페스트 1회 업로드 |
| 5 | Startup hook + `POST /api/admin/criteria/reconcile` | startup 테스트, e2e admin reconcile | 부팅 시 reconcile 비차단 실행 |
| 6 | 관리자 UI 배지/버튼/비활성 + QnA 가드 | 수동 UI 확인 + 회귀 | 관리자 화면 변경 |
| 7 | 첫 배포 후 24h 운영 모니터링 | 로그, sync_state 통계 | — |

각 Wave는 독립적으로 머지 가능. Wave 1–3은 dark, 사용자 영향 0.

Rollback: Wave 5–6만 revert해도 시스템은 이전 상태로 복귀. 매니페스트 store는 그대로 두면 다음 시도 시 재사용된다.

기능 플래그: `settings.CRITERIA_CLOUD_RECONCILE_ENABLED` (기본 `True`). `False`로 두면 startup hook / dependency / CRUD 후처리 모두 no-op. 긴급 차단 수단.

## 13. Open Questions / Future Work

- 매니페스트가 매우 커진 경우(수백 건) 단일 JSON 문서 업로드 성능 영향 측정 — 현재 평가기준 수는 한 자릿수 가정.
- Gemini File Search store 생성/삭제 quota — 신규 store 1개 추가가 운영 한도에 영향이 있는지 확인.
- 향후 multi-tenant 지원 시 매니페스트 스키마에 `tenant_id` 필드 추가 여지를 남겨두기 위해 `schema_version` 도입 — 현 설계는 v1로 고정.
- 매니페스트의 `display_alias` 정규화(현재 Hangul + ASCII만 허용)는 기존 schema validation을 그대로 재사용.
