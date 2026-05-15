# 평가기준 — 클라우드 메타데이터 단일화 설계

- **작성일:** 2026-05-15
- **상태:** Draft — 사용자 검토 대기
- **소유:** TBD
- **관련 작업:**
  - `2026-05-12-criteria-display-alias-design.md` (display_alias DB 컬럼 도입, 머지됨)
  - `2026-05-15-cloud-evaluation-criteria-design.md` (manifest 기반 클라우드 SoT, PR #57로 머지됨 — 본 설계로 대체)
- **참조:** `research/file_search_api_doc.md` (Gemini File Search API 공식 문서)

## 1. 배경

PR #57(2026-05-15 머지)이 클라우드를 평가기준의 진실의 원천(Source of Truth)으로 도입했다. 이후 두 가지 사실이 드러났다:

1. **Gemini File Search API는 개별 문서 삭제를 지원한다.**
   `client.file_search_stores.documents.delete(name=...)` — 현재 `criteria_vector_service.py:100-120` 의 주석("개별 document 삭제 불가, Store 재생성으로 대체")은 잘못된 가정에 기반함.
2. **API는 문서별 custom_metadata를 지원한다.**
   업로드 시 `custom_metadata=[{"key", "string_value"|"numeric_value"}]` 형태로 첨부 가능. 검색에 `metadata_filter` 로 사용 가능. 단, **업로드 이후 수정 불가** (`patch`/`update` 엔드포인트 없음).

이 두 사실로 인해, PR #57에서 도입한 별도 `rubric-metadata-store` + manifest JSON 구조는 더 단순한 형태로 대체할 수 있다.

## 2. 목표

1. 평가기준의 클라우드-진실의 원천 모델을 유지하되, **인프라를 단순화**한다 (store 2개 → 1개).
2. **개별 삭제**가 `documents.delete(name)` 1콜로 가능하다 (Store 재생성 N-1 재업로드 비용 제거).
3. **alias 편집**이 PDF 재임베딩 없이 수초 내 완료된다 (alias_map 작은 텍스트 문서만 재업로드).
4. **API key 교체 시에도 alias가 보존**된다 (alias_map이 클라우드에 존재하므로).
5. 관리자 UI를 단일 표로 통합하여 "DB vs 클라우드" 이중성 인상을 제거한다.

## 3. 비목표 (Out of scope)

- 다중 사용자(Multi-tenant) 격리.
- API key UI 입력. 변경 경로는 `.env` 수정 + 재시작 유지.
- 100개+ 평가기준 운영 (현재 1-5개 운영 기준).
- 평가기준 PDF 원본의 클라우드 백업 (Gemini File Search는 임베딩만 보관).
- custom_metadata 사후 수정 (API 제약).
- 주기적 폴링 reconcile (트리거: 부팅 / 관리자 수동 / CRUD 직후 3가지).

## 4. 아키텍처 개요

### 4.1 클라우드 객체 (단일 `rubric-store`)

```
rubric-store (Gemini File Search Store, 유일한 진실의 원천)
├── 📄 평가기준 PDF 1개당 1문서
│   custom_metadata:
│     type = "criteria"
│     stable_id = "<ULID/UUID>"       ← API key 교체에도 살아남는 식별자
│     original_title_b64 = [...]      ← 한글 파일명 base64 청크
│     created_at = "<ISO-8601>"
│
└── 📄 alias-map.txt (1개, < 1KB)
    custom_metadata:
      type = "alias_map"
      payload_b64 = [...]              ← base64 청크
    payload 디코딩 = JSON:
      {
        schema_version: 1,
        updated_at: ISO-8601,
        entries: {
          "<stable_id>": {
            alias: string | null,
            status: "active" | "uploaded" | "archived",
            activated_at: ISO-8601 | null
          },
          ...
        }
      }
```

**제거 객체**:
- `rubric-metadata-store` (PR #57에서 도입한 별도 store).

### 4.2 로컬 상태

| Storage | 역할 | 변경 |
|---|---|---|
| SQLite `criteria` | 캐시. reconcile 시 truncate/insert. | `stable_id` 컬럼 추가. `synced_at`은 단계적 제거 (1차: 사용처 제거, 2차: 2주 후 컬럼 DROP — §11) |
| SQLite `app_state` | sync 상태 key-value. | 변경 없음 (PR #57 그대로) |
| `data/uploads/criteria/` | PDF 업로드 캐시. | 역할 약화: 선택적. 부재해도 시스템 동작. key 변경 시 wipe. |

### 4.3 컴포넌트 변경

| 컴포넌트 | 위치 | 변경 |
|---|---|---|
| `CriteriaAliasMapService` (신규) | `app/services/criteria_alias_map_service.py` | alias-map.txt fetch/parse/update/upload. base64 청크 인/디코딩. |
| `CriteriaVectorService` (수정) | `app/services/criteria_vector_service.py` | `delete_criteria` → `documents.delete(name)`. `_recreate_criteria_store` 제거. `upload_criteria` → custom_metadata에 stable_id 등 포함. `list_criteria_documents` → type 필터링. |
| `CriteriaReconciliationService` (수정) | `app/services/criteria_reconciliation_service.py` | manifest → alias_map 전환. 마이그레이션 분기 추가. |
| `CriteriaManifestService` | `app/services/criteria_manifest_service.py` | **제거** |
| `CriteriaRepository` (수정) | `app/repositories/criteria_repository.py` | `stable_id` 컬럼 lookup 메서드 추가, `synced_at` 의존 제거 |
| `Criteria` 모델 (수정) | `app/models/criteria.py` | `stable_id` 컬럼 추가. `synced_at`은 단계적 제거 (사용처만 1차 제거) |
| Admin 라우터 (수정) | `app/routers/admin/criteria.py`, `criteria_views.py` | 단일 표 뷰. `PATCH /alias`, `POST /activate` 엔드포인트. |
| Admin 템플릿 (수정) | `app/templates/admin/criteria_list.html` | 단일 표, inline alias 편집, 활성 토글. dual-table 코드 제거. |
| `app/config.py` | `FS_RUBRIC_METADATA_STORE_NAME` **제거** | |
| `app/main.py` lifespan | 변경 없음 (reconcile 호출 시그니처 동일) | |

## 5. 데이터 모델

### 5.1 클라우드: 평가기준 PDF 문서 custom_metadata

| key | type | 값 | 비고 |
|---|---|---|---|
| `type` | string | `"criteria"` | alias_map 문서와 구분 |
| `stable_id` | string | ULID 26-char ASCII | API key 교체에도 살아남는 식별자. alias_map의 매핑 키. |
| `original_title_b64` | string_list | base64 청크 (chunk size 3000) | 한글 파일명 손실 방지. 디코딩 후 UTF-8 문자열. |
| `created_at` | string | ISO-8601 UTC | |

**chunk size 3000** 은 `file_search_service.py` 의 `_MANIFEST_PAYLOAD_CHUNK_SIZE` 와 통일.

### 5.2 클라우드: alias-map.txt 문서

- `display_name` = `"alias-map"` (ASCII-safe)
- 파일 내용: 의미 없는 placeholder 텍스트 1KB 미만 (API 요구사항 충족용 — 실제 데이터는 custom_metadata에)
- `custom_metadata`:
  - `type = "alias_map"`
  - `payload_b64 = string_list` (base64-encoded JSON 청크)

**payload 디코딩 결과 (JSON schema)**:

```json
{
  "schema_version": 1,
  "updated_at": "2026-05-15T03:21:00Z",
  "entries": {
    "01HXYZ...": {
      "alias": "1학기 평가기준",
      "status": "active",
      "activated_at": "2026-05-15T03:21:00Z"
    },
    "01HXYZ2...": {
      "alias": null,
      "status": "uploaded",
      "activated_at": null
    }
  }
}
```

필드 정의:
- `schema_version` (int, required). 현재 `1`. 미지원 버전 → `sync_state=error`, wipe 금지.
- `updated_at` (ISO-8601, required). 디버깅용.
- `entries` (object, required, 빈 객체 허용). key = stable_id, value = entry.
- entry:
  - `alias` (string|null). 관리자 편집 가능. 한글 OK (base64 보존).
  - `status` (string, required). `active` | `uploaded` | `archived`.
  - `activated_at` (ISO-8601|null). status==`active`로 전환된 시각.

Pydantic 모델 `AliasMap` / `AliasMapEntry` 로 build/parse 양쪽 검증.

### 5.3 로컬 SQLite `criteria` 테이블

```sql
ALTER TABLE criteria ADD COLUMN stable_id VARCHAR(64) NULL;
-- synced_at, cloud_synced 등은 사용처 제거 후 다음 마이그레이션에서 DROP
```

| 컬럼 | 출처 | 비고 |
|---|---|---|
| `id` | reconcile 시 자동 생성 | 외부 참조 금지 (stable_id를 쓸 것) |
| `stable_id` | document custom_metadata | 신규. NOT NULL이 목표지만 단계적 도입 |
| `document_id` | Gemini 문서 이름 | |
| `title` | document custom_metadata `original_title_b64` 디코딩 | 변경 불가 |
| `display_alias` | alias_map `entries[stable_id].alias` | NULL 가능, fallback to title |
| `status` | alias_map `entries[stable_id].status` | |
| `created_at` | document custom_metadata `created_at` | |
| `activated_at` | alias_map `entries[stable_id].activated_at` | NULL 가능 |
| `file_size` | 로컬 PDF 캐시 (있을 때만) | 참고용. 없으면 NULL/0. |
| `synced_at` | **제거 대상** | reconcile 후 일관성 보장으로 불필요 |

### 5.4 `app_state` 테이블

PR #57 그대로 유지. 키 정의 변경 없음.

| key | 비고 |
|---|---|
| `criteria_api_key_hash` | sha256(GOOGLE_API_KEY) |
| `criteria_last_synced_at` | 마지막 정상 reconcile 시각 |
| `criteria_sync_state` | `ok` \| `needs_resync` \| `error` |
| `criteria_sync_error` | 마지막 실패 메시지 |

## 6. CRUD 흐름

### 6.1 추가 (Add)

```
관리자가 PDF 업로드
  ↓
1. 서버: stable_id 생성 (ULID)
2. CriteriaVectorService.upload_criteria(file_path, title)
   → upload_to_file_search_store(
        file_search_store_name=<rubric-store>,
        file=file_path,
        config={
          'display_name': sanitized_title,
          'chunking_config': {...},
          'custom_metadata': [
            {key:"type", string_value:"criteria"},
            {key:"stable_id", string_value:<ulid>},
            {key:"original_title_b64", string_list_value:{values:[chunks]}},
            {key:"created_at", string_value:<iso>}
          ]
        }
      )
   → document_id 획득
3. CriteriaAliasMapService.update_entry(stable_id, {alias:null, status:"uploaded", activated_at:null})
   (내부 순서: 기존 alias-map 문서 fetch → entries 추가 → **새 문서 upload 성공 후 → 기존 문서 delete**.
    Upload-Then-Delete 순서로 부분 손실 방지. 자세한 내용은 §10.5)
4. CriteriaRepository.insert(stable_id, document_id, title, ...)
5. app_state.last_synced_at 업데이트
```

**실패 처리**: 2번 실패 → 0 영향. 3-5번 중 실패 → app_state.sync_state=needs_resync. reconcile로 복구.

### 6.2 삭제 (Delete)

```
관리자가 삭제 클릭 + 확인
  ↓
1. CriteriaVectorService.delete_criteria(document_id)
   → client.file_search_stores.documents.delete(name=document_id)
2. CriteriaAliasMapService.remove_entry(stable_id)
3. CriteriaRepository.delete_by_stable_id(stable_id)
4. app_state.last_synced_at 업데이트
```

**비용**: PDF 재임베딩 0회. API 호출 3-4회. 수초 내.

### 6.3 alias 편집 (Inline UI)

```
관리자가 셀 클릭 → 텍스트 입력 → Enter
  ↓
PATCH /api/admin/criteria/{stable_id}/alias
body: {alias: "1학기 평가기준" | null}
  ↓
1. CriteriaAliasMapService.update_entry(stable_id, {alias: new_value})
   (fetch → modify → upload new → delete old. §10.5 참조)
2. CriteriaRepository.update_alias(stable_id, new_value)
3. 응답: 갱신된 entry
```

**비용**: PDF 재임베딩 0회. alias-map.txt 재업로드 1회 (< 1KB). 1-2초.

### 6.4 활성/비활성 토글

```
관리자가 라디오 클릭 → 확인 모달
  ↓
POST /api/admin/criteria/{stable_id}/activate
  ↓
async with _reconcile_lock:
  1. alias_map fetch
  2. entries 순회: 기존 active를 모두 "uploaded"로 강등
  3. entries[stable_id] = {..., status:"active", activated_at:now}
  4. alias_map 재업로드
  5. DB UPDATE (대상 행 + 기존 active 행)
```

**제약**: 한 번에 1개만 active. 서버에서 강제.

### 6.5 Reconcile

```python
async def reconcile() -> ReconcileResult:
    async with _reconcile_lock:
        current_hash = sha256_hex(settings.GOOGLE_API_KEY)
        stored_hash = await app_state.get("criteria_api_key_hash")
        stored_state = await app_state.get("criteria_sync_state")

        key_changed = stored_hash != current_hash
        if not key_changed and stored_state == "ok":
            return ReconcileResult(skipped=True)

        try:
            # 마이그레이션 분기 (1회): rubric-metadata-store 존재 시 처리
            await _migrate_from_legacy_manifest_if_needed()

            # 1. 모든 rubric-store 문서 fetch
            all_docs = await criteria_vec_svc.list_all_documents()
            criteria_docs = [d for d in all_docs if _meta(d, "type") == "criteria"]
            alias_map_doc = next(
                (d for d in all_docs if _meta(d, "type") == "alias_map"),
                None
            )

            # 2. alias_map 파싱 (없으면 빈 dict)
            alias_map = await alias_map_svc.parse(alias_map_doc) if alias_map_doc else {}

            # 3. stable_id 없는 criteria_docs는 WARN + 건너뜀
            #    (단, 마이그레이션 직후엔 자동 백필 시도)
            valid_docs = [d for d in criteria_docs if _meta(d, "stable_id")]

            # 4. 교차 검증 + 합성을 1단계로 처리 (alias_map 재업로드 최대 1회)
            valid_stable_ids = {_meta(d, "stable_id") for d in valid_docs}
            cleaned_entries = {
                sid: e for sid, e in alias_map.items()
                if sid in valid_stable_ids   # 4a. 클라우드에 없는 entry 제거
            }
            for d in valid_docs:             # 4b. entry 없는 클라우드 문서 합성
                sid = _meta(d, "stable_id")
                if sid not in cleaned_entries:
                    cleaned_entries[sid] = AliasMapEntry(
                        alias=None, status="uploaded", activated_at=None
                    )

            # 5. 변경이 있을 때만 단일 재업로드 (self-heal)
            if cleaned_entries != alias_map:
                await alias_map_svc.replace(cleaned_entries)

            # 6. 로컬 DB 트랜잭션 재구성
            async with db.begin():
                await criteria_repo.truncate()
                for d in valid_docs:
                    sid = _meta(d, "stable_id")
                    entry = cleaned_entries[sid]
                    await criteria_repo.insert(
                        stable_id=sid,
                        document_id=d.name,
                        title=_decode_b64(_meta(d, "original_title_b64")),
                        display_alias=entry.alias,
                        status=entry.status,
                        created_at=_parse_iso(_meta(d, "created_at")),
                        activated_at=entry.activated_at,
                    )

            # 7. key 변경 시 PDF 캐시 wipe
            if key_changed:
                _wipe_upload_dir()

            # 8. app_state 업데이트
            await app_state.set_many({
                "criteria_api_key_hash": current_hash,
                "criteria_last_synced_at": now_iso(),
                "criteria_sync_state": "ok",
                "criteria_sync_error": None,
            })
            return ReconcileResult(ok=True, count=len(valid_docs))

        except Exception as e:
            await app_state.set_many({
                "criteria_sync_state": "needs_resync" if not key_changed else "error",
                "criteria_sync_error": str(e),
            })
            if key_changed:
                # key 변경인데 클라우드 접근 실패 → 로컬 wipe로 일관성 강제
                await _wipe_local_state()
            return ReconcileResult(error=str(e))
```

### 6.6 마이그레이션 (`_migrate_from_legacy_manifest_if_needed`)

reconcile 시작 시 1회 검사:

```
1. rubric-metadata-store 검색
2. 존재 시:
   a. manifest.json fetch (실패 시 빈 manifest로 진행)
   b. manifest의 {document_id: display_alias} 매핑 추출
   c. rubric-store 문서 순회:
      - documents.get(name)으로 현재 custom_metadata 확인
      - stable_id 있으면: 그대로 사용
      - stable_id 없으면 (PR #57 시점 업로드된 문서):
        * 로컬 PDF 캐시(data/uploads/criteria/)가 있으면:
          - 새 stable_id 발급 → upload_criteria 재업로드 → 기존 documents.delete
        * 로컬 PDF 캐시가 없으면:
          - **document_id를 stable_id 대리값으로 사용 (surrogate)**
          - 새 alias_map entry는 surrogate 키로 기록
          - WARN 로그: "Document {name} migrated without proper stable_id; will use surrogate"
   d. 추출한 alias 매핑(stable_id 또는 surrogate 기준)을 새 alias_map 문서로 업로드
3. rubric-metadata-store 통째로 delete (force=True)
4. 마이그레이션 완료 마커: app_state["criteria_migration_v2_done"] = "true"
   이후 reconcile은 이 단계 건너뜀.
```

**비용**: criteria 개수만큼의 PDF 재임베딩 (1-5개, 로컬 PDF 있을 때만). 1회성. 부팅 비차단.

**Surrogate 절충**: PR #57 시점 업로드된 문서가 로컬 PDF 부재 상태이면 stable_id 백필 불가. 해당 문서는 `document_id` 자체를 stable_id 자리에 채워 운영을 계속한다. 단점: 이후 어떤 이유로 그 문서를 삭제 후 같은 PDF를 재업로드하면 새 stable_id가 발급되어 (이론적으로는) 별개로 취급된다. 운영 영향은 낮음 — 평가기준은 자주 갱신되지 않음.

**실패 처리**: 마이그레이션 도중 실패 시 sync_state=error. 관리자는 재동기화 버튼으로 재시도 가능. 멱등성 확보: 각 단계는 상태 확인 후 진행 (rubric-metadata-store가 이미 없으면 1·2·3 단계 건너뜀, alias_map이 이미 존재하면 덮어쓰기).

## 7. UI 디자인

### 7.1 관리자 평가기준 목록 페이지

**Before** (PR #57 머지 상태):
- 위: DB 평가기준 표 (6개 컬럼: 제목/상태/크기/생성일/클라우드/작업)
- 아래: 클라우드 Store 문서 표 (3개 컬럼: 제목/표시이름/문서ID)
- 우상단: [동기화 확정] + [+ 새 기준 업로드]
- 동기화 상태 배너 (`needs_sync`, `cloud_sync_warning`)

**After**:
- 단일 표:

```
┌────────────────────────────────────────────────────────────────────────┐
│ ● 동기화 완료    마지막 동기화 2026-05-15 14:32       [⟳ 재동기화]    │
├────────────────────────────────────────────────────────────────────────┤
│ 평가 기준 관리                                       [+ 새 기준 업로드] │
├────────────────────────────────────────────────────────────────────────┤
│ 표시 이름             │ 원본 파일명         │ 상태   │ 생성일      │작업 │
├────────────────────────────────────────────────────────────────────────┤
│ [1학기 평가기준    ]✎ │ 초등6_정보.pdf      │●활성  │ 05-12 08:15 │삭제 │
│ [               ]✎  │ 2_curicurum.pdf     │○비활성│ 05-13 10:02 │삭제 │
│ [2학기 평가기준    ]✎ │ 2학기_초등.pdf      │○비활성│ 05-14 09:30 │삭제 │
└────────────────────────────────────────────────────────────────────────┘
```

**제거 요소**:
- 하단 클라우드 문서 표 (단일 SoT라 중복)
- "동기화 확정" 버튼 (즉시 클라우드 반영이므로 불필요)
- "needs_sync" 배너 (개념 자체가 사라짐)
- "cloud_sync_warning" 배너 (sync_state 배지로 충분)
- "클라우드 누락" 컬럼/표시

**신규 요소**:
- 표시 이름 inline 편집 (✎ 클릭 → input → Enter 저장)
- 상태 라디오 (활성 1개 제약)

### 7.2 신규/변경 API

| 메서드 | 경로 | 동작 |
|---|---|---|
| `PATCH` | `/api/admin/criteria/{stable_id}/alias` | alias 편집. body: `{alias: string \| null}` |
| `POST` | `/api/admin/criteria/{stable_id}/activate` | 활성화 (다른 active 자동 비활성) |
| `POST` | `/api/admin/criteria/{stable_id}/deactivate` | 비활성화 (`uploaded` 로 강등) |
| `DELETE` | `/api/admin/criteria/{stable_id}` | 삭제 |
| `POST` | `/api/admin/criteria/upload` | 추가 (기존, 시그니처 변경) |
| `POST` | `/api/admin/criteria/reconcile` | 수동 재동기화 (PR #57 유지) |

기존 `id` 기반 경로(`/api/admin/criteria/{id}`) → `stable_id` 기반으로 마이그레이션. 호출 측 모두 stable_id를 알 수 있음 (DB에서 같이 반환).

### 7.3 사용자 측 변경 (최소)

- `templates/user/dashboard.html` 의 "활성 평가 기준" 박스: 변경 없음. `display_alias` fallback to `title` 처리는 기존 그대로.
- QnA 인용 표시: 변경 없음 (DB lookup by document_id).
- `sync_state != ok` 시 QnA 평가기준 인용 비활성: PR #57 동작 유지.

## 8. 보안 / 접근 제어

- 모든 신규 엔드포인트는 `Depends(get_current_admin)` + `require_criteria_sync_ready` dependency 부착.
- `sync_state != ok` 시 mutation 엔드포인트는 503 반환 (PR #57과 동일).
- alias 입력은 길이 제한(255자), 한글 허용.

## 9. 테스트 전략

| 레이어 | 항목 |
|---|---|
| 단위 | `CriteriaAliasMapService` — base64 청크 인/디코딩, schema validation, self-heal |
| 단위 | `CriteriaVectorService.delete_criteria` — `documents.delete(name)` 호출 확인 (mock) |
| 단위 | `CriteriaVectorService.upload_criteria` — custom_metadata 형식 확인 |
| 단위 | reconcile — stable_id 매칭, orphans 합성, alias_map self-heal |
| 단위 | reconcile — key_changed 시 wipe 동작 |
| 통합 | 추가→삭제→reconcile 일관성 (mock SDK) |
| 통합 | alias 편집 후 재시작 → DB 캐시 재구성 → alias 보존 확인 |
| 통합 | API key 변경 시뮬 → DB wipe → reconcile → alias 보존 확인 |
| 통합 | 마이그레이션: 기존 rubric-metadata-store + manifest.json 존재 상태 → alias_map 생성 + metadata-store 삭제 |
| 통합 | 활성 라디오 제약 — 다른 활성 자동 강등 확인 |
| 회귀 | QnA 평가기준 인용 (PR #57 sync gate 동작 유지) |
| 수동 | 한글 alias 편집 → 재시작 → 보존 확인 |
| 수동 | 실제 SDK에서 `documents.delete(name)` 동작 검증 |

**1순위 작업**: 본격 구현 전, 별도 검증 스크립트로 다음 4가지를 실제 SDK 호출로 확인:
1. `client.file_search_stores.documents.delete(name=...)` 가 동작하는가
2. `upload_to_file_search_store` 의 `custom_metadata` 가 `documents.list()` 응답에 보존되는가
3. `string_list_value` chunked metadata가 한글 복원 가능한가
4. `documents.list()` 응답이 `custom_metadata` 를 포함하는가 (아니면 `documents.get()` 으로 개별 fetch 필요)

## 10. 위험 / 미해결

1. **SDK 호환성**: 위 1순위 작업의 결과에 따라 일부 흐름 조정 필요할 수 있음.
2. **마이그레이션 일회 비용**: PR #57 운영 환경에서 평가기준 N개 재업로드 = 재임베딩 비용. 무료 티어 한도 사전 점검.
3. **alias_map 크기 한계**: custom_metadata `string_list_value` 의 총 크기 한계 미문서화. 100개 항목 초과 운영 시 별도 분할 전략 필요. 현재 1-5개 운영 기준에서는 안전.
4. **외부 동시 변경**: 별도 콘솔에서 클라우드 문서가 추가/삭제되는 경우 → 본 시스템은 모름. reconcile 시 자동 합성/정리되지만, 그 사이는 inconsistent. 단일 관리자 모델이므로 실무상 무시 가능.
5. **재업로드 중 부분 손실**: alias_map 재업로드는 "delete old → upload new" 순서. 사이에 장애가 나면 alias_map 부재 상태. 이 경우 reconcile이 빈 entries로 합성 → alias 일시 손실. 완화: 새 문서 upload 성공 후에야 old를 delete (eventually consistent).

## 11. 마이그레이션 체크리스트 (배포 시)

1. DB 마이그레이션: `criteria.stable_id` 컬럼 추가 (NULL 허용)
2. 새 코드 배포
3. 부팅 시 reconcile 자동 실행:
   - 기존 `rubric-metadata-store` 감지 → `_migrate_from_legacy_manifest_if_needed` 진입
   - 평가기준 PDF 재업로드 (custom_metadata 부여)
   - alias_map 신규 생성 (기존 manifest 데이터 보존)
   - `rubric-metadata-store` 삭제
   - 마이그레이션 마커 기록
4. 관리자가 sync 배지에서 `ok` 확인
5. 2주 운영 후 다음 마이그레이션: `criteria.synced_at` 등 미사용 컬럼 DROP (`cloud_synced`는 컬럼이 아닌 view 측 계산값이므로 §12에서 코드 제거로 처리)
6. `FS_RUBRIC_METADATA_STORE_NAME` 환경 변수 / 코드 참조 모두 제거 확인

## 12. 코드 제거 목록

- `app/services/criteria_manifest_service.py` (전체 파일)
- `app/schemas/manifest.py` 또는 `Manifest`/`ManifestEntry` 정의 위치
- `app/config.py` 의 `FS_RUBRIC_METADATA_STORE_NAME`
- `app/services/criteria_vector_service.py` 의 `_recreate_criteria_store` 메서드
- `app/templates/admin/criteria_list.html` 의 dual-table 코드, "동기화 확정" 버튼, `cloud_sync_warning`/`needs_sync` 배너
- `app/routers/admin/criteria_views.py` 의 `cloud_documents` enrichment, `pending_sync_criteria` 계산
- `app/services/cloud_sync_validator.py` 의 `validate_rubricstore_sync` (또는 새 의미로 재정의)
- `Criteria.synced_at` (단계적 — 1차 배포에서는 컬럼 유지, 사용 코드만 제거)
- 위 관련 테스트
