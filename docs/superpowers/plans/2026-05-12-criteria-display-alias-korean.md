# 평가기준 표시 이름(display_alias) 한글 입력 허용 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자 평가기준 관리 화면의 "클라우드 Store 문서 표시 이름(display_alias)" 입력값이 현재 ASCII printable로만 제한되어 있는 것을, ASCII에 더하여 **한글(Hangul)** 도 허용하도록 변경한다.

**Architecture:** 변경 지점은 단 4곳이다 — (1) Pydantic 스키마 검증기 `UpdateDisplayAliasRequest.validate_alias`, (2) 검증기를 검사하는 두 개의 테스트, (3) 동일 규칙을 클라이언트에서 거울처럼 적용하는 인라인 편집기의 JS 정규식. DB 컬럼(`String(255)`), 리포지토리(`update_display_alias`), Jinja 템플릿(`{{ item.display_alias }}` / `{{ doc.alias }}`), QnA citation 치환 로직(`criteria.display_alias or criteria.title`)은 이미 한글 데이터를 그대로 처리한다 — 변경하지 않는다.

**Decision — allowed character set (명시):**
- 허용: `U+0020`–`U+007E` (printable ASCII) **AND** `U+AC00`–`U+D7A3` (Hangul Syllables) **AND** `U+1100`–`U+115E` / `U+1161`–`U+11FF` (Hangul Jamo, filler 제외) **AND** `U+3130`–`U+3163` / `U+3165`–`U+318F` (Hangul Compatibility Jamo, filler 제외)
- 거부 (기존 정책 유지): 이모지, 한자/CJK 통합, 다른 스크립트(히라가나·키릴 등), 제어 문자(`\x00`, `\n` 등), 길이 256 이상
- 길이 제한 255는 그대로 두며 **문자 수** 기준으로 검사 (UTF-8 바이트 길이 미사용 — SQLite는 TEXT로 저장, MySQL utf8mb4 VARCHAR(255)도 char 단위)

**Why this scope (and not "all Unicode"):** 사용자의 요청은 "ascii문자 말고 **한글도** 입력을 할 수 있도록"이며, 명시적으로 한글만 추가를 요청했다. 현재 테스트가 이모지를 거부하는 의도를 유지하므로, 외연을 한글로 한정한다.

**Tech Stack:** Python 3 · FastAPI · Pydantic v2 (`field_validator`) · SQLAlchemy async · SQLite (dev) / MySQL or Postgres (prod) · Jinja2 · vanilla JS · pytest / pytest-asyncio / httpx

---

## File Structure

- **Modify** `app/schemas/criteria.py` (lines 55–74) — `UpdateDisplayAliasRequest`의 검증기 및 필드 description
- **Modify** `app/static/js/criteria_list.js` (lines 303–306, 356) — `isPrintableAscii` 함수 및 한글 미허용 경고 메시지
- **Modify** `app/models/criteria.py` (lines 84–88) — `display_alias` 컬럼 comment 문구 (참조용 정확도)
- **Modify** `app/routers/admin/criteria.py` (lines 644–651) — PATCH 엔드포인트의 `summary`/`description`
- **Modify** `tests/test_criteria_display_alias_schema.py` — `test_rejects_korean` 제거, `test_accepts_korean` 및 `test_accepts_mixed_korean_ascii` 추가
- **Modify** `tests/test_admin_criteria_alias_router.py` — `test_patch_alias_rejects_korean` → `test_patch_alias_accepts_korean`

각 파일은 단일 책임을 유지한다. 신규 파일을 만들 필요는 없다 — 기존 모듈이 모두 ≤500줄로 관리 가능한 범위 안에 있다.

---

## Task 1: 스키마 검증기에 한글 허용 — RED 단계

**Files:**
- Modify: `tests/test_criteria_display_alias_schema.py:33-37`

- [ ] **Step 1: 기존 `test_rejects_korean`를 `test_accepts_korean`으로 교체**

`tests/test_criteria_display_alias_schema.py`에서 33~37행의 `test_rejects_korean`을 통째로 제거하고 그 자리에 다음을 둔다:

```python
def test_accepts_korean():
    req = UpdateDisplayAliasRequest(display_alias="평가기준-1")
    assert req.display_alias == "평가기준-1"


def test_accepts_pure_korean():
    req = UpdateDisplayAliasRequest(display_alias="수학기준")
    assert req.display_alias == "수학기준"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_criteria_display_alias_schema.py::test_accepts_korean -v`
Expected: FAIL — `ValidationError: 표시 가능한 ASCII 문자만 허용됩니다.`

---

## Task 2: 스키마 검증기 구현 — GREEN 단계

**Files:**
- Modify: `app/schemas/criteria.py:55-74`

- [ ] **Step 1: `validate_alias` 검증 로직 교체**

`app/schemas/criteria.py`의 55~74행 `UpdateDisplayAliasRequest` 전체를 다음으로 교체한다:

```python
class UpdateDisplayAliasRequest(BaseModel):
    """평가기준 표시명(alias) 업데이트 요청"""

    display_alias: Optional[str] = Field(
        default=None,
        description=(
            "표시명. ASCII printable(U+0020–U+007E) 및 한글(Hangul) 문자만 "
            "허용. None/빈 문자열이면 alias 제거."
        ),
    )

    @field_validator("display_alias")
    def validate_alias(cls, v):
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if not all(_is_allowed_alias_char(c) for c in v):
            raise ValueError(
                "표시명에 허용되지 않는 문자가 포함되어 있습니다. "
                "ASCII 또는 한글만 입력하세요."
            )
        if len(v) > 255:
            raise ValueError("표시명은 255자 이내로 입력하세요.")
        return v


def _is_allowed_alias_char(ch: str) -> bool:
    """display_alias에 허용되는 문자인지 판별.

    허용: ASCII printable + Hangul Syllables/Jamo/Compatibility Jamo.
    거부: 제어 문자, 이모지, 그 외 모든 스크립트.
    """
    code = ord(ch)
    if 0x20 <= code < 0x7F:
        return True
    if 0xAC00 <= code <= 0xD7A3:
        return True
    if (0x1100 <= code <= 0x115E) or (0x1161 <= code <= 0x11FF):
        return True
    if (0x3130 <= code <= 0x3163) or (0x3165 <= code <= 0x318F):
        return True
    return False
```

> 주의 — `_is_allowed_alias_char`는 모듈 최상위(클래스 밖)에 정의한다. Pydantic v2의 `field_validator`는 `classmethod` 컨텍스트로 동작하므로 헬퍼는 모듈 함수로 둬야 import 순환·정의 순서 문제를 피한다.

- [ ] **Step 2: 통과 확인**

Run: `uv run pytest tests/test_criteria_display_alias_schema.py -v`
Expected: 10개 테스트 모두 PASS (`test_accepts_ascii`, `test_strips_whitespace`, `test_empty_string_becomes_none`, `test_whitespace_only_becomes_none`, `test_none_stays_none`, `test_accepts_korean`, `test_accepts_pure_korean`, `test_rejects_emoji`, `test_rejects_over_255_chars`, `test_accepts_exactly_255_chars`, `test_rejects_control_characters`)

---

## Task 3: 경계 케이스 추가 검증 (이모지 거부 유지·혼합 입력 허용)

**Files:**
- Modify: `tests/test_criteria_display_alias_schema.py`

- [ ] **Step 1: 혼합 입력 테스트 추가**

`tests/test_criteria_display_alias_schema.py` 파일 끝에 다음을 append한다:

```python
def test_accepts_mixed_korean_and_ascii():
    req = UpdateDisplayAliasRequest(
        display_alias="Math 수학 grade-6"
    )
    assert req.display_alias == "Math 수학 grade-6"


def test_rejects_hanja_kanji():
    """한자(CJK 통합)는 한글이 아니므로 거부되어야 한다."""
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        UpdateDisplayAliasRequest(display_alias="数学")


def test_rejects_hiragana():
    """일본어 히라가나는 한글이 아니므로 거부되어야 한다."""
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        UpdateDisplayAliasRequest(display_alias="ひらがな")
```

(파일 상단의 `import pytest` / `from pydantic import ValidationError`는 이미 있으니 함수 내 import는 명시적 표시일 뿐 — 그대로 두어도 동작한다.)

- [ ] **Step 2: 추가 테스트 PASS 확인**

Run: `uv run pytest tests/test_criteria_display_alias_schema.py -v`
Expected: 13개 테스트 모두 PASS

- [ ] **Step 3: 커밋**

```bash
git add app/schemas/criteria.py tests/test_criteria_display_alias_schema.py
git commit -m "feat(criteria): allow Korean (Hangul) in display_alias validator

- Replace ASCII-only check with explicit allow-list of printable ASCII +
  Hangul Syllables / Jamo / Compatibility Jamo
- Update Pydantic field description and ValueError message
- Add tests for Korean, mixed Korean+ASCII; verify hanja/hiragana still rejected"
```

---

## Task 4: 라우터 통합 테스트 정합화

**Files:**
- Modify: `tests/test_admin_criteria_alias_router.py:110-117`

- [ ] **Step 1: `test_patch_alias_rejects_korean`를 `test_patch_alias_accepts_korean`으로 교체**

`tests/test_admin_criteria_alias_router.py`의 110~117행 함수 전체를 다음으로 교체한다:

```python
@pytest.mark.asyncio
async def test_patch_alias_accepts_korean(admin_client, make_criteria):
    """한글 alias가 정상적으로 저장·반환되는지 검증"""
    c = await make_criteria()
    res = await admin_client.patch(
        f"/api/admin/criteria/{c.id}/display-alias",
        json={"display_alias": "수학 평가기준"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["display_alias"] == "수학 평가기준"
```

- [ ] **Step 2: 통과 확인**

Run: `uv run pytest tests/test_admin_criteria_alias_router.py -v`
Expected: 6개 테스트 모두 PASS (`test_patch_alias_success`, `test_patch_alias_clears_with_null`, `test_patch_alias_not_found`, `test_patch_alias_accepts_korean`, `test_patch_alias_rejects_control_chars`, `test_patch_alias_forbidden_for_non_admin`)

- [ ] **Step 3: 커밋**

```bash
git add tests/test_admin_criteria_alias_router.py
git commit -m "test(criteria-alias): flip Korean rejection test to acceptance assertion"
```

---

## Task 5: 프론트엔드 인라인 편집 검증 완화

**Files:**
- Modify: `app/static/js/criteria_list.js:303-306`
- Modify: `app/static/js/criteria_list.js:356`

- [ ] **Step 1: `isPrintableAscii` 함수를 `isAllowedAliasChars`로 교체**

`app/static/js/criteria_list.js`의 303~306행을 다음으로 교체한다:

```javascript
function isAllowedAliasChars(s) {
    // ASCII printable + Hangul (Syllables, Jamo, Compatibility Jamo)
    // 서버측 _is_allowed_alias_char와 동일한 규칙 유지
    return /^[\x20-\x7E가-힣ᄀ-ᅞᅡ-ᇿ㄰-ㅣㅥ-㆏]*$/.test(s);
}
```

- [ ] **Step 2: 호출부(`activateAliasEdit` 내부)와 경고 문구 갱신**

`app/static/js/criteria_list.js`의 354~358행 (validation block)을 찾아 다음으로 교체한다:

```javascript
        const v = input.value.trim();
        if (v && !isAllowedAliasChars(v)) {
            alert('표시명에는 영문/숫자/기호 또는 한글만 입력할 수 있습니다.');
            restore(original);
            return;
        }
```

- [ ] **Step 3: 개발 서버에서 수동 스모크 테스트**

```bash
# 별도 터미널에서
uv run uvicorn app.main:app --reload --port 8000
```

브라우저로 `http://localhost:8000/admin/criteria` 접속 후 관리자 로그인 → "클라우드 Store 문서" 표에서 임의의 alias 셀을 클릭 → `수학 평가기준` 입력 후 Enter → 셀이 `수학 평가기준`으로 갱신되는지 확인. 페이지 새로고침 후에도 값이 유지되는지 확인. 이어서 `🎯` 같은 이모지를 시도 → 클라이언트 alert가 출력되는지 확인.

- [ ] **Step 4: 커밋**

```bash
git add app/static/js/criteria_list.js
git commit -m "feat(criteria-ui): allow Hangul in inline alias editor

Mirror server-side relaxation: accept ASCII printable + Hangul ranges.
Update alert copy."
```

---

## Task 6: 사용자 노출 문서·주석 정리

**Files:**
- Modify: `app/models/criteria.py:84-88`
- Modify: `app/routers/admin/criteria.py:644-651`

- [ ] **Step 1: 모델 컬럼 comment 갱신**

`app/models/criteria.py`의 84~88행을 다음으로 교체한다:

```python
    display_alias = Column(
        String(255),
        nullable=True,
        comment=(
            "관리자 편집용 표시명. ASCII printable 또는 한글 허용 "
            "(NULL이면 title을 fallback)"
        ),
    )
```

- [ ] **Step 2: 라우터 엔드포인트 description 갱신**

`app/routers/admin/criteria.py`의 644~651행을 다음으로 교체한다:

```python
@router.patch(
    "/{criteria_id}/display-alias",
    response_model=UpdateDisplayAliasResponse,
    summary="평가기준 표시명(alias) 업데이트",
    description=(
        "DB-only 업데이트. 클라우드 재업로드 없음. "
        "ASCII printable 또는 한글 문자만 허용. "
        "NULL/빈 문자열로 보내면 alias 제거."
    ),
)
```

- [ ] **Step 3: 커밋**

```bash
git add app/models/criteria.py app/routers/admin/criteria.py
git commit -m "docs(criteria): update display_alias comments to reflect Hangul support"
```

---

## Task 7: 전체 회귀 검증 + 수동 점검

- [ ] **Step 1: 관련 테스트 일괄 실행**

Run:
```bash
uv run pytest \
  tests/test_criteria_display_alias_schema.py \
  tests/test_admin_criteria_alias_router.py \
  tests/test_criteria_repository_alias.py \
  tests/test_qna_citation_alias.py \
  tests/test_criteria_list_template.py \
  tests/test_criteria_detail_template.py \
  tests/test_user_dashboard_criteria_source.py \
  -v
```

Expected: 모든 테스트 PASS. 한 건이라도 실패하면 그 자리에서 멈추고 진단 (해당 테스트가 `display_alias`의 ASCII-only 가정을 더 깊은 곳에서 사용 중일 가능성 확인).

- [ ] **Step 2: 변경되지 않은 영역 회귀 보호 — Pydantic v2 마이그레이션 직후이므로 전체 테스트도 확인**

Run: `uv run pytest -q`
Expected: 전체 PASS.

- [ ] **Step 3: 수동 통합 시나리오**

1. `uv run uvicorn app.main:app --reload` 로 서버 기동
2. 관리자 계정 로그인 → `/admin/criteria` 접속
3. 한글 alias `수학 6학년 평가기준` 입력 후 저장 → 페이지 새로고침 시 유지 확인
4. 같은 행의 "평가기준 제목" 표시도 동일 한글이 표 좌측 카드의 `표시명:` 영역에 나오는지 확인
5. (선택) QnA 질의 1회 실행 → citation에 한글 alias가 노출되는지 확인 (`tests/test_qna_citation_alias.py`가 단위 수준에서 이미 보호)

- [ ] **Step 4: 최종 정리 커밋 (필요 시)**

위 Task 1–6에서 별도 커밋이 이미 4건 생성되었다. 변경 사항이 없다면 본 단계는 skip.

```bash
git status   # 깨끗한 작업트리 확인
git log --oneline -6   # 새 커밋 4건 + 이전 HEAD가 보여야 함
```

---

## Self-Review

- **Spec coverage:** "ASCII에 더해 한글도 허용" → Task 2가 검증기를 갱신, Task 5가 동일 규칙을 JS에 반영, Task 1·3·4가 테스트로 보장. ✓
- **Placeholder scan:** "TBD", "later", "handle edge cases", "similar to" 사용 없음. 모든 코드 블록이 실제 코드로 채워져 있다. ✓
- **Type consistency:** 새 헬퍼 `_is_allowed_alias_char`는 Task 2에서 정의되어 같은 파일 내 `validate_alias`에서만 호출. JS의 `isAllowedAliasChars`는 Task 5의 정의와 호출이 동일 파일 내 일관. ✓
- **No new files:** `app/static/js/criteria_list.js` 등 기존 파일만 수정. ✓

## Risk Notes

- **MySQL char 길이**: 운영 DB가 utf8mb4 + VARCHAR(255)이면 255 한글 문자(최대 1020 bytes)도 안전. 만약 latin1이라면 문제가 되지만, `display_alias` 컬럼 자체가 한글 저장 의도로 추가된 최근 컬럼이므로 환경별 charset 점검은 별도 운영 이슈. 본 계획 범위는 어플리케이션 검증 로직에 한정.
- **기존 ASCII-only 데이터 호환성**: 신규 정책은 기존 ASCII-only 데이터를 100% 포함하는 superset이므로 마이그레이션 불필요.
- **클라우드 Store와의 동기화**: `display_alias`는 DB-only(라우터 설명 참고) — Gemini Vector Store 측 메타데이터를 건드리지 않으므로 클라우드 사이드 영향 없음.
