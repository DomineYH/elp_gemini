# Issue #62 — Pre-v2 평가기준 교체(replace) 워크플로 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use agent-team-driven-development to execute this plan.

**Goal:** PR #59 이전에 업로드되어 cloud `custom_metadata`에 `stable_id`가 없는 평가기준(=legacy surrogate)을 관리자가 한 번의 PDF 재업로드로 v2 stable_id 문서로 교체할 수 있는 정식 경로를 제공한다. 그 결과 기존 운영 환경에서도 모든 평가기준이 활성화 가능해진다.

**Architecture:**
Gemini File Search API는 업로드된 document의 `custom_metadata` 수정을 지원하지 않으므로, 단순 패치로는 `stable_id`를 백필할 수 없다. 또한 원본 PDF를 클라우드에서 다운로드할 수도 없다 (embedding-only). 따라서 유일한 가능한 해법은 **관리자가 PDF 원본을 재공급**하는 것이다. 본 계획은 이 재공급을 (a) 명시적 UI 버튼 + (b) 원자적 서버 엔드포인트로 안내한다: legacy 행에서 "교체" 클릭 → 파일 선택 → `POST /api/admin/criteria/{legacy_stable_id}/replace` → 새 ULID 발급 + 새 cloud document upload + alias_map의 legacy entry를 새 entry로 교체 (alias 승계, status="uploaded") + 기존 cloud document 삭제 + DB 행 교체. 부분 실패 시 `needs_resync`로 표시해 자가 치유한다.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, google-genai SDK, Jinja2, vanilla JS, pytest + pytest-asyncio.

---

## Wave Analysis

### Specialists

| Role | Expertise | Tasks |
|------|-----------|-------|
| backend-engineer | FastAPI 라우터, criteria 서비스(alias_map/vector), 비동기 SQLAlchemy 리포지토리, pytest-asyncio | Tasks 1, 4, 5 |
| frontend-engineer | Jinja2 템플릿, FastAPI 컨텍스트 주입, vanilla JS DOM 핸들러, 템플릿/JS 렌더링 회귀 테스트 | Tasks 2, 3 |

### Waves

**Wave 1: 교체 컨트랙트 — 서버 엔드포인트 + 템플릿 가시화 (병렬)** — UI 진입점과 서버 엔드포인트를 동시에 만든다. 두 작업은 합의된 URL 경로(`/api/admin/criteria/{stable_id}/replace`)와 multipart 폼 컨트랙트를 공유한다.
- Task 1 (backend-engineer) — `POST /api/admin/criteria/{stable_id}/replace` 엔드포인트
- Task 2 (frontend-engineer) — 템플릿 컨텍스트 `is_legacy` 주입 + legacy 행에 "교체" 버튼 렌더

  *Parallel-safe because:* Task 1은 `app/routers/admin/criteria.py`와 새 테스트 파일만 수정한다. Task 2는 `app/routers/admin/criteria_views.py`(다른 라우터 파일), `app/templates/admin/criteria_list.html`, 템플릿/뷰 테스트만 수정한다. 두 작업은 import 관계가 없고 파일 교집합도 없다. URL 경로는 문자열 상수로 양쪽이 독립 참조한다.

**Wave 2: 와이어링 — JS 핸들러 + activate 오류 메시지 정렬 (병렬)** — Wave 1이 만든 엔드포인트/버튼 사이를 잇고, 기존 activate 오류 메시지가 새 UI 경로를 가리키도록 정렬한다.
- Task 3 (frontend-engineer) — `criteria_list.js`에 "교체" 클릭 → file picker → POST 핸들러
- Task 4 (backend-engineer) — `activate_by_stable_id` 오류 메시지를 "삭제 후 다시 업로드"에서 "목록의 '교체' 버튼으로 동일 PDF를 재업로드"로 변경

  *Parallel-safe because:* Task 3은 `app/static/js/criteria_list.js`와 JS 테스트만 수정. Task 4는 `app/routers/admin/criteria.py`의 다른 함수(`_set_status_by_stable_id`)와 `tests/routers/test_criteria_router_sync.py`만 수정. 두 작업은 파일 교집합 없음.
  *Depends on Wave 1:*
  - Task 3은 Task 1이 등록한 `POST /api/admin/criteria/{stable_id}/replace` 엔드포인트와 응답 스키마(`{old_stable_id, new_stable_id, document_id}`)를 호출한다.
  - Task 3은 Task 2가 추가한 `[data-action="replace"]` 버튼 셀렉터를 바인딩한다.
  - Task 4의 메시지 문구는 Task 2의 버튼 라벨("교체")과 일치해야 한다.

**Wave 3: 통합 검증 — end-to-end 교체 플로우 회귀** — 모든 변경을 모은 하나의 시나리오로 회귀 보호.
- Task 5 (backend-engineer) — 시뮬레이션: legacy surrogate가 있는 alias_map → reconcile → replace 엔드포인트 호출 → 새 stable_id의 활성화까지 통과

  *Depends on Wave 2:* Tasks 1–4의 모든 산출물(replace 엔드포인트, alias_map 변환 로직, DB 교체, 새 activate 오류 메시지)을 단일 테스트가 호출한다.

### Dependency Graph

```
Task 1 ──┬──→ Task 3 ──┐
         │             │
Task 2 ──┴──→ Task 4 ──┴──→ Task 5
```

---

## Tasks

### Task 1: Backend — `POST /api/admin/criteria/{stable_id}/replace` 엔드포인트

**Specialist:** backend-engineer
**Depends on:** None (Wave 1)
**Produces:**
- Public API: `POST /api/admin/criteria/{stable_id}/replace` (multipart `file`)
- Response JSON: `{"old_stable_id": "...", "new_stable_id": "...", "document_id": "..."}`
- 합의된 동작: legacy surrogate 행에만 적용 가능 (그 외는 400)
- 새 테스트 파일 `tests/test_admin_criteria_replace.py` 의 단위 mock 패턴 — Task 5의 e2e 테스트가 동일 mock 표면을 재사용

**Files:**
- Modify: `app/routers/admin/criteria.py` (새 엔드포인트 함수 추가; 기존 `upload_criteria`와 `_set_status_by_stable_id` 함수는 그대로 유지)
- Test: `tests/test_admin_criteria_replace.py` (신규)

- [ ] **Step 1: 실패 테스트를 먼저 작성**

신규 파일 `tests/test_admin_criteria_replace.py` 생성:

```python
"""replace 라우터: legacy surrogate를 v2 stable_id 문서로 교체"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.admin.criteria import (
    replace_legacy_criteria,
    router,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry


def test_replace_route_is_registered():
    paths = [r.path for r in router.routes if hasattr(r, "path")]
    assert "/api/admin/criteria/{stable_id}/replace" in paths


@pytest.mark.asyncio
async def test_replace_rejects_non_legacy_stable_id():
    file = SimpleNamespace(
        filename="r.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 r"),
    )
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await replace_legacy_criteria(
            stable_id="01HV2REAL",
            file=file,
            current_admin=SimpleNamespace(username="admin"),
            _sync_ready=None,
            db=db,
        )

    assert exc.value.status_code == 400
    assert "legacy" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_replace_uploads_new_doc_preserves_alias_and_deletes_old():
    legacy_sid = "legacy_0123456789abcdef"
    old_doc = "fileSearchStores/s/documents/old"
    new_doc = "fileSearchStores/s/documents/new"

    file = SimpleNamespace(
        filename="rubric.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 r"),
    )
    db = AsyncMock()

    with patch(
        "app.routers.admin.criteria.FileValidator"
    ) as validator_cls, patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )

        vec = vector_cls.return_value
        vec.file_search_service.client = MagicMock()
        vec.upload_criteria = AsyncMock(return_value={"document_id": new_doc})
        vec.delete_criteria = AsyncMock(return_value=True)

        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "docs/alias-map",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:00:00Z",
                entries={
                    legacy_sid: AliasMapEntry(
                        alias="1학기 평가기준",
                        status="uploaded",
                        activated_at=None,
                    ),
                },
            ),
        ))
        alias.replace = AsyncMock()

        repo = repo_cls.return_value
        repo.get_criteria_by_stable_id = AsyncMock(return_value=SimpleNamespace(
            stable_id=legacy_sid,
            document_id=old_doc,
            display_alias="1학기 평가기준",
        ))
        repo.insert = AsyncMock()
        # delete is performed via db.delete(row); leave as AsyncMock default

        result = await replace_legacy_criteria(
            stable_id=legacy_sid,
            file=file,
            current_admin=SimpleNamespace(username="admin"),
            _sync_ready=None,
            db=db,
        )

    assert result["old_stable_id"] == legacy_sid
    assert result["new_stable_id"].startswith("") and result["new_stable_id"] != legacy_sid
    assert result["document_id"] == new_doc

    # upload happened before any destructive op
    vec.upload_criteria.assert_awaited_once()
    upload_kwargs = vec.upload_criteria.await_args.kwargs
    assert upload_kwargs["title"] == "rubric.pdf"
    assert upload_kwargs["stable_id"] == result["new_stable_id"]

    # alias_map replace was called with new entry preserving alias
    alias.replace.assert_awaited_once()
    new_alias_map = alias.replace.await_args.args[0]
    assert legacy_sid not in new_alias_map.entries
    new_entry = new_alias_map.entries[result["new_stable_id"]]
    assert new_entry.alias == "1학기 평가기준"
    assert new_entry.status == "uploaded"
    assert new_entry.activated_at is None

    # old cloud document deleted after alias_map updated
    vec.delete_criteria.assert_awaited_once_with(document_id=old_doc)
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_admin_criteria_replace.py -v`
Expected: FAIL with `ImportError: cannot import name 'replace_legacy_criteria' from 'app.routers.admin.criteria'`

- [ ] **Step 3: 최소 구현 — 엔드포인트 추가**

`app/routers/admin/criteria.py` 의 다른 라우트들 사이(예: `delete_criteria_by_stable_id` 바로 다음, `patch_criteria_alias` 앞)에 다음을 추가:

```python
@router.post(
    "/{stable_id}/replace",
    summary="평가기준 PDF 교체 (legacy → v2 마이그레이션 경로)",
    description=(
        "stable_id가 legacy surrogate인 평가기준 행을 동일/대체 PDF "
        "재업로드로 새 v2 stable_id 문서로 교체합니다. alias는 승계됩니다."
    ),
)
async def replace_legacy_criteria(
    stable_id: str,
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_admin),
    _sync_ready=Depends(require_criteria_sync_ready),
    db: AsyncSession = Depends(get_db),
):
    if not is_legacy_surrogate_stable_id(stable_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "교체는 legacy(pre-v2) 평가기준에만 적용됩니다. "
                "이미 v2 stable_id를 가진 행은 일반 삭제/업로드를 사용하세요."
            ),
        )

    temp_file_path = None
    cloud_write_started = False
    try:
        validator = FileValidator()
        validation_result = await validator.validate_file(file)
        if not validation_result["valid"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=validation_result["error"],
            )

        file_content = await file.read()
        suffix = os.path.splitext(file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_content)
            temp_file_path = tmp.name

        vec = CriteriaVectorService()
        alias_svc = CriteriaAliasMapService(
            client=vec.file_search_service.client,
            store_display_name=settings.FS_RUBRIC_STORE_NAME,
        )
        repo = CriteriaRepository(db)

        try:
            fetched = await alias_svc.fetch()
        except AliasMapParseError as e:
            await _raise_alias_map_parse_unavailable(db, e)
        if fetched is None:
            await _raise_alias_map_missing_conflict(db)
        old_doc_name, alias_map = fetched
        if stable_id not in alias_map.entries:
            raise HTTPException(
                status_code=404,
                detail=f"평가기준 stable_id={stable_id} 를 찾을 수 없습니다",
            )
        old_alias = alias_map.entries[stable_id].alias

        old_row = await repo.get_criteria_by_stable_id(stable_id)
        if not old_row:
            raise HTTPException(
                status_code=404,
                detail=f"DB 캐시에 stable_id={stable_id} 행이 없습니다",
            )
        old_document_id = old_row.document_id

        # 1) 새 stable_id로 cloud upload (다른 어떤 파괴적 작업보다 먼저).
        new_stable_id = _new_stable_id()
        cloud_write_started = True
        upload_result = await vec.upload_criteria(
            file_path=temp_file_path,
            title=file.filename,
            stable_id=new_stable_id,
        )
        new_document_id = upload_result["document_id"]

        # 2) alias_map: legacy entry 제거 + 새 entry 추가 (alias 승계).
        new_entries = dict(alias_map.entries)
        new_entries.pop(stable_id, None)
        new_entries[new_stable_id] = AliasMapEntry(
            alias=old_alias,
            status="uploaded",
            activated_at=None,
        )
        new_alias_map = AliasMap(
            schema_version=1,
            updated_at=_now_iso_utc(),
            entries=new_entries,
        )
        await alias_svc.replace(new_alias_map, old_doc_name=old_doc_name)

        # 3) cloud 옛 document 삭제 (alias_map publish 성공 후).
        await vec.delete_criteria(document_id=old_document_id)

        # 4) DB: 옛 행 삭제 + 새 행 삽입.
        await db.delete(old_row)
        await repo.insert(
            stable_id=new_stable_id,
            document_id=new_document_id,
            title=file.filename,
            display_alias=old_alias,
            status="uploaded",
            created_at=None,
            activated_at=None,
            uploaded_by=current_admin.username,
        )
        await db.commit()

        logger.info(
            "평가기준 교체: legacy_stable_id=%s → new_stable_id=%s "
            "old_document_id=%s new_document_id=%s",
            stable_id, new_stable_id, old_document_id, new_document_id,
        )
        return {
            "old_stable_id": stable_id,
            "new_stable_id": new_stable_id,
            "document_id": new_document_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        await _raise_criteria_mutation_failed(
            db, e, cloud_write_started=cloud_write_started,
        )
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                logger.warning("임시 파일 삭제 실패", exc_info=True)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_admin_criteria_replace.py -v`
Expected: PASS — 3 tests pass.

- [ ] **Step 5: 기존 라우터 회귀 테스트 무영향 확인**

Run: `pytest tests/routers/test_criteria_router_sync.py tests/test_admin_criteria_activate.py tests/test_admin_criteria_upload_v2.py tests/test_admin_criteria_delete_v2.py -v`
Expected: PASS — 새 엔드포인트 추가가 기존 라우트 동작을 깨지 않음.

- [ ] **Step 6: 커밋**

```bash
git add app/routers/admin/criteria.py tests/test_admin_criteria_replace.py
git commit -m "feat(criteria-meta): POST /{stable_id}/replace endpoint for legacy migration (issue #62)"
```

---

### Task 2: Frontend — 템플릿 컨텍스트 `is_legacy` 주입 + "교체" 버튼 렌더

**Specialist:** frontend-engineer
**Depends on:** None (Wave 1) — Task 1과 URL 컨트랙트만 공유, 코드 의존성 없음
**Produces:**
- 템플릿 컨텍스트에 행별 `is_legacy: bool` 노출
- legacy 행은 (a) 활성 라디오 비활성화 + (b) "Legacy v1" 배지 + (c) `[data-action="replace"]` 속성을 가진 "교체" 버튼을 렌더
- Task 3의 JS 핸들러가 바인딩할 셀렉터: `button[data-action="replace"][data-stable-id="..."]`

**Files:**
- Modify: `app/routers/admin/criteria_views.py:42-55` (`_criteria_items_from_rows`)
- Modify: `app/templates/admin/criteria_list.html:67-101` (테이블 행 렌더링)
- Test: `tests/test_criteria_list_view.py` (컨텍스트 주입 검증; 기존 파일에 케이스 추가)
- Test: `tests/test_criteria_list_template.py` (legacy 행 렌더 검증; 기존 파일에 케이스 추가)

- [ ] **Step 1: 실패 테스트 — view 컨텍스트**

`tests/test_criteria_list_view.py` 에 다음 테스트를 추가 (기존 헬퍼 `_criteria_items_from_rows` import 사용):

```python
def test_criteria_items_marks_legacy_surrogate_rows():
    """legacy_ prefix를 가진 stable_id 행은 is_legacy=True로 표시되어야 한다."""
    from types import SimpleNamespace
    from app.routers.admin.criteria_views import _criteria_items_from_rows

    rows = [
        SimpleNamespace(
            stable_id="legacy_abcdef0123456789",
            title="old.pdf",
            display_alias=None,
            status="uploaded",
            created_at=None,
            document_id="docs/old",
        ),
        SimpleNamespace(
            stable_id="01HV2REAL",
            title="new.pdf",
            display_alias=None,
            status="uploaded",
            created_at=None,
            document_id="docs/new",
        ),
    ]
    items = _criteria_items_from_rows(rows)
    by_sid = {i["stable_id"]: i for i in items}
    assert by_sid["legacy_abcdef0123456789"]["is_legacy"] is True
    assert by_sid["01HV2REAL"]["is_legacy"] is False
```

- [ ] **Step 2: 실패 테스트 — 템플릿 렌더링**

`tests/test_criteria_list_template.py` 에 다음을 추가 (기존 `_render` / `_item` 헬퍼 패턴 재사용; legacy 행에 맞춰 `is_legacy=True`를 전달하도록 `_item` 시그니처에 키워드 추가 가능):

```python
def test_legacy_row_renders_replace_button_and_disables_activate_radio():
    text = _render([_item(stable_id="legacy_aabbccdd", status="uploaded", is_legacy=True)])
    # "교체" 버튼이 legacy 행에 존재해야 함
    assert 'data-action="replace"' in text
    assert 'data-stable-id="legacy_aabbccdd"' in text
    assert "교체" in text
    # legacy 행에서는 활성 라디오가 비활성화되어 잘못 클릭하지 않음
    assert "disabled" in _row_for(text, "legacy_aabbccdd")
    # "Legacy" 라벨로 사용자에게 컨텍스트 제공
    assert "Legacy" in _row_for(text, "legacy_aabbccdd")


def test_non_legacy_row_has_no_replace_button():
    text = _render([_item(stable_id="01HV2REAL", status="uploaded", is_legacy=False)])
    assert 'data-action="replace"' not in text
```

`_item` 헬퍼가 아직 `is_legacy`를 받지 않으면 시그니처에 `is_legacy: bool = False`를 추가하고 반환 dict에 키를 포함시킨다. `_row_for(text, sid)` 헬퍼가 없다면 동일 파일 상단에 단순 substring slicer로 추가:

```python
def _row_for(html: str, stable_id: str) -> str:
    marker = f'data-stable-id="{stable_id}"'
    idx = html.index(marker)
    end = html.find("</tr>", idx)
    return html[idx:end]
```

- [ ] **Step 3: 두 테스트 모두 실패 확인**

Run: `pytest tests/test_criteria_list_view.py::test_criteria_items_marks_legacy_surrogate_rows tests/test_criteria_list_template.py -v`
Expected: FAIL — `is_legacy` 키 없음 / "교체" 마크업 없음.

- [ ] **Step 4: View 헬퍼 수정**

`app/routers/admin/criteria_views.py:42-55` 의 `_criteria_items_from_rows` 를 다음과 같이 교체:

```python
def _criteria_items_from_rows(all_criteria) -> list[dict]:
    """Template context rows; pre-reconcile rows without stable_id are hidden."""
    from app.services.criteria_reconciliation_service import (
        is_legacy_surrogate_stable_id,
    )
    return [
        {
            "stable_id": c.stable_id,
            "title": c.title,
            "display_alias": c.display_alias,
            "status": c.status,
            "created_at": c.created_at,
            "document_id": c.document_id,
            "is_legacy": is_legacy_surrogate_stable_id(c.stable_id),
        }
        for c in all_criteria
        if c.stable_id is not None
    ]
```

- [ ] **Step 5: 템플릿 수정**

`app/templates/admin/criteria_list.html:67-101` 의 `<tbody>` 부분을 다음으로 교체:

```html
      <tbody class="divide-y divide-gray-200" id="criteria-rows">
        {% for item in criteria_items %}
        <tr data-stable-id="{{ item.stable_id }}" {% if item.is_legacy %}data-legacy="true"{% endif %}>
          <td class="px-6 py-4 text-sm">
            <span class="alias-cell cursor-pointer hover:bg-blue-50 px-2 py-1 rounded inline-block min-w-[160px]"
                  data-original="{{ item.display_alias or '' }}">
              {{ item.display_alias or '(미설정)' }}
            </span>
          </td>
          <td class="px-6 py-4 text-sm text-gray-900">
            {{ item.title }}
            {% if item.is_legacy %}
            <span class="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800"
                  title="PR #59 이전에 업로드되어 v2 stable_id가 없는 평가기준. '교체' 버튼으로 PDF를 다시 업로드하면 활성화할 수 있습니다.">
              Legacy v1
            </span>
            {% endif %}
          </td>
          <td class="px-6 py-4 text-sm">
            <div class="inline-flex items-center gap-3">
              <label class="inline-flex items-center gap-2">
                <input type="radio" name="active_criteria" value="{{ item.stable_id }}"
                       {% if item.status == 'active' %}checked{% endif %}
                       {% if item.is_legacy %}disabled{% endif %}
                       class="active-radio">
                <span>{{ '활성' if item.status == 'active' else '비활성' }}</span>
              </label>
              {% if item.status == 'active' and not item.is_legacy %}
              <button type="button"
                      class="text-xs text-gray-600 hover:underline"
                      data-action="deactivate"
                      data-stable-id="{{ item.stable_id }}">비활성화</button>
              {% endif %}
            </div>
          </td>
          <td class="px-6 py-4 text-sm text-gray-500">
            {% if item.created_at %}{{ item.created_at.strftime('%Y-%m-%d %H:%M') }}{% else %}-{% endif %}
          </td>
          <td class="px-6 py-4 text-sm">
            {% if item.is_legacy %}
            <button type="button"
                    class="text-amber-700 hover:underline font-medium mr-3"
                    data-action="replace"
                    data-stable-id="{{ item.stable_id }}"
                    data-title="{{ item.title }}">교체</button>
            {% endif %}
            <button class="delete-btn text-red-600 hover:underline font-medium"
                    data-stable-id="{{ item.stable_id }}"
                    data-title="{{ item.title }}">삭제</button>
          </td>
        </tr>
        {% endfor %}
      </tbody>
```

- [ ] **Step 6: 모든 테스트 통과 확인**

Run: `pytest tests/test_criteria_list_view.py tests/test_criteria_list_template.py -v`
Expected: PASS — 새 테스트 + 기존 테스트 모두 그린.

- [ ] **Step 7: 커밋**

```bash
git add app/routers/admin/criteria_views.py app/templates/admin/criteria_list.html tests/test_criteria_list_view.py tests/test_criteria_list_template.py
git commit -m "feat(criteria-meta): mark legacy rows with badge + replace button (issue #62)"
```

---

### Task 3: Frontend — `criteria_list.js`에 "교체" 클릭 핸들러

**Specialist:** frontend-engineer
**Depends on:**
- Task 1 — `POST /api/admin/criteria/{stable_id}/replace` (multipart `file`) 엔드포인트 호출
- Task 2 — `button[data-action="replace"]` 셀렉터 + `data-stable-id` 속성
**Produces:** 사용자가 legacy 행의 "교체" 버튼을 누르면 파일 선택기가 열리고, PDF를 고르면 서버로 전송 후 페이지를 리로드한다.

**Files:**
- Modify: `app/static/js/criteria_list.js`
- Test: `tests/test_criteria_list_js.py` (기존 파일에 추가)

- [ ] **Step 1: 실패 테스트**

`tests/test_criteria_list_js.py` 의 기존 패턴(파일을 텍스트로 읽고 substring 검사)을 따라 추가:

```python
def test_replace_action_posts_to_replace_endpoint_with_multipart():
    js = (Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "criteria_list.js").read_text()
    # replace 버튼 셀렉터 바인딩
    assert '[data-action="replace"]' in js
    # FormData multipart 사용
    assert "FormData" in js
    # replace 엔드포인트 경로 문자열이 존재
    assert "/replace" in js
    assert "/api/admin/criteria/" in js
    # 파일 input은 PDF만 (accept 속성)
    assert "application/pdf" in js or '.pdf' in js
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_criteria_list_js.py -v`
Expected: FAIL — replace 관련 마크 부재.

- [ ] **Step 3: JS 핸들러 추가**

`app/static/js/criteria_list.js` 의 `DOMContentLoaded` 핸들러 내 `delete-btn` 바인딩 바로 다음(삭제 핸들러 아래)에 다음을 추가:

```javascript
  document.querySelectorAll('[data-action="replace"]').forEach((b) => {
    b.addEventListener('click', () => {
      const sid = b.dataset.stableId;
      const title = b.dataset.title;
      if (!confirm(
        `${title} 평가기준을 교체합니다.\n` +
        `동일하거나 대체할 PDF를 선택하세요. 새 stable_id가 발급되고 ` +
        `기존 표시 이름(별칭)은 자동으로 승계됩니다.`
      )) return;
      const picker = document.createElement('input');
      picker.type = 'file';
      picker.accept = 'application/pdf,.pdf';
      picker.addEventListener('change', async () => {
        const f = picker.files && picker.files[0];
        if (!f) return;
        await replaceCriteria(sid, f);
      });
      picker.click();
    });
  });
```

같은 파일에 다음 함수를 (`async function deleteCriteria` 바로 위 또는 아래에) 추가:

```javascript
async function replaceCriteria(sid, file) {
  const form = new FormData();
  form.append('file', file);
  try {
    const r = await fetch(`/api/admin/criteria/${sid}/replace`, {
      method: 'POST',
      body: form,
    });
    if (!r.ok) throw new Error(await r.text());
    location.reload();
  } catch (e) {
    alert(`교체 실패: ${e.message}`);
  }
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_criteria_list_js.py -v`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/static/js/criteria_list.js tests/test_criteria_list_js.py
git commit -m "feat(criteria-meta): wire replace button to multipart POST handler (issue #62)"
```

---

### Task 4: Backend — `activate_by_stable_id` 오류 메시지를 새 UI 경로로 정렬

**Specialist:** backend-engineer
**Depends on:** Task 2 — 새 UI에서 "교체" 라벨이 노출되어 메시지 문구와 정확히 일치해야 함
**Produces:** legacy stable_id 활성화 시도 시 사용자가 "삭제 후 다시 업로드"라는 실패하기 쉬운 경로 대신 "교체" 버튼을 안내받는다.

**Files:**
- Modify: `app/routers/admin/criteria.py:481-489` (`_set_status_by_stable_id` 내 `HTTPException` detail)
- Modify: `tests/routers/test_criteria_router_sync.py:155` (assertion 문구)

- [ ] **Step 1: 실패 테스트로 새 문구를 고정**

`tests/routers/test_criteria_router_sync.py:154-155` 를 다음으로 교체 (다른 assertion은 유지):

```python
    assert exc.value.status_code == 400
    assert "Legacy" in exc.value.detail
    assert "교체" in exc.value.detail
    # 옛 문구는 더 이상 안내되지 않음
    assert "삭제 후 다시 업로드" not in exc.value.detail
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/routers/test_criteria_router_sync.py::test_activate_rejects_legacy_surrogate_stable_id -v`
Expected: FAIL — 옛 문구가 여전히 detail에 포함됨.

- [ ] **Step 3: 메시지 교체**

`app/routers/admin/criteria.py:481-489` 의 `raise HTTPException(...)` 블록을 다음으로 교체:

```python
    if target_status == "active" and is_legacy_surrogate_stable_id(stable_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "Legacy(pre-v2) 평가기준은 직접 활성화할 수 없습니다. "
                "목록의 '교체' 버튼으로 동일하거나 대체할 PDF를 재업로드하면 "
                "v2 stable_id가 발급되어 활성화할 수 있습니다."
            ),
        )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/routers/test_criteria_router_sync.py -v`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/routers/admin/criteria.py tests/routers/test_criteria_router_sync.py
git commit -m "fix(criteria-meta): point legacy-activate error to new replace UI (issue #62)"
```

---

### Task 5: Backend — end-to-end 회귀: legacy → replace → activate 시나리오

**Specialist:** backend-engineer
**Depends on:** Tasks 1, 2, 3, 4 — 모든 표면(엔드포인트, 템플릿 컨텍스트, 오류 메시지, JS 마크업)을 합쳐 단일 테스트로 회귀 보호
**Produces:** `tests/test_e2e_legacy_replace_flow.py` — `pytest -k legacy_replace`로 실행 가능한 단일 시나리오 회귀.

**Files:**
- Test: `tests/test_e2e_legacy_replace_flow.py` (신규)

- [ ] **Step 1: 시나리오 테스트 작성**

```python
"""End-to-end: legacy surrogate가 살아 있는 alias_map → replace → activate.

기존 운영 환경 시뮬레이션(pre-v2 cloud doc이 stable_id 메타데이터 없이 존재).
이 테스트는 Tasks 1-4가 모두 정합한지 한 번에 확인한다.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.admin.criteria import (
    activate_by_stable_id,
    replace_legacy_criteria,
)
from app.schemas.alias_map import AliasMap, AliasMapEntry
from app.services.criteria_reconciliation_service import (
    legacy_surrogate_stable_id,
)


@pytest.mark.asyncio
async def test_legacy_replace_then_activate_round_trip():
    old_doc = "fileSearchStores/s/documents/pre-v2"
    legacy_sid = legacy_surrogate_stable_id(old_doc)
    new_doc = "fileSearchStores/s/documents/v2-new"

    # 1) 활성화 직접 시도 → 새 UI를 안내하는 400
    db_activate = AsyncMock()
    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias_cls.return_value.fetch = AsyncMock(return_value=(
            "docs/alias-map",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:00:00Z",
                entries={
                    legacy_sid: AliasMapEntry(
                        alias="기준 v1",
                        status="uploaded",
                        activated_at=None,
                    ),
                },
            ),
        ))
        alias_cls.return_value.replace = AsyncMock()
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=SimpleNamespace(
                stable_id=legacy_sid,
                document_id=old_doc,
                status="uploaded",
            )
        )
        with pytest.raises(HTTPException) as exc:
            await activate_by_stable_id(
                stable_id=legacy_sid,
                current_admin=object(),
                _sync_ready=None,
                db=db_activate,
            )
    assert exc.value.status_code == 400
    assert "교체" in exc.value.detail

    # 2) replace 엔드포인트 호출
    file = SimpleNamespace(
        filename="rubric_v1.pdf",
        read=AsyncMock(return_value=b"%PDF-1.4 rubric"),
    )
    db_replace = AsyncMock()
    with patch(
        "app.routers.admin.criteria.FileValidator"
    ) as validator_cls, patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        validator_cls.return_value.validate_file = AsyncMock(
            return_value={"valid": True}
        )
        vec = vector_cls.return_value
        vec.file_search_service.client = MagicMock()
        vec.upload_criteria = AsyncMock(return_value={"document_id": new_doc})
        vec.delete_criteria = AsyncMock(return_value=True)

        alias = alias_cls.return_value
        alias.fetch = AsyncMock(return_value=(
            "docs/alias-map",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:00:00Z",
                entries={
                    legacy_sid: AliasMapEntry(
                        alias="기준 v1",
                        status="uploaded",
                        activated_at=None,
                    ),
                },
            ),
        ))
        alias.replace = AsyncMock()

        repo = repo_cls.return_value
        repo.get_criteria_by_stable_id = AsyncMock(
            return_value=SimpleNamespace(
                stable_id=legacy_sid,
                document_id=old_doc,
                display_alias="기준 v1",
            )
        )
        repo.insert = AsyncMock()

        result = await replace_legacy_criteria(
            stable_id=legacy_sid,
            file=file,
            current_admin=SimpleNamespace(username="admin"),
            _sync_ready=None,
            db=db_replace,
        )

    new_sid = result["new_stable_id"]
    assert new_sid != legacy_sid
    assert not new_sid.startswith("legacy_")
    # alias_map: legacy entry는 사라지고 새 entry가 alias를 승계
    publish_call = alias.replace.await_args.args[0]
    assert legacy_sid not in publish_call.entries
    assert publish_call.entries[new_sid].alias == "기준 v1"

    # 3) 새 stable_id로 activate 호출 — 정상 동작
    db_activate2 = AsyncMock()
    with patch(
        "app.routers.admin.criteria.CriteriaVectorService"
    ) as vector_cls, patch(
        "app.routers.admin.criteria.CriteriaAliasMapService"
    ) as alias_cls, patch(
        "app.routers.admin.criteria.CriteriaRepository"
    ) as repo_cls:
        vector_cls.return_value.file_search_service.client = MagicMock()
        alias_cls.return_value.fetch = AsyncMock(return_value=(
            "docs/alias-map",
            AliasMap(
                schema_version=1,
                updated_at="2026-05-15T00:01:00Z",
                entries={
                    new_sid: AliasMapEntry(
                        alias="기준 v1",
                        status="uploaded",
                        activated_at=None,
                    ),
                },
            ),
        ))
        alias_cls.return_value.replace = AsyncMock()
        repo_cls.return_value.get_criteria_by_stable_id = AsyncMock(
            return_value=SimpleNamespace(
                stable_id=new_sid,
                status="uploaded",
                activated_at=None,
            )
        )

        out = await activate_by_stable_id(
            stable_id=new_sid,
            current_admin=object(),
            _sync_ready=None,
            db=db_activate2,
        )

    assert out == {"stable_id": new_sid, "status": "active"}
```

- [ ] **Step 2: 실행 — 통과 확인**

Run: `pytest tests/test_e2e_legacy_replace_flow.py -v`
Expected: PASS — 3단계가 한 시나리오에서 모두 그린.

- [ ] **Step 3: 전체 criteria 회귀 묶음 실행 (안전망)**

Run: `pytest -k "criteria or legacy" -v`
Expected: 기존 + 새 테스트 모두 PASS.

- [ ] **Step 4: 커밋**

```bash
git add tests/test_e2e_legacy_replace_flow.py
git commit -m "test(criteria-meta): end-to-end legacy → replace → activate regression (issue #62)"
```

---

## Execution

Plan complete and saved to `docs/plans/2026-05-16-issue-62-pre-v2-criteria-replace.md`.

**Recommended: Agent Team-Driven** — Wave 1과 Wave 2 모두 병렬 가능한 작업이 2개씩 있고, backend/frontend 두 도메인이 명확히 분리되어 있어 팀 실행이 유리합니다. 각 Wave 후 두 단계 리뷰(자가 리뷰 + 코드 리뷰 전문 에이전트)로 회귀 차단.

**Alternative: Subagent-Driven** — 만약 인스턴스 한 번에 하나의 specialist만 운영하길 원한다면, 같은 Task 순서(1 → 2 → 3 → 4 → 5)를 직렬로 실행해도 무방합니다. 의존성 그래프가 그대로 유효함.

Which approach?
