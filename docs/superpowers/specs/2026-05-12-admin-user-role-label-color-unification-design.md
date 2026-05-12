# 관리자 사용자 관리 — 라벨 통일 및 색상 일관성 설계 문서

- **작성일:** 2026-05-12
- **작성자:** Claude (Opus 4.7) — 브레인스토밍 세션 기반
- **상태:** Draft — 사용자 검토 대기
- **계획 작성:** Opus
- **구현(코딩):** Sonnet (별도 세션)

## 1. 배경

`/admin/users` 화면에는 두 종류의 사용자 분류 라벨이 존재한다.

| # | 영역 | 라벨 출처 | 표시되는 값 |
|---|---|---|---|
| 1 | 사용자 계정 목록 — 역할 컬럼 | `UserProfile.role` (`teacher` / `preservice_teacher`) → `auth.py` 번역 맵 | `교사` / `예비교사` |
| 2 | 세션 목록 — 세션 유형 컬럼 | `ChatSession.user_type` (analytics segment) | `1학년` / `2학년` / `3학년` / `4학년` / `현직교사` |

문제점:

1. **라벨 불일치** — 같은 in-service 교사를 두 영역에서 `교사`(역할)와 `현직교사`(세션 유형)로 다르게 부른다. 관리자에게 혼란을 준다.
2. **색상 불일치** — 같은 사용자 그룹이 두 영역에서 다른 색으로 표시된다.
   - 역할 `교사` = emerald, 세션 유형 `현직교사` = red
   - 역할 `예비교사` = indigo, 세션 유형 `1~4학년` = blue/green/yellow/purple (모두 다른 색)

## 2. 목표

1. 세션 유형 라벨 `현직교사`를 `교사`로 통일한다. (역할 라벨과 동일하게)
2. 역할 컬럼의 색상과 세션 유형 컬럼의 색상이 같은 사용자 그룹을 표시할 때 시각적으로 일관되도록 한다.
   - 교사(역할 + 세션 유형) → 동일한 단일 색
   - 예비교사(역할) + 1~4학년(세션 유형) → 동일 계열의 색
3. 기존 DB에 저장된 `현직교사` 값을 마이그레이션으로 `교사`로 일괄 갱신한다.

## 3. 비목표 (Out of scope)

- `UserProfile.role` 코드값(`teacher`, `preservice_teacher`) 변경
- 회원가입/프로필 폼의 역할 선택 UI 변경
- 신규 라벨/색상 추가
- 사용자 측 화면(`templates/user/*`)의 색상 변경

## 4. 결정 사항 (브레인스토밍 합의 내용)

| 항목 | 결정 |
|---|---|
| 라벨 변경 범위 | 세션 유형 `현직교사` → `교사` (역할 라벨 `교사`는 이미 사용 중이라 변경 없음) |
| DB 처리 | 신규 startup-time 멱등 마이그레이션 헬퍼로 `chat_sessions.user_type='현직교사'` → `'교사'` 일괄 UPDATE (이 프로젝트는 Alembic이 아닌 `app/migrations/*` 헬퍼 패턴을 사용) |
| 교사 색상 | red 계열로 통일 (`bg-red-100 text-red-800`) — 역할/세션 유형 모두 |
| 예비교사 색상 | 현행 유지 (`bg-indigo-100 text-indigo-800`) |
| 1~4학년 색상 | indigo 계열 4단계 (연한 → 진한 순으로) |
| 작업 분담 | 계획: Opus / 구현(코딩): Sonnet |

## 5. 변경 사항

### 5.1 라벨 변경

| 파일 | 라인(현재) | Before | After |
|---|---|---|---|
| `app/constants.py` | 8 | `"현직교사"` (in `SESSION_USER_TYPE_LABELS`) | `"교사"` |
| `app/templates/admin/admin_users.html` | 95 | `<option value="현직교사">현직교사</option>` | `<option value="교사">교사</option>` |
| `app/routers/qna.py` | 93 | `return "현직교사"` (profile_role == "teacher") | `return "교사"` |
| `app/routers/qna.py` | 102 | `return "현직교사"` (nickname == "teacher") | `return "교사"` |
| `app/models/chat_sessions.py` | 58 | `"(1학년, 2학년, 3학년, 4학년, 현직교사)"` | `"(1학년, 2학년, 3학년, 4학년, 교사)"` |
| `tests/test_user_history_endpoints.py` | 86 | `user_type="현직교사"` | `user_type="교사"` |

### 5.2 색상 매핑 변경

`app/templates/admin/admin_users.html` 의 `getBadgeClass` 함수 (현재 184~197 라인) 매핑을 아래와 같이 변경한다.

| 키 | Before | After |
|---|---|---|
| `1학년` | `bg-blue-100 text-blue-800` | `bg-indigo-50 text-indigo-700` |
| `2학년` | `bg-green-100 text-green-800` | `bg-indigo-100 text-indigo-800` |
| `3학년` | `bg-yellow-100 text-yellow-800` | `bg-indigo-200 text-indigo-900` |
| `4학년` | `bg-purple-100 text-purple-800` | `bg-indigo-300 text-indigo-900` |
| `현직교사` | `bg-red-100 text-red-800` | (키 삭제 — 라벨이 더 이상 존재하지 않음) |
| `교사` | `bg-emerald-100 text-emerald-800` | `bg-red-100 text-red-800` |
| `teacher` | `bg-emerald-100 text-emerald-800` | `bg-red-100 text-red-800` |
| `예비교사` | `bg-indigo-100 text-indigo-800` | (유지) |
| `preservice_teacher` | `bg-indigo-100 text-indigo-800` | (유지) |

**결과 가시화:**

- 교사(역할 + 세션 유형) = red
- 예비교사(역할) = indigo-100
- 1학년 = indigo-50, 2학년 = indigo-100, 3학년 = indigo-200, 4학년 = indigo-300
  (연 → 진으로 학년 상승 직관성 부여)

### 5.3 DB 마이그레이션 — startup-time 멱등 헬퍼

이 프로젝트는 Alembic이 아닌, `app/migrations/*` 아래의 멱등 헬퍼를 `app/main.py` startup에서 호출하는 패턴을 사용한다 (`ensure_criteria_file_path_column`, `ensure_users_lockout_columns` 등 참조).

#### 5.3.1 신규 헬퍼 파일

`app/migrations/chat_sessions_user_type_rename.py` (가칭) 신규 추가:

```python
"""
chat_sessions.user_type 라벨 정규화: '현직교사' → '교사'
"""
from __future__ import annotations

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def rename_chat_session_in_service_teacher_label(
    engine: AsyncEngine,
) -> int:
    """
    chat_sessions.user_type의 '현직교사' 레코드를 '교사'로 일괄 갱신.

    Returns:
        갱신된 행 수. 멱등이므로 두 번째 호출부터는 0.
    """
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE chat_sessions "
                "SET user_type = '교사' "
                "WHERE user_type = '현직교사'"
            )
        )
        updated = result.rowcount or 0
        if updated:
            logger.info(
                "chat_sessions.user_type '현직교사' → '교사' "
                "갱신 행 수: %d", updated,
            )
        return updated
```

#### 5.3.2 등록

- `app/migrations/__init__.py` 의 `__all__` 및 import 에 함수 추가.
- `app/main.py` 의 startup 보정 블록(현재 `ensure_*` 호출이 있는 영역, 약 191~207 라인)에 호출 추가.

#### 5.3.3 멱등성

- `WHERE user_type = '현직교사'` 조건이 0 행 매치 시 UPDATE는 no-op.
- 따라서 매 startup 마다 호출되어도 안전.

#### 5.3.4 롤백 전략

이 마이그레이션은 별도 다운그레이드 함수를 제공하지 않는다(헬퍼 패턴의 일반 관행). 만약 롤백이 필요하면 임시로 다음 SQL을 실행한다:

```sql
UPDATE chat_sessions SET user_type = '현직교사' WHERE user_type = '교사';
```

단, 라벨 통일 이후 신규 입력된 `교사` 값과 구분이 불가능하므로 실행 시점에 한해서만 안전.

## 6. 비고: `app/routers/auth.py` 역할 라벨

`auth.py:62-63`에는 다음 매핑이 이미 존재한다.

```python
"teacher": "교사",
"preservice_teacher": "예비교사",
```

이 매핑은 변경하지 않는다(역할 라벨은 이미 `교사`). 즉 5.1 라벨 변경 작업은 **세션 유형 영역**에만 적용된다.

## 7. 검증 기준

1. 기존 테스트 스위트가 라벨 변경 반영 후 통과한다.
2. `/admin/users` 화면에서:
   - 필터 셀렉트에 `교사` 옵션이 보이고 `현직교사`는 없다.
   - 역할 컬럼의 `교사` / `예비교사` 배지가 각각 red / indigo로 보인다.
   - 세션 유형 컬럼의 `교사` 배지가 red로, 1~4학년 배지가 indigo 4단계로 보인다.
3. 앱 startup 후 다음 쿼리 결과가 0이어야 한다.

   ```sql
   SELECT COUNT(*) FROM chat_sessions WHERE user_type = '현직교사';
   ```

4. 신규 세션 생성 시 `ChatSession.user_type`에 `교사`가 기록된다(`qna.py` 변경 반영).

5. 마이그레이션 헬퍼를 두 번째로 호출했을 때 갱신 행 수가 0이며 에러가 없다 (멱등성).

## 8. 작업 분담

| 단계 | 담당 |
|---|---|
| 브레인스토밍 / 설계(이 문서) | Opus |
| 구현 계획(plan) 작성 | Opus |
| 코드 변경 / 마이그레이션 작성 / 테스트 갱신 / PR | **Sonnet** |
| 코드 리뷰 | (사용자 또는 별도 리뷰 세션) |

구현(코딩) 작업은 별도 세션에서 Sonnet이 plan 문서를 따라 수행한다.

## 9. 영향 범위 / 위험 요소

- **영향 범위**: 관리자 화면(`admin_users.html`), QnA 세션 생성 시 user_type 기록, DB의 기존 chat_sessions 레코드.
- **사용자 측 화면**: 사용자 대시보드/뷰어/리포트 등에는 `현직교사` 표시가 없으므로 영향 없음(grep 확인됨).
- **위험 요소**:
  - 마이그레이션 다운그레이드 시 신규 입력된 `교사` 값을 `현직교사`로 되돌리면, 라벨 통일 이전부터 `교사`로 입력되어 있던 데이터(없을 것으로 보이지만)도 함께 되돌려질 수 있다. 본 컬럼에는 이전에 `교사` 값이 존재하지 않았으므로 실용적으로 안전.
  - 라벨 캐싱(브라우저/CDN): admin 화면은 캐시되지 않으므로 별도 조치 불필요.

## 10. 산출물

- 본 spec 문서 (`docs/superpowers/specs/2026-05-12-admin-user-role-label-color-unification-design.md`)
- 구현 plan 문서 (다음 단계에서 Opus가 `docs/superpowers/plans/` 하위에 작성)
- GitHub issue (작업 분담 / 링크 포함)
- (Sonnet 산출물) 코드 변경 PR
