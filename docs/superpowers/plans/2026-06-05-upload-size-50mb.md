# 파일 업로드 한도 50MB 단일화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 파일 업로드 한도를 `settings.MAX_UPLOAD_SIZE`(=50MB) 단일 출처에서 파생시켜 백엔드·프론트 전체를 50MB로 통일한다.

**Architecture:** `FileValidator`의 10MB 하드코딩을 제거하고 `settings.MAX_UPLOAD_SIZE`를 기본값으로 사용. 대시보드 라우터는 같은 설정을 직접 참조. 평가기준 업로드 페이지는 설정값을 템플릿 컨텍스트로 받아 표기/JS 검증에 주입.

**Tech Stack:** FastAPI, Pydantic Settings, Jinja2, Vanilla JS, pytest.

---

## 관련 사실 / 제약

- 단일 출처: `settings.MAX_UPLOAD_SIZE` (`.env`의 `MAX_UPLOAD_SIZE=52428800` = 50MB). 이미 50MB이므로 설정값 변경 없음.
- 백엔드 enforcement 지점: `FileValidator` (대시보드 `views.py`, 평가기준 `admin/criteria.py` 모두 사용).
- `views.py`에서 `FileValidator`는 **line 32의 `MAX_FILE_SIZE` 참조 전용** → settings로 바꾸면 line 26 import는 orphan이 되어 함께 제거.
- 테스트 인터프리터: `.venv/bin/python -m pytest` (bare `python` 없음).
- 타깃 baseline(변경 전): 아래 명령 기준 **16 passed / 2 skipped / 2 errors**. 2 errors는 `tests/test_dashboard_upload_creates_upload_row.py`의 `email` kwarg stale fixture(email 제거 리팩터 #91/#93 잔재)로 **pre-existing**, 본 작업 범위 밖.
  ```
  .venv/bin/python -m pytest -q tests/test_dashboard_upload_creates_upload_row.py tests/test_admin_criteria_upload_v2.py tests/test_admin_criteria_replace.py tests/test_e2e_legacy_replace_flow.py tests/routers/test_criteria_router_sync.py
  ```

---

## File Structure

- Create: `tests/test_upload_size_limit_config.py` — 업로드 한도가 settings 단일 출처에서 파생되는지 검증하는 단위 테스트.
- Modify: `app/services/file_validator.py` — 하드코딩 제거, settings 기본값.
- Modify: `app/routers/views.py` — `DASHBOARD_MAX_UPLOAD_SIZE`를 settings로, orphan import 제거.
- Modify: `app/routers/admin/criteria_views.py` — 업로드 페이지 컨텍스트에 `max_upload_size` 주입.
- Modify: `app/templates/admin/criteria_upload.html` — 표기 동적화 + JS 주입.
- Modify: `app/static/js/criteria_upload.js` — 주입값 기반 검증.

---

## Task 1: FileValidator가 settings.MAX_UPLOAD_SIZE를 기본값으로 사용

**Files:**
- Test: `tests/test_upload_size_limit_config.py`
- Modify: `app/services/file_validator.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_upload_size_limit_config.py` 생성:

```python
"""업로드 한도가 settings.MAX_UPLOAD_SIZE 단일 출처에서 파생되는지 검증."""
from app.config import settings
from app.services.file_validator import FileValidator


def test_settings_max_upload_size_is_50mb():
    assert settings.MAX_UPLOAD_SIZE == 50 * 1024 * 1024


def test_file_validator_defaults_to_settings_max_upload_size():
    validator = FileValidator()
    assert validator.max_file_size == settings.MAX_UPLOAD_SIZE


def test_file_validator_explicit_override_still_works():
    validator = FileValidator(max_size_mb=10)
    assert validator.max_file_size == 10 * 1024 * 1024
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_upload_size_limit_config.py`
Expected: `test_file_validator_defaults_to_settings_max_upload_size` FAIL (현재 10MB == 10485760 ≠ 52428800). 나머지 2개는 PASS.

- [ ] **Step 3: 최소 구현** — `app/services/file_validator.py` 수정.

imports에 settings 추가 (line 9 `from fastapi import ...` 다음):
```python
from fastapi import UploadFile, HTTPException

from app.config import settings
```

하드코딩 상수 제거 (현재 line 26-27):
```python
    # 최대 파일 크기 (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024
```
→ 삭제.

`__init__`의 else 분기 (현재 line 47-50):
```python
        if max_size_mb:
            self.max_file_size = max_size_mb * 1024 * 1024
        else:
            self.max_file_size = self.MAX_FILE_SIZE
```
→ 변경:
```python
        if max_size_mb:
            self.max_file_size = max_size_mb * 1024 * 1024
        else:
            self.max_file_size = settings.MAX_UPLOAD_SIZE
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_upload_size_limit_config.py`
Expected: 3 passed.

- [ ] **Step 5: 커밋**

```bash
git add tests/test_upload_size_limit_config.py app/services/file_validator.py
git commit -m "feat(upload): FileValidator 기본 한도를 settings.MAX_UPLOAD_SIZE(50MB)로 파생"
```

---

## Task 2: 대시보드 업로드 한도를 settings로 일원화 (orphan import 제거)

**Files:**
- Test: `tests/test_upload_size_limit_config.py` (테스트 추가)
- Modify: `app/routers/views.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_upload_size_limit_config.py` 끝에 추가:

```python
def test_dashboard_max_upload_size_uses_settings():
    from app.routers import views
    assert views.DASHBOARD_MAX_UPLOAD_SIZE == settings.MAX_UPLOAD_SIZE
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_upload_size_limit_config.py::test_dashboard_max_upload_size_uses_settings`
Expected: 현 상태에서도 우연히 PASS일 수 있음(Task1 이후 FileValidator 기본=settings라서 `FileValidator.MAX_FILE_SIZE`는 이제 존재하지 않음 → 실제로는 line 32가 `FileValidator.MAX_FILE_SIZE`를 참조하므로 **AttributeError로 import 단계 ERROR**). Expected: ERROR/FAIL (MAX_FILE_SIZE 제거로 인한 AttributeError).

- [ ] **Step 3: 최소 구현** — `app/routers/views.py` 수정.

orphan이 될 import 제거 (현재 line 26):
```python
from app.services.file_validator import FileValidator
```
→ 삭제.

settings import 추가 (line 16 `from app.db import get_db` 위/근처, app.* 그룹):
```python
from app.config import settings
from app.db import get_db
```

상수 변경 (현재 line 32):
```python
DASHBOARD_MAX_UPLOAD_SIZE = FileValidator.MAX_FILE_SIZE
```
→
```python
DASHBOARD_MAX_UPLOAD_SIZE = settings.MAX_UPLOAD_SIZE
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_upload_size_limit_config.py`
Expected: 4 passed.
또한 views import 무결성:
Run: `.venv/bin/python -c "from app.routers import views; print(views.DASHBOARD_MAX_UPLOAD_SIZE)"`
Expected: `52428800`

- [ ] **Step 5: 커밋**

```bash
git add tests/test_upload_size_limit_config.py app/routers/views.py
git commit -m "feat(upload): 대시보드 업로드 한도를 settings.MAX_UPLOAD_SIZE로 일원화"
```

---

## Task 3: 평가기준 업로드 페이지 프론트 한도를 백엔드 값에서 동기화

**Files:**
- Modify: `app/routers/admin/criteria_views.py`
- Modify: `app/templates/admin/criteria_upload.html`
- Modify: `app/static/js/criteria_upload.js`

> 참고: 이 레포에는 JS 단위 테스트 인프라가 없으므로 본 태스크는 라우터 컨텍스트 단위 테스트 + 수동 grep으로 검증한다.

- [ ] **Step 1: 라우터 컨텍스트 테스트 추가** — `tests/test_upload_size_limit_config.py` 끝에 추가:

```python
def test_criteria_upload_page_injects_max_upload_size(monkeypatch):
    """criteria_upload_page 가 컨텍스트에 max_upload_size 를 주입하는지 검증."""
    import app.routers.admin.criteria_views as cv

    captured = {}

    class _FakeTemplates:
        def TemplateResponse(self, name, context):
            captured["name"] = name
            captured["context"] = context
            return context

    monkeypatch.setattr(cv, "templates", _FakeTemplates())

    import asyncio
    from types import SimpleNamespace

    admin = SimpleNamespace(username="admin")
    asyncio.run(cv.criteria_upload_page(request=object(), current_admin=admin))

    assert captured["context"]["max_upload_size"] == settings.MAX_UPLOAD_SIZE
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest -q tests/test_upload_size_limit_config.py::test_criteria_upload_page_injects_max_upload_size`
Expected: FAIL with `KeyError: 'max_upload_size'`.

- [ ] **Step 3: 라우터 구현** — `app/routers/admin/criteria_views.py` 수정.

settings import 추가 (기존 `from app.db import get_db` 근처):
```python
from app.config import settings
```

`criteria_upload_page` 의 TemplateResponse 컨텍스트(현재 line 141-145)에 키 추가:
```python
    return templates.TemplateResponse(
        "admin/criteria_upload.html",
        {
            "request": request,
            "user": current_admin,
            "max_upload_size": settings.MAX_UPLOAD_SIZE,
        }
    )
```

- [ ] **Step 4: 라우터 테스트 통과 확인**

Run: `.venv/bin/python -m pytest -q tests/test_upload_size_limit_config.py::test_criteria_upload_page_injects_max_upload_size`
Expected: PASS.

- [ ] **Step 5: 템플릿 구현** — `app/templates/admin/criteria_upload.html` 수정.

표기 (현재 line 98):
```html
                            PDF 파일 (최대 10MB)
```
→
```html
                            PDF 파일 (최대 {{ (max_upload_size / 1024 / 1024) | round | int }}MB)
```

scripts 블록 (현재 line 174-176)에서 JS 로드 직전 주입:
```html
{% block scripts %}
<script src="/static/js/criteria_upload.js"></script>
{% endblock %}
```
→
```html
{% block scripts %}
<script>window.MAX_UPLOAD_SIZE = {{ max_upload_size }};</script>
<script src="/static/js/criteria_upload.js"></script>
{% endblock %}
```

- [ ] **Step 6: JS 구현** — `app/static/js/criteria_upload.js` 수정 (현재 line 68-74).

```javascript
        // 파일 크기 검증 (10MB)
        const maxSize = 10 * 1024 * 1024;
        if (file.size > maxSize) {
            alert(
                '파일 크기가 10MB를 초과합니다. ' +
                '더 작은 파일을 선택해주세요.'
            );
```
→
```javascript
        // 파일 크기 검증 (백엔드 settings.MAX_UPLOAD_SIZE 주입값)
        const maxSize = window.MAX_UPLOAD_SIZE || 50 * 1024 * 1024;
        if (file.size > maxSize) {
            const maxMB = (maxSize / 1024 / 1024).toFixed(0);
            alert(
                `파일 크기가 ${maxMB}MB를 초과합니다. ` +
                '더 작은 파일을 선택해주세요.'
            );
```

- [ ] **Step 7: 잔존 10MB grep 검증**

Run:
```bash
grep -rniE "10 ?\* ?1024 ?\* ?1024|최대 ?10MB|10MB를 초과" app/services/file_validator.py app/routers/views.py app/templates/admin/criteria_upload.html app/static/js/criteria_upload.js
```
Expected: 출력 없음 (잔존 0건).

- [ ] **Step 8: 커밋**

```bash
git add app/routers/admin/criteria_views.py app/templates/admin/criteria_upload.html app/static/js/criteria_upload.js tests/test_upload_size_limit_config.py
git commit -m "feat(upload): 평가기준 업로드 프론트 한도를 백엔드 settings 값과 동기화"
```

---

## Task 4: 회귀 검증 (baseline 대비 신규 실패 0건)

**Files:** 없음 (검증 전용)

- [ ] **Step 1: 신규 테스트 전체 통과**

Run: `.venv/bin/python -m pytest -q tests/test_upload_size_limit_config.py`
Expected: 5 passed.

- [ ] **Step 2: 업로드 관련 모듈 회귀 (baseline 대비)**

Run:
```bash
.venv/bin/python -m pytest -q tests/test_dashboard_upload_creates_upload_row.py tests/test_admin_criteria_upload_v2.py tests/test_admin_criteria_replace.py tests/test_e2e_legacy_replace_flow.py tests/routers/test_criteria_router_sync.py
```
Expected: **16 passed / 2 skipped / 2 errors** (2 errors는 변경 전과 동일한 pre-existing `email` fixture 문제 — 신규 실패 0건).

- [ ] **Step 3: 앱 import 무결성**

Run: `.venv/bin/python -c "import app.main"`
Expected: 예외 없음.

---

## Self-Review 메모

- 스펙의 5개 변경 파일 + 테스트 모두 태스크로 커버됨.
- orphan import 제거(views.py line 26)를 Task 2에 명시 — CLAUDE.md "내 변경이 만든 orphan 제거" 준수, 그 외 pre-existing dead code는 손대지 않음.
- 범위 밖: `.env`/`config.py`/`README.md`(이미 50MB), `email` stale fixture(별도 이슈).
