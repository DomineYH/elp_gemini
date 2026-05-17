# Issue #68 — Criteria Delete `Cannot delete non-empty Document` 수정 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 평가기준 삭제 시 Gemini File Search API가 chunk를 포함한 Document 삭제를 거부(`400 FAILED_PRECONDITION`)하는 문제를, `documents.delete(name=..., config={"force": True})` 로 수정한다.

**Architecture:** Gemini SDK의 `DeleteDocumentConfig.force` 옵션을 핵심 삭제 경로(`CriteriaVectorService.delete_criteria`)에 추가하고, 동일한 호출 패턴을 사용하는 `CriteriaAliasMapService` 의 두 곳(`replace`의 old 문서 삭제, `fetch`의 stale 정리)에도 방어적으로 적용한다. 단위 테스트로 `force=True` 전달을 회귀 가드한다.

**Tech Stack:** Python 3.11, FastAPI, google-genai SDK (>=1.x, `DeleteDocumentConfig` 보유 확인), pytest + pytest-asyncio.

---

## 사전 컨텍스트 (구현 전 반드시 확인)

- 에러 원문: `ClientError - 400 FAILED_PRECONDITION. {'error': {'code': 400, 'message': 'Cannot delete non-empty Document', 'status': 'FAILED_PRECONDITION'}}`
- 영향 엔드포인트: `DELETE /api/admin/criteria/{stable_id}` (`app/routers/admin/criteria.py:303-367`), `POST /api/admin/criteria/{stable_id}/replace` 의 step 3 (`app/routers/admin/criteria.py:466`)
- SDK 확인: `genai.types.DeleteDocumentConfig.model_fields` = `['http_options', 'force']` — `force=True` 지원됨.
- 기존 동일 패턴: `app/services/file_search_service.py:518-521` 가 store 삭제에서 `config={'force': True}` 사용.
- 삭제 대상 문서 ID 예: `fileSearchStores/rubricstore-khud6zyi66o4/documents/pdf-g82l6gidxj6t` (현재 운영 DB의 legacy 행).
- 작업 디렉토리: 저장소 루트 `/home/dominemint/Dev/elp_gemini`.
- 테스트 러너: `.venv/bin/pytest` (uv venv 사용, 시스템 `python` 없음).

---

## Task 1: `CriteriaVectorService.delete_criteria` 에 `force=True` 추가 (핵심 수정)

**Files:**
- Modify: `app/services/criteria_vector_service.py:80-88`
- Test: `tests/test_criteria_vector_service_delete_individual.py` (수정)

- [ ] **Step 1: 기존 회귀 테스트 강화 (failing test 만들기)**

`tests/test_criteria_vector_service_delete_individual.py` 의 `test_delete_criteria_calls_documents_delete_by_name` 를 다음으로 교체. `force=True` 가 SDK 호출에 전달되었음을 검증한다.

```python
"""delete_criteria가 documents.delete(name=..., config={"force": True})를 호출"""
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_delete_criteria_calls_documents_delete_with_force():
    """chunks를 가진 Document 삭제를 위해 force=True 가 전달되어야 한다."""
    from app.services.criteria_vector_service import CriteriaVectorService

    svc = CriteriaVectorService()
    svc.file_search_service = MagicMock()
    svc.file_search_service.client = MagicMock()
    delete_mock = MagicMock()
    svc.file_search_service.client.file_search_stores.documents.delete = delete_mock

    ok = await svc.delete_criteria(document_id="fileSearchStores/x/documents/foo")

    assert ok is True
    delete_mock.assert_called_once_with(
        name="fileSearchStores/x/documents/foo",
        config={"force": True},
    )


@pytest.mark.asyncio
async def test_delete_criteria_does_not_recreate_store():
    from app.services.criteria_vector_service import CriteriaVectorService

    svc = CriteriaVectorService()
    svc.file_search_service = MagicMock()
    svc.file_search_service.client = MagicMock()

    await svc.delete_criteria(document_id="fileSearchStores/x/documents/foo")

    svc.file_search_service.client.file_search_stores.create.assert_not_called()
    svc.file_search_service.client.file_search_stores.delete.assert_not_called()
```

- [ ] **Step 2: 테스트 실행해 실패하는 것 확인**

Run:
```
.venv/bin/pytest tests/test_criteria_vector_service_delete_individual.py -v
```
Expected: `test_delete_criteria_calls_documents_delete_with_force` FAIL — assertion error: 실제 호출은 `config` 없이 `name=...` 만 전달됨.

- [ ] **Step 3: `delete_criteria` 에 `config={"force": True}` 추가**

`app/services/criteria_vector_service.py:80-88` 를 다음으로 교체. body 외 변경 없음.

```python
    async def delete_criteria(self, document_id: str) -> bool:
        """document_id로 식별되는 평가기준 1개를 삭제. store 재생성 없음.

        Gemini File Search Document는 chunk를 포함한 상태에서 삭제하려면
        ``force=True`` 가 필요하다. 미전달 시 ``400 FAILED_PRECONDITION
        Cannot delete non-empty Document`` 가 발생한다 (issue #68).
        """
        if not document_id:
            raise ValueError("document_id가 비어있습니다")
        self.file_search_service.client.file_search_stores.documents.delete(
            name=document_id,
            config={"force": True},
        )
        logger.info(f"평가기준 삭제 완료: {document_id}")
        return True
```

- [ ] **Step 4: 테스트가 통과하는지 확인**

Run:
```
.venv/bin/pytest tests/test_criteria_vector_service_delete_individual.py -v
```
Expected: PASS (2 passed).

- [ ] **Step 5: 회귀 영향 범위 확인 — 같은 서비스 다른 호출자 영향 없음**

Run:
```
.venv/bin/pytest tests/ -k "criteria_vector_service or criteria_lifecycle or criteria_meta or criteria_reconcile" -q
```
Expected: 기존 통과 테스트가 그대로 PASS. 새 실패 없음.

- [ ] **Step 6: 커밋**

```bash
git add app/services/criteria_vector_service.py tests/test_criteria_vector_service_delete_individual.py
git commit -m "fix(criteria-meta): pass force=True to documents.delete (issue #68)

Gemini File Search rejects deletion of Document resources that still
contain chunks with 400 FAILED_PRECONDITION ('Cannot delete non-empty
Document'). Pass DeleteDocumentConfig.force=True so the Document and
its chunks are deleted in one call.

Closes #68 (criteria deletion)."
```

---

## Task 2: `CriteriaAliasMapService` 의 두 `documents.delete` 호출에 방어적 `force=True` 적용

**Why:** alias-map placeholder 문서는 현재 chunk가 거의 없어 우연히 동작 중. SDK/포맷 변경 시 동일 회귀가 reproducible 하므로 방어적 fix 를 함께 적용한다. 동작 변경은 없고 옵션만 추가.

**Files:**
- Modify: `app/services/criteria_alias_map_service.py:184` (fetch 의 stale cleanup)
- Modify: `app/services/criteria_alias_map_service.py:242` (replace 의 old doc 삭제)
- Test: `tests/test_criteria_alias_map_service_replace.py` (수정)
- Test: `tests/test_criteria_alias_map_service_fetch.py` (수정)

- [ ] **Step 1: replace 회귀 테스트 강화 (failing test)**

`tests/test_criteria_alias_map_service_replace.py` 의 `test_replace_uploads_then_deletes_old` 의 마지막 assert 만 교체:

```python
    # 기존:
    # client.file_search_stores.documents.delete.assert_called_once_with(name="docs/alias-map-old")

    # 신규:
    client.file_search_stores.documents.delete.assert_called_once_with(
        name="docs/alias-map-old",
        config={"force": True},
    )
```

- [ ] **Step 2: fetch stale-cleanup 회귀 테스트 강화 (failing test)**

`tests/test_criteria_alias_map_service_fetch.py` 의 `test_fetch_returns_newest_alias_map_when_duplicates_exist` 마지막 assert 만 교체:

```python
    # 기존:
    # client.file_search_stores.documents.delete.assert_called_once_with(
    #     name="docs/alias-map-old"
    # )

    # 신규:
    client.file_search_stores.documents.delete.assert_called_once_with(
        name="docs/alias-map-old",
        config={"force": True},
    )
```

- [ ] **Step 3: 테스트 실행해 실패 확인**

Run:
```
.venv/bin/pytest tests/test_criteria_alias_map_service_replace.py tests/test_criteria_alias_map_service_fetch.py -v
```
Expected: 위 2 테스트 FAIL — 실제 호출은 아직 `config` 미포함.

- [ ] **Step 4: `criteria_alias_map_service.py` 의 두 호출에 `config={"force": True}` 추가**

`app/services/criteria_alias_map_service.py:184` 부근 (fetch 의 stale cleanup):

```python
        for doc_name in cleanup_names:
            try:
                self._client.file_search_stores.documents.delete(
                    name=doc_name,
                    config={"force": True},
                )
            except Exception:
                logger.warning(
                    "stale alias_map cleanup failed for %s",
                    doc_name,
                    exc_info=True,
                )
```

`app/services/criteria_alias_map_service.py:241-242` 부근 (replace 의 old 삭제):

```python
        if old_doc_name:
            self._client.file_search_stores.documents.delete(
                name=old_doc_name,
                config={"force": True},
            )
```

- [ ] **Step 5: 테스트가 모두 통과하는지 확인**

Run:
```
.venv/bin/pytest tests/test_criteria_alias_map_service_replace.py tests/test_criteria_alias_map_service_fetch.py -v
```
Expected: 모두 PASS. `test_replace_does_not_delete_when_no_old_doc`, `test_replace_does_not_delete_when_upload_fails` 등 `assert_not_called` 검증 테스트가 영향 받지 않음(여전히 not called 이어야 함).

- [ ] **Step 6: 커밋**

```bash
git add app/services/criteria_alias_map_service.py tests/test_criteria_alias_map_service_replace.py tests/test_criteria_alias_map_service_fetch.py
git commit -m "fix(criteria-meta): pass force=True to alias_map documents.delete (issue #68)

Defensive fix: alias-map placeholder documents currently delete
successfully without force=True only because they have no chunks.
Match the criteria document delete path so a future SDK or content
change cannot reintroduce the 'Cannot delete non-empty Document'
regression on the alias-map cleanup paths (fetch stale dedupe,
replace old-doc cleanup).

Refs #68."
```

---

## Task 3: 전체 회귀 + lint 게이트 통과 확인

**Files:** (없음 — 검증만)

- [ ] **Step 1: 평가기준 관련 전체 단위 테스트 실행**

Run:
```
.venv/bin/pytest tests/ -k "criteria" -q
```
Expected: 모두 PASS. 새로 도입한 fix 외 다른 회귀 없음.

- [ ] **Step 2: 프로젝트 전체 테스트 스모크**

Run:
```
.venv/bin/pytest tests/ -q --ignore=tests/e2e
```
Expected: PASS (또는 사전부터 알려진 무관한 skip만). 알려지지 않은 새 실패가 나오면 멈추고 원인 분석.

- [ ] **Step 3: lint (프로젝트 표준 ruff 사용)**

Run:
```
.venv/bin/ruff check app/services/criteria_vector_service.py app/services/criteria_alias_map_service.py tests/test_criteria_vector_service_delete_individual.py tests/test_criteria_alias_map_service_replace.py tests/test_criteria_alias_map_service_fetch.py
```
Expected: `All checks passed!`

- [ ] **Step 4: 운영 DB 상 실제 삭제 시나리오 수동 확인 (선택, 클라우드 API key 보유 시)**

전제: `.env` 의 `GOOGLE_API_KEY` 가 실제 호출 가능한 키이고, 운영 DB(`data/app.db`) 의 `legacy_051085b106cc1688` 행을 정리하려는 시점.

순서:
1. 서버 기동:
   ```
   .venv/bin/uvicorn app.main:app --reload --port 8000
   ```
2. 관리자 로그인 후, 평가기준 화면에서 해당 legacy 항목 삭제 버튼 클릭.
3. 응답이 200 + `{"stable_id": "legacy_051085b106cc1688", "deleted": true}` 인지 확인.
4. DB 확인:
   ```
   .venv/bin/python -c "import sqlite3; c=sqlite3.connect('data/app.db'); print(list(c.execute('SELECT id, stable_id FROM criteria')))"
   ```
   Expected: `[]` (해당 행 사라짐).

수동 확인을 수행하지 못해도(키/환경 부재) Task 3 의 자동 회귀 게이트(Step 1-3)는 반드시 통과해야 한다.

- [ ] **Step 5: PR 생성**

```bash
git push -u origin HEAD
gh pr create --title "fix(criteria-meta): force=True on Gemini documents.delete (issue #68)" --body "$(cat <<'EOF'
## Summary
- `CriteriaVectorService.delete_criteria` 가 `documents.delete(name=..., config={"force": True})` 로 호출하도록 수정 → chunks 가 있는 평가기준 PDF Document 삭제가 400 FAILED_PRECONDITION 없이 성공.
- `CriteriaAliasMapService` 의 두 `documents.delete` 호출(replace 의 old doc, fetch 의 stale 정리)도 방어적으로 동일한 `force=True` 옵션을 사용 — 미래 회귀 차단.

## Closes
- Closes #68

## Test plan
- [ ] `.venv/bin/pytest tests/test_criteria_vector_service_delete_individual.py -v` — 새로 추가된 force 회귀 가드 PASS
- [ ] `.venv/bin/pytest tests/test_criteria_alias_map_service_replace.py tests/test_criteria_alias_map_service_fetch.py -v` — 갱신된 alias_map 테스트 PASS
- [ ] `.venv/bin/pytest tests/ -k criteria -q` — 평가기준 전체 단위 테스트 회귀 없음
- [ ] `.venv/bin/ruff check` — 수정 파일 모두 통과
- [ ] (선택, 키 보유 시) 운영 DB legacy 행 삭제 수동 확인

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review 결과

- **Spec coverage:** Issue #68 의 모든 제안 수정 방향(① delete_criteria force=True, ② alias_map 두 곳 방어적 force=True, ③ 단위 테스트 보강, ④ alias_map 관련 테스트 갱신, ⑤ 회귀 게이트)이 Task 1-3 에 매핑됨. Issue 의 "선택 E2E 회귀"는 Task 3 Step 4 의 수동 확인으로 대체(자동 E2E 추가는 별도 PR 권장 — 운영 키 의존성 큼).
- **Placeholder scan:** "TODO/TBD/적절한 에러 처리" 없음. 모든 코드/명령 완전 기재.
- **Type consistency:** `documents.delete(name=..., config={"force": True})` 시그니처가 Task 1, 2, 그리고 모든 assert 에서 동일하게 사용됨.
