# Issue #74 — 평가기준 체크박스 즉시 라벨 반영 (Optimistic UI Update) 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Issue:** https://github.com/DomineYH/elp_gemini/issues/74

**Goal:** 평가기준 관리 화면(`/admin/criteria`)에서 사용자가 체크박스를 클릭하면, 백엔드 응답을 기다리지 않고 상태 라벨("비활성"→"활성" 또는 반대)이 **즉시** 갱신되도록 한다. 백엔드 호출이 실패하면 라벨·체크박스를 모두 이전 상태로 롤백한다.

**Architecture:** `app/static/js/criteria_list.js` 의 `.active-checkbox` `change` 핸들러에서, fetch 시작 전에 라벨 텍스트를 먼저 갱신(optimistic update)한다. 백엔드 응답이 실패 시 라벨과 체크박스를 함께 이전 값으로 복원한다. 백엔드(`POST /api/admin/criteria/{stable_id}/activate|deactivate`) 시그니처와 응답 의미는 변경하지 않는다.

**Tech Stack:** Vanilla JS (브라우저), Jinja2 템플릿(읽기 전용), Python 3.11 + pytest (정적 텍스트 회귀 가드).

---

## 사전 컨텍스트 (구현 전 반드시 확인)

- **현재 동작 (버그):**
  - `app/static/js/criteria_list.js:5-24` 의 `change` 핸들러는 `await fetch(...)` 이후에야 `label.textContent` 를 갱신.
  - 백엔드 `_set_status_by_stable_id` 는 `CriteriaAliasMapService.replace()` 를 호출(`app/routers/admin/criteria.py:668`).
  - `replace()` 내부(`app/services/criteria_alias_map_service.py:197-250`)는 Gemini File Search 에 alias-map 새 문서 업로드 → `while not op.done` 폴링(2초 간격, 최대 60초) → 기존 문서 삭제. 정상 케이스에서도 수 초 소요.
  - 결과: 체크박스의 체크 표시는 브라우저 기본 동작으로 즉시 보이지만, 상태 라벨은 백엔드 응답이 돌아올 때까지 변하지 않아 "비활성으로 보이는 채로 멈춰 있음" 으로 인식됨.
- **수정 범위:**
  - Modify: `app/static/js/criteria_list.js` (체크박스 핸들러 한 곳)
  - Modify: `tests/test_criteria_list_js.py` (정적 회귀 가드 추가)
  - 백엔드(라우터/서비스/스키마) 수정 없음.
- **테스트 러너:** `.venv/bin/pytest` (uv venv 사용). 시스템 `python` 없음.
- **회귀 보존 항목:** 기존 테스트 `test_failure_reverts_checkbox_state` (체크박스 롤백) 가 계속 통과해야 함 — 라벨 롤백도 함께 추가.
- **작업 디렉토리:** 저장소 루트 `/home/dominemint/Dev/elp_gemini`.

---

## File Structure

| File | Responsibility | Change Type |
|------|----------------|-------------|
| `app/static/js/criteria_list.js` | Admin 평가기준 목록의 체크박스/별칭/삭제/교체/재동기화 클라이언트 핸들러 | Modify (체크박스 핸들러만) |
| `tests/test_criteria_list_js.py` | `criteria_list.js` 의 핵심 동작에 대한 정적 텍스트 회귀 가드 | Modify (테스트 1개 추가, 1개 보강) |

---

## Task 1: 라벨 롤백을 포함한 회귀 가드 추가 (failing tests 먼저)

**Files:**
- Modify: `tests/test_criteria_list_js.py`

- [ ] **Step 1: 즉시 라벨 갱신 회귀 가드 작성**

`tests/test_criteria_list_js.py` 끝에 다음 테스트를 추가한다. 이 테스트는 라벨이 fetch *이전에* 갱신되는 텍스트 구조를 정적으로 검사한다.

```python
def test_label_updates_optimistically_before_fetch():
    """체크박스 change 시 라벨은 fetch 응답 전에 즉시 갱신되어야 한다.

    근거: 백엔드 alias_map.replace()는 클라우드 업로드 폴링(최대 60초)으로
    느릴 수 있으므로, UI 라벨은 optimistic 업데이트 후 실패 시 롤백한다.
    """
    src = JS_SOURCE.read_text()

    fetch_index = src.find('await fetch(url')
    assert fetch_index != -1, "fetch 호출이 존재해야 한다"

    # 라벨 즉시 갱신은 fetch 호출보다 먼저 등장해야 한다.
    optimistic_index = src.find("label.textContent = wasChecked ? '활성' : '비활성'")
    assert optimistic_index != -1, "라벨 갱신 라인이 존재해야 한다"
    assert optimistic_index < fetch_index, (
        "라벨 갱신은 fetch 호출보다 먼저 실행되어야 한다 (optimistic update)"
    )
```

- [ ] **Step 2: 실패 시 라벨 롤백 회귀 가드 추가 및 기존 보강**

같은 파일의 `test_failure_reverts_checkbox_state` 를 다음과 같이 교체한다. 라벨 롤백이 함께 일어남을 보장한다.

```python
def test_failure_reverts_checkbox_state():
    src = JS_SOURCE.read_text()

    assert "cb.checked = previous" in src
    assert "try {" in src
    assert "} catch" in src
    # 실패 시 라벨도 이전 텍스트로 되돌려야 한다.
    assert "label.textContent = previousLabelText" in src
```

- [ ] **Step 3: 테스트 실행해 실패 확인**

Run: `.venv/bin/pytest tests/test_criteria_list_js.py -v`

Expected:
- `test_label_updates_optimistically_before_fetch` → FAIL (현재는 fetch 후에만 라벨 갱신)
- `test_failure_reverts_checkbox_state` → FAIL (현재 코드에 `previousLabelText` 없음)
- 다른 테스트 → PASS

- [ ] **Step 4: 커밋**

```bash
git add tests/test_criteria_list_js.py
git commit -m "test(criteria-list-js): guard optimistic label update + label rollback"
```

---

## Task 2: `criteria_list.js` 의 체크박스 핸들러를 optimistic update 로 전환

**Files:**
- Modify: `app/static/js/criteria_list.js:5-24`

- [ ] **Step 1: 체크박스 핸들러 교체**

`app/static/js/criteria_list.js` 의 다음 블록(현재 5–24 행)을:

```javascript
  document.querySelectorAll('.active-checkbox').forEach((cb) => {
    cb.addEventListener('change', async () => {
      const sid = cb.value;
      const wasChecked = cb.checked;
      const previous = !wasChecked;
      try {
        const url = wasChecked
          ? `/api/admin/criteria/${sid}/activate`
          : `/api/admin/criteria/${sid}/deactivate`;
        const r = await fetch(url, { method: 'POST' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const row = cb.closest('tr');
        const label = row.querySelector('.status-label');
        if (label) label.textContent = wasChecked ? '활성' : '비활성';
      } catch (err) {
        cb.checked = previous;
        alert(`상태 변경 실패: ${err.message}`);
      }
    });
  });
```

다음으로 교체한다:

```javascript
  document.querySelectorAll('.active-checkbox').forEach((cb) => {
    cb.addEventListener('change', async () => {
      const sid = cb.value;
      const wasChecked = cb.checked;
      const previous = !wasChecked;
      const row = cb.closest('tr');
      const label = row.querySelector('.status-label');
      const previousLabelText = label ? label.textContent : null;
      if (label) label.textContent = wasChecked ? '활성' : '비활성';
      try {
        const url = wasChecked
          ? `/api/admin/criteria/${sid}/activate`
          : `/api/admin/criteria/${sid}/deactivate`;
        const r = await fetch(url, { method: 'POST' });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
      } catch (err) {
        cb.checked = previous;
        if (label) label.textContent = previousLabelText;
        alert(`상태 변경 실패: ${err.message}`);
      }
    });
  });
```

핵심 변경 4가지:
1. `row` / `label` / `previousLabelText` 변수를 try 블록 *밖에서* 캡처.
2. `label.textContent` 갱신을 `await fetch` *이전* 으로 이동(optimistic).
3. `catch` 블록에서 라벨을 `previousLabelText` 로 되돌림(롤백).
4. fetch 성공 경로에서는 라벨을 다시 만지지 않음(이미 갱신됨).

- [ ] **Step 2: Task 1 의 테스트가 통과하는지 확인**

Run: `.venv/bin/pytest tests/test_criteria_list_js.py -v`

Expected: 모든 테스트 PASS (특히 `test_label_updates_optimistically_before_fetch`, `test_failure_reverts_checkbox_state`).

- [ ] **Step 3: 전체 평가기준 관련 테스트 회귀 확인**

Run: `.venv/bin/pytest tests/test_criteria_list_js.py tests/test_criteria_list_template.py tests/test_admin_criteria_activate.py -v`

Expected: 모두 PASS. 기존 활성/비활성 라우터 동작, 템플릿 렌더링은 영향 없음.

- [ ] **Step 4: 수동 스모크 (개발 서버)**

1. `.venv/bin/uvicorn app.main:app --reload` 로 서버 기동.
2. 관리자 계정으로 `/admin/criteria` 접근.
3. 비활성 상태인 평가기준의 체크박스를 클릭 → "활성" 라벨이 **즉시** 표시되는지 확인.
4. 활성 상태인 평가기준 체크 해제 → "비활성" 즉시 표시 확인.
5. (선택) DevTools Network 탭에서 activate/deactivate 요청을 throttle/abort 시켜 실패 케이스 재현 → 라벨이 원래 상태로 롤백되고 alert 가 뜨는지 확인.

- [ ] **Step 5: 커밋**

```bash
git add app/static/js/criteria_list.js
git commit -m "fix(criteria-list): update status label optimistically on checkbox toggle

Backend alias_map.replace() polls Gemini File Search for up to 60s,
which previously delayed the label update until the await resolved.
Move the label flip before fetch and roll back on failure so the
checkbox and label respond immediately."
```

---

## Self-Review

**Spec coverage**
- ✅ "체크박스 체크 시 라벨이 즉시 비활성→활성으로 바뀌어야 함" → Task 2 Step 1 의 `label.textContent` 즉시 갱신.
- ✅ 실패 시 일관성 보존 → Task 2 Step 1 의 라벨 롤백 + 기존 체크박스 롤백 유지.
- ✅ 회귀 가드 → Task 1 의 2개 정적 테스트.

**Placeholder scan**
- 없음. 모든 코드 블록은 실제 코드.

**Type consistency**
- `previousLabelText` 변수명이 plan 전체에서 일관됨(Task 1 테스트, Task 2 구현 모두).
- `label` 은 `row.querySelector('.status-label')` 결과로 nullable 가능성 보존 (`if (label)` 가드 유지).

**범위 외 보류 (의도적)**
- 백엔드 `alias_map.replace()` 자체의 latency 개선(BackgroundTasks, 큐, 비동기 응답)은 **하지 않는다.** Cloud-as-source-of-truth 보장과 별개 설계 영역이므로 본 이슈 범위가 아님.
- 다른 UI(삭제, 별칭 편집 등)의 optimistic 처리는 변경하지 않는다.
