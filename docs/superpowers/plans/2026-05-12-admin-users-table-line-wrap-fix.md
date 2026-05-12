# 관리자 사용자 관리 — 표 셀 세로 줄바꿈 수정 계획

**계획 작성:** Opus 4.7
**대상 페이지:** `/admin/users` (`app/templates/admin/admin_users.html`)
**Goal:** 사용자 계정 목록 / 세션 목록 표의 배지·링크·날짜 셀이 한 글자씩 세로로 적층되는 현상을 제거하고, 좁은 컬럼에서도 가독성이 유지되도록 가로 스크롤이 정상 동작하도록 한다.

---

## 1. 문제 (Symptoms)

스크린샷(2026-05-12 21:26)에서 확인된 시각적 결함:

- `사용자 계정 목록` (상단 표):
  - `예비교사`/`교사` 배지가 한 글자씩 세로로 적층됨
  - `세션 1 · 보고서 0` 활동 셀이 단어 단위로 줄바꿈됨
  - 날짜 `2026. 05. 12. 오전 02:32`가 4~5줄로 나뉨
  - `상세보기` 링크가 `상`/`세`/`보`/`기` 세로 적층
  - 헤더 `지역/대학교지역`, `비밀번호 변경`도 줄바꿈됨
- `세션 목록` (하단 표):
  - `1학년`/`교사` 배지가 세로 적층
  - 날짜·`상세보기`가 동일 증상

---

## 2. 근본 원인 (Root cause)

| 원인 | 위치 | 비고 |
|---|---|---|
| 10개 컬럼을 `max-w-6xl`(1152px) 컨테이너에 끼워 넣음 | `admin_users.html:24` | 셀당 평균 ≈115px |
| `내부 ID` 값 `preservice_teacher_…`이 ≈32자라 폭을 독점, 다른 컬럼이 더 좁아짐 | `admin_users.html:341` (`account.username` 렌더링) | |
| 배지 `<span>`, `상세보기` `<a>`, 날짜·활동 셀에 `whitespace-nowrap` 부재 | `admin_users.html:339-356` (계정 표), `:424-444` (세션 표), `:128-138` 및 `:152-163` (헤더 `<th>`) | admin 템플릿 전체에서 `whitespace-nowrap` grep 0건 |
| 한국어 텍스트는 단어 경계가 없어 좁아진 셀에서 글자 단위로 분리됨 | (브라우저 기본 동작) | |
| `<table>`에 `min-width`가 없어 `overflow-x-auto` 부모 안에서 가로 스크롤이 트리거되지 않고 강제 압축됨 | `admin_users.html:124-125`, `:149-150` | |

---

## 3. 수정 범위 (Scope)

순수 템플릿(HTML/CSS class) 수정만. 라우터/모델/JS 로직/테스트 fixture 변경 없음.

**파일:** `app/templates/admin/admin_users.html`만 수정.

### 3.1 헤더 행 (`<th>`)에 `whitespace-nowrap` 추가

대상 라인:
- 계정 표 헤더: `admin_users.html:128-137` (10개 `<th>`)
- 세션 표 헤더: `admin_users.html:153-162` (10개 `<th>`)

추가 클래스: `whitespace-nowrap` (Tailwind 표준).

### 3.2 데이터 행 셀에 `whitespace-nowrap` 추가

대상 (계정 표, `admin_users.html:338-357`):

| 위치 | 셀 내용 | 조치 |
|---|---|---|
| `:339` | ID `<td>` | `whitespace-nowrap` |
| `:340` | 이메일 `<td>` | `whitespace-nowrap` |
| `:341` | 내부 ID `<td>` | `whitespace-nowrap` + 긴 username 대응으로 `max-w-[200px] truncate` 추가 + `title="{username}"` 속성 부여 (호버 시 전체 값 표시) |
| `:343-346` | 역할 배지 span | span에 `whitespace-nowrap` 추가 |
| `:347` | 지역 셀 | `whitespace-nowrap` |
| `:348` | 경력/학년 셀 | `whitespace-nowrap` |
| `:349-351` | 활동 셀 (`세션 N · 보고서 M`) | `whitespace-nowrap` |
| `:352` | 가입일 셀 | `whitespace-nowrap` |
| `:354` | `상세보기` `<a>` 부모 `<td>` | `whitespace-nowrap` |
| `:356` | 비밀번호 변경 `<td>` | (이미 `min-w-[240px]` 내부 div 존재; `<td>`에 `whitespace-nowrap` 추가) |

대상 (세션 표, `admin_users.html:423-444`):

| 위치 | 셀 내용 | 조치 |
|---|---|---|
| `:424-428` | 세션 유형 배지 span | span에 `whitespace-nowrap` |
| `:429` | 이메일 `<td>` | `whitespace-nowrap` |
| `:430` | 프로필 요약 셀 | `whitespace-nowrap` (또는 `truncate max-w-[260px]` 검토) |
| `:431` | 접속일시 셀 | `whitespace-nowrap` |
| `:432` | 세션 ID 셀 | `whitespace-nowrap` |
| `:433-434` | QnA/보고서 수 | `whitespace-nowrap` |
| `:435` | 마지막 활동 셀 | `whitespace-nowrap` |
| `:436-440` | 상태 배지 span | span에 `whitespace-nowrap` |
| `:441-443` | `상세보기` `<a>` 부모 `<td>` | `whitespace-nowrap` |

### 3.3 표에 `min-width` 부여 (가로 스크롤 활성화)

`overflow-x-auto` 부모(`:124`, `:149`)가 이미 존재하므로 `<table>`에 `min-w-[1200px]`(또는 적절한 px) 추가 시 화면이 좁을 때 자연스러운 가로 스크롤이 발생함.

- `:125` `<table class="w-full">` → `class="w-full min-w-[1200px]"`
- `:150` `<table class="w-full">` → `class="w-full min-w-[1200px]"`

### 3.4 컨테이너 폭 확장 (선택)

`max-w-6xl`(1152px)을 `max-w-7xl`(1280px)로 변경 시 1280px 이상 화면에서는 가로 스크롤 없이 표시 가능. 이는 디자인 결정이므로 별도 단계로 분리하고 본 수정에서는 보수적으로 **유지**한다. (3.3의 `min-width`로 작은 화면에서는 스크롤, 큰 화면에서는 여유 폭 활용)

---

## 4. 수정 단계 (Tasks)

- [ ] **Task 1**: `admin_users.html` 헤더 행 `<th>`에 `whitespace-nowrap` 추가 (계정 표 + 세션 표)
- [ ] **Task 2**: `admin_users.html` 계정 표 데이터 행 `<td>` 및 배지 `<span>`에 `whitespace-nowrap` 추가, 내부 ID 셀에 `max-w-[200px] truncate` + `title` 속성 추가
- [ ] **Task 3**: `admin_users.html` 세션 표 데이터 행 `<td>` 및 배지 `<span>`에 `whitespace-nowrap` 추가
- [ ] **Task 4**: 두 `<table>`에 `min-w-[1200px]` 추가
- [ ] **Task 5**: 로컬 서버 기동(`make run` 또는 `uv run uvicorn app.main:app --reload`) 후 `/admin/users` 시각 검증

---

## 5. 검증 기준 (Acceptance criteria)

`/admin/users` 페이지 (Chromium 기반 브라우저, 화면 폭 ≥ 1280px 기준):

- [ ] 모든 배지(`예비교사`, `교사`, `1학년`~`4학년`, `활성`/`비활성`)가 **한 줄**로 표시되며 한 글자씩 세로 적층되지 않는다.
- [ ] `상세보기` 링크가 **한 줄**로 표시된다.
- [ ] 날짜 셀(`가입일`, `접속일시`, `마지막 활동`)이 **한 줄**로 표시된다.
- [ ] `활동` 셀(`세션 N · 보고서 M`)이 **한 줄**로 표시된다.
- [ ] 헤더 텍스트(`지역/대학교지역`, `비밀번호 변경` 등)가 **한 줄**로 표시된다.
- [ ] 화면 폭이 `<` 1200px인 경우 표 영역에 가로 스크롤이 발생하고, 가로 스크롤 시 모든 셀이 한 줄 상태를 유지한다.
- [ ] `내부 ID` 컬럼: 긴 username이 truncate되어 표 폭을 침범하지 않으며, 호버 시 `title` 툴팁으로 전체 값이 보인다.
- [ ] 다른 페이지(`/admin/dashboard`, `/admin/qna-logs` 등) 레이아웃에 회귀 없음 (해당 파일을 건드리지 않으므로 자명).

---

## 6. 비범위 (Out of scope)

- 다른 admin 페이지(criteria, prompts, qna-logs)는 동일 패턴이 있을 수 있으나, 이슈에서 보고된 것은 `/admin/users`이므로 본 수정에서는 제외한다. 후속 이슈로 분리.
- 응답형(반응형) 모바일 최적화는 별도 작업으로 분리.
- 컨테이너 폭(`max-w-6xl` → `max-w-7xl`) 변경은 디자인 결정이 필요하므로 본 수정에서는 보류.

---

## 7. 위험 / 회귀 (Risks)

- `whitespace-nowrap` + 좁은 화면에서 가로 스크롤이 새로 도입됨 → `min-width: 1200px` 선택으로 의도된 동작. UX상 명백한 개선.
- `truncate`로 인해 `내부 ID` 전체 값을 한 화면에서 못 보는 경우 발생 가능 → `title` 속성으로 호버 시 노출.

---

## 8. PR 메시지 초안

```
fix(admin-users-ui): prevent vertical character stacking in user/session tables

- 모든 데이터 행 셀(`<td>`)과 배지(`<span>`)에 `whitespace-nowrap` 추가
- 두 표에 `min-w-[1200px]` 적용하여 좁은 화면에서 가로 스크롤이 정상 동작
- `내부 ID` 컬럼은 `max-w-[200px] truncate` + `title` 속성으로 폭 폭주 방지
```
