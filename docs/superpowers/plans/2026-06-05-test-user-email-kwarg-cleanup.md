# 테스트 `User(email=...)` stale kwarg 정리 Implementation Plan (이슈 #100)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** auth 리팩터(#90~#93)로 제거된 `User.email` 컬럼을 여전히 전달하는 테스트의 `User(email=...)` 키워드 인자 47곳을 포맷 보존 방식으로 제거하여 `TypeError: 'email' is an invalid keyword argument for User`를 해소한다.

**Architecture:** Python `ast`로 `User(...)` 호출의 `email` 키워드 위치를 정확히 찾아, 단독 라인이면 라인 통째, 인라인이면 토큰+인접 콤마만 제거한다(`libcst` 미설치라 ast 위치정보 사용). 변환 스크립트는 컴파일 검증 + `User()` 내 `email` 잔존 0 검증을 내장한다.

**Tech Stack:** Python ast, pytest, git.

---

## 관련 사실 / 제약

- 근본 원인: `app/models/users.py`의 `User`에 `email` 컬럼 없음(#91에서 제거). 테스트만 미갱신.
- 범위: `User(...)` 호출에 `email=`를 넘기는 **18개 파일, 47곳** (전부 `tests/` 하위, 프로덕션 코드엔 없음 — repo-wide 확인됨).
- 테스트 인터프리터: `.venv/bin/python -m pytest` (bare `python` 없음).
- `libcst` 미설치 → 의존성 추가 대신 표준 `ast` 위치정보(파이썬 3.9+의 `Constant.end_lineno/col` 등)로 처리.
- **범위 밖(별도 후속):** 일부 파일은 `email`과 무관한 collection ImportError를 별도로 가짐 — `app.models.documents` 부재(`test_frontend_flow.py`, `test_lifecycle.py`, `integration/test_qna_api.py`, `integration/test_criteria_pipeline_evaluation.py`), `app.routers.admin.criteria_delete` 부재(`unit/test_criteria_delete_logic.py`). 이들은 email 수정 후에도 collect 불가. email 인자 제거 자체는 옳으므로 적용하되, 통과는 기대하지 않는다.
- `tests/unit/test_lessonplan_analysis_integration.py:24`의 `user.email = "..."`(속성 대입)은 `User(email=)` 패턴이 아니며 에러를 유발하지 않음 → 범위 밖, 손대지 않음.

## 변경 전 baseline (측정값)

collect 가능한 11개 affected 파일 기준:
```
.venv/bin/python -m pytest -q tests/e2e/test_admin_criteria_sync_badge_smoke.py \
  tests/services/test_lessonplan_analysis_service_dedup.py tests/test_admin_deletion_service.py \
  tests/test_admin_login_bruteforce.py tests/test_admin_login_timing_sidechannel.py \
  tests/test_dashboard_upload_creates_upload_row.py tests/test_dashboard_view.py \
  tests/test_lessonplan_analysis_router_429.py tests/test_lessonplan_uploads_model.py \
  tests/test_report_viewer.py tests/test_user_history_endpoints.py
```
→ **23 failed / 10 passed / 55 errors**, `email ... invalid keyword argument` **83건**.

## File Structure

- 변환기 `strip_user_email_kwarg.py`는 **일회성 도구로 `/tmp`에만 두고 레포에 커밋하지 않음**(YAGNI). PR에는 테스트 변경만 담는다. 재현 방법은 PR 본문에 기록.
- Modify: 아래 18개 테스트 파일 (각각 `User(email=...)` 인자만 제거):
  `tests/e2e/conftest.py`, `tests/e2e/test_admin_criteria_sync_badge_smoke.py`,
  `tests/integration/test_criteria_pipeline_evaluation.py`, `tests/integration/test_qna_api.py`,
  `tests/services/test_lessonplan_analysis_service_dedup.py`, `tests/test_admin_deletion_service.py`,
  `tests/test_admin_login_bruteforce.py`, `tests/test_admin_login_timing_sidechannel.py`,
  `tests/test_dashboard_upload_creates_upload_row.py`, `tests/test_dashboard_view.py`,
  `tests/test_frontend_flow.py`, `tests/test_lessonplan_analysis_router_429.py`,
  `tests/test_lessonplan_uploads_model.py`, `tests/test_lifecycle.py`, `tests/test_report_viewer.py`,
  `tests/test_user_history_endpoints.py`, `tests/unit/test_criteria_delete_logic.py`,
  `tests/verify_upload_handler.py`.

---

## Task 1: 변환 도구 준비 + dry-run (커밋하지 않음)

**Files:**
- 임시: `/tmp/strip_user_email_kwarg.py` (레포에 커밋하지 않는 일회성 도구)

- [ ] **Step 1: 스크립트 작성** — 아래 내용 그대로 `/tmp/strip_user_email_kwarg.py`에 생성(ast 위치정보 기반, 컴파일+잔존검증 내장):

```python
"""User(...) 호출에서 email= 키워드 인자만 포맷 보존 제거 (이슈 #100).
- email 인자가 한 줄을 단독 점유하면 그 줄 통째 삭제(개행 포함)
- 인라인이면 토큰+인접 콤마만 제거
사용: python /tmp/strip_user_email_kwarg.py [--apply] <file...>"""
import ast, sys, re, difflib

def process(src):
    tree = ast.parse(src)
    idx = [0]
    for ln in src.split('\n'):
        idx.append(idx[-1] + len(ln) + 1)
    def off(lineno, col): return idx[lineno - 1] + col
    cuts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'User':
            for kw in node.keywords:
                if kw.arg != 'email':
                    continue
                ve = off(kw.value.end_lineno, kw.value.end_col_offset)
                vs = off(kw.value.lineno, kw.value.col_offset)
                j = vs - 1
                while j >= 0 and src[j] in ' \t': j -= 1
                assert src[j] == '='
                j -= 1
                while j >= 0 and src[j] in ' \t': j -= 1
                name_end = j + 1; k = j
                while k >= 0 and (src[k].isalnum() or src[k] == '_'): k -= 1
                name_start = k + 1
                assert src[name_start:name_end] == 'email', src[name_start:name_end]
                e = ve
                while e < len(src) and src[e] in ' \t': e += 1
                has_tc = e < len(src) and src[e] == ','
                line_start = src.rfind('\n', 0, name_start) + 1
                line_end = src.find('\n', ve)
                if line_end == -1: line_end = len(src)
                tok_end_for_check = (e + 1) if has_tc else ve
                before = src[line_start:name_start]
                after = src[tok_end_for_check:line_end]
                if before.strip() == '' and after.strip() == '':
                    cuts.append((line_start, line_end + 1))
                elif has_tc:
                    f = e + 1
                    while f < len(src) and src[f] in ' \t': f += 1
                    cuts.append((name_start, f))
                else:
                    b = name_start - 1
                    while b >= 0 and src[b] in ' \t': b -= 1
                    cut_s = b if (b >= 0 and src[b] == ',') else name_start
                    cuts.append((cut_s, ve))
    cuts.sort(reverse=True)
    out = src
    for s, e in cuts:
        out = out[:s] + out[e:]
    return out, len(cuts)

def main():
    args = sys.argv[1:]; apply = '--apply' in args
    files = [a for a in args if a != '--apply']; total = 0
    for f in files:
        src = open(f, encoding='utf-8').read()
        new, n = process(src); total += n
        if n == 0:
            continue
        compile(new, f, 'exec')
        for m in re.finditer(r"\bUser\((.*?)\)", new, re.DOTALL):
            assert not re.search(r"\bemail\s*=", m.group(1)), f"residual email in {f}"
        if apply:
            open(f, 'w', encoding='utf-8').write(new)
            print(f"APPLIED {n:>2}  {f}")
        else:
            print(f"--- {f} ({n}) ---")
            for d in list(difflib.unified_diff(src.split('\n'), new.split('\n'), lineterm='', n=0))[2:]:
                print("  ", d)
    print(("APPLIED " if apply else "DRYRUN ") + f"total: {total}")

if __name__ == '__main__':
    main()
```

- [ ] **Step 2: dry-run으로 전체 미리보기**

Run:
```bash
.venv/bin/python /tmp/strip_user_email_kwarg.py <18개 파일>
```
Expected: `DRYRUN total: 47`, 그리고 각 diff가 오직 `email=...` 토큰/라인만 제거(부수 변경 없음).

---

## Task 2: 18개 파일에 변환 적용

**Files:** 위 File Structure의 18개 테스트 파일 (Modify)

- [ ] **Step 1: 적용**

Run:
```bash
.venv/bin/python /tmp/strip_user_email_kwarg.py --apply \
  tests/e2e/conftest.py tests/e2e/test_admin_criteria_sync_badge_smoke.py \
  tests/integration/test_criteria_pipeline_evaluation.py tests/integration/test_qna_api.py \
  tests/services/test_lessonplan_analysis_service_dedup.py tests/test_admin_deletion_service.py \
  tests/test_admin_login_bruteforce.py tests/test_admin_login_timing_sidechannel.py \
  tests/test_dashboard_upload_creates_upload_row.py tests/test_dashboard_view.py \
  tests/test_frontend_flow.py tests/test_lessonplan_analysis_router_429.py \
  tests/test_lessonplan_uploads_model.py tests/test_lifecycle.py tests/test_report_viewer.py \
  tests/test_user_history_endpoints.py tests/unit/test_criteria_delete_logic.py \
  tests/verify_upload_handler.py
```
Expected: 각 파일 `APPLIED n  <file>` 출력, 마지막 `APPLIED total: 47`.

- [ ] **Step 2: repo-wide 잔존 0 검증**

Run:
```bash
.venv/bin/python - <<'PY'
import re, pathlib
n = 0
for p in pathlib.Path(".").rglob("*.py"):
    if any(s in p.parts for s in (".venv", ".uv-cache", "__pycache__")): continue
    t = p.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"\bUser\((.*?)\)", t, re.DOTALL):
        if re.search(r"\bemail\s*=", m.group(1)): n += 1; print("RESIDUAL", p)
print("residual User(email=) =", n)
PY
```
Expected: `residual User(email=) = 0`.

- [ ] **Step 3: 변경 diff 육안 검토** — 부수 변경(무관한 빈 줄 삭제 등)이 없는지 확인.

Run: `git diff --stat && git diff | grep -E "^[-+]" | grep -viE "email" | grep -vE "^(\+\+\+|---)" | head`
Expected: `email` 무관 변경 라인 없음(빈 출력에 가까움; 콤마 정리로 인한 동일 라인 치환만 존재).

---

## Task 3: 검증 (email TypeError 0건 + 신규 실패 0건)

**Files:** 없음 (검증 전용)

- [ ] **Step 1: collect-OK 11개 파일 재실행 (after)**

Run:
```bash
.venv/bin/python -m pytest -q \
  tests/e2e/test_admin_criteria_sync_badge_smoke.py \
  tests/services/test_lessonplan_analysis_service_dedup.py tests/test_admin_deletion_service.py \
  tests/test_admin_login_bruteforce.py tests/test_admin_login_timing_sidechannel.py \
  tests/test_dashboard_upload_creates_upload_row.py tests/test_dashboard_view.py \
  tests/test_lessonplan_analysis_router_429.py tests/test_lessonplan_uploads_model.py \
  tests/test_report_viewer.py tests/test_user_history_endpoints.py 2>&1 | tee /tmp/email_after.txt | tail -1
grep -c "is an invalid keyword argument for User" /tmp/email_after.txt
```
Expected: email TypeError **0건**. 통과 수가 baseline(10 passed) 대비 크게 증가하고 email발 error(55개 중 다수) 소멸. 잔존 실패가 있으면 email 무관 사유인지 개별 확인.

- [ ] **Step 2: 잔존 실패 원인 분류** — `email_after.txt`에서 FAILED/ERROR 항목을 보고, email과 무관한 pre-existing 사유(예: 외부 모킹, DB 제약)인지 확인하여 PR 본문에 명시.

Run: `grep -E "FAILED|ERROR" /tmp/email_after.txt | head -40`
Expected: 표시되는 항목 중 `email` 사유 0건.

- [ ] **Step 3: 앱 import 무결성 + 변환 스크립트 자체 점검**

Run: `.venv/bin/python -c "import app.main; print('app.main OK')"`
Expected: `app.main OK`.

- [ ] **Step 4: 커밋 (18개 파일)**

```bash
git add tests/
git commit -m "test: User(email=) stale kwarg 47곳 제거 (#100)

auth email 제거(#91) 이후 남아 있던 테스트의 User(email=...) 인자를
ast 기반 변환으로 일괄 제거하여 TypeError 해소."
```

---

## Self-Review 메모

- 이슈 #100 범위(47곳 email kwarg) 전부 Task 2가 커버. collection ImportError(별도 사유)는 범위 밖으로 명시.
- 변환 스크립트는 placeholder 없이 완전한 코드. dry-run으로 47건/부수변경 0 사전 검증 완료.
- 커밋 분리: 스크립트(Task1) / 적용(Task3 Step4). 모든 커밋이 collect 가능한 상태 유지(테스트 파일 문법 정상).
