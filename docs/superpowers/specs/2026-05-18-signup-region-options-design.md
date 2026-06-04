> **⚠️ SUPERSEDED by #91** — This spec designed the role/region/career signup
> options which have been **removed**. The platform now uses user-chosen `user_id` +
> password login with no role, region, or career fields.
> See `docs/plans/2026-06-04-issue-91-id-auth-email-removal.md`.

# 가입 폼 교사/예비교사 지역 옵션 정비

- 작성일: 2026-05-18
- 작성자: DomineYH (with Claude)
- 상태: 설계 승인됨, 구현 대기

## 배경

`/auth/register` 가입 폼에서 사용자는 `교사` / `예비교사` 중 하나를
선택한다. 각 역할은 select 드롭다운으로 지역(또는 대학) 목록을 노출
하며, 이는 `app/constants.py`의 `TEACHER_REGIONS` /
`PRESERVICE_UNIVERSITY_REGIONS`에서 정의된다.

현재 목록에는 다음 두 가지 미흡한 점이 있다.

1. 두 역할 모두 사용자가 직접 분류 불가능한 경우 선택할 옵션이 없다
   (드롭다운에서 강제로 화이트리스트 값 선택 필요).
2. 예비교사 목록은 시·도 이름 일부 + `한국교원대`가 혼재되어 있어
   "교육대학교" 단위로 정렬되지 않는다. 사용자가 자신이 다니는 학교
   이름과 매핑하기 어렵다.

## 목표

- 교사: 기존 17개 시·도 끝에 `기타` 추가.
- 예비교사: 기존 11개 항목을 "교육대학교" 단위로 라벨링.
  - `한국교원대` 제거 (해당 케이스는 `기타`로 흡수).
  - 나머지 10개 지역명에 `교대` 접미사를 붙임.
  - 끝에 `기타` 추가.
- 기존 DB에 저장된 예비교사 region 값을 새 값으로 자동 변환.

## 비목표 (Out of Scope)

- `기타` 선택 시 자유 입력 텍스트 필드 노출/저장. 본 변경에서는 `기타`
  문자열만 저장한다.
- 관리자 콘솔 통계/필터 UI 개편. region 화이트리스트만 바뀌므로 기존
  필터는 그대로 동작한다.
- 교사 역할의 지역명 자체 변경(시·도명은 그대로).

## 상세 설계

### 1. `app/constants.py`

```python
TEACHER_REGIONS = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "충북", "충남", "전북", "전남", "경북", "경남", "강원", "제주",
    "기타",
]

PRESERVICE_UNIVERSITY_REGIONS = [
    "서울교대", "경인교대", "공주교대", "광주교대", "대구교대",
    "부산교대", "전주교대", "진주교대", "청주교대", "춘천교대",
    "기타",
]
```

`USER_AUTH_ROLES`, `SESSION_USER_TYPE_LABELS` 등 그 외 상수는 변경 없음.

### 2. 스키마 (`app/schemas/users.py`)

기존 `validate_teacher_region` / `validate_university_region`는
constants 화이트리스트를 그대로 사용하므로 코드 변경 불필요.
검증 메시지("허용되지 않는 …")도 그대로.

### 3. 라우터 (`app/routers/auth.py`)

컨텍스트로 constants를 그대로 전달하므로 변경 불필요.

### 4. 템플릿 (`app/templates/user/register.html`)

`{% for region in preservice_university_regions %}` 루프를 그대로
사용 — DB/라벨이 동일한 값이므로 추가 매핑 테이블 불필요.

### 5. 데이터 마이그레이션

새 파일: `app/migrations/preservice_region_kyodae_rename.py`

```python
PRESERVICE_REGION_RENAME = {
    "서울": "서울교대",
    "경인": "경인교대",
    "공주": "공주교대",
    "광주": "광주교대",
    "대구": "대구교대",
    "부산": "부산교대",
    "전주": "전주교대",
    "진주": "진주교대",
    "청주": "청주교대",
    "춘천": "춘천교대",
    "한국교원대": "기타",
}
```

- 비동기 함수 `rename_preservice_university_regions(engine)`로 정의.
- `user_profiles` 테이블 존재 여부를 inspect로 확인 후 진행.
- 멱등(idempotent): 이미 새 값("…교대" 또는 "기타")인 행은 건너뜀
  (WHERE 절로 자연스럽게 필터).
- 갱신된 행 수를 반환하고 로그 출력.

`app/main.py`의 startup 마이그레이션 시퀀스에 호출 추가
(`rename_chat_session_in_service_teacher_label` 호출 직후 부근).

### 6. 테스트

- `tests/test_constants_region_options.py` (신규): TEACHER_REGIONS /
  PRESERVICE_UNIVERSITY_REGIONS의 마지막 원소가 `기타`이고 예비교사
  목록에 `한국교원대`가 없으며 모든 비-`기타` 항목이 `교대`로 끝남을
  검증.
- `tests/test_user_email_password_auth.py` 등 가입 검증 흐름이 새 값
  ("서울교대", "기타")을 통과시키고, 기존 값("서울", "한국교원대")은
  ValueError를 일으키는지 확인.
- `tests/test_preservice_region_kyodae_rename.py` (신규):
  - 마이그레이션이 옛 값을 새 값으로 갱신.
  - 멱등성: 두 번 호출해도 두 번째는 0행.
  - 알 수 없는 값은 그대로 둠.

### 7. 영향 받는 부수 코드

- `app/services/admin_export_service.py:162-164`: region 필터링.
  값 화이트리스트가 바뀌면 관리자가 필터에 사용하는 값도 새 값을 입력
  해야 한다 — 현재 입력은 자유 텍스트이므로 코드 변경 없이 동작.
- `app/utils/admin_export_naming.py:83-85`: 값을 그대로 반환. 변경 없음.

## 위험 및 완화

- **기존 DB의 `대구` 사용자**: 마이그레이션이 자동으로 `대구교대`로 갱신.
- **재실행 안전성**: WHERE 절로 옛 값만 타깃하므로 멱등.
- **`기타` 충돌**: 교사·예비교사 모두 `기타`를 가지지만, 화이트리스트
  검증은 역할별로 분리되어 있어 교차 오염 없음. 관리자 export는 role
  컬럼과 함께 묶이므로 통계상 분리 가능.

## 변경 영향 범위 요약

- `app/constants.py` (수정)
- `app/migrations/preservice_region_kyodae_rename.py` (신규)
- `app/main.py` (마이그레이션 호출 추가)
- `tests/` 3개 파일 (신규 2개 + 기존 1개 보강)

## 후속 작업 (별도 이슈)

- `기타` 선택 시 자유 입력란 노출이 필요하면 추가 스펙으로 분리.
- 관리자 export region 필터를 화이트리스트 기반 드롭다운으로 전환.
