# 설문 게이트 기반 보고서 획득 차단 (Survey-gated report access)

작성일: 2026-06-07
관련: PR #125(인쇄&저장 전용 페이지화)의 후속. 그 변경으로 '인쇄&저장'이 새 탭 전용 페이지를 여는데, 이 경로(및 기존 '내 분석 보고서' 목록)로 **설문 참여를 우회**할 수 있게 되었다.

## 목표

사용자가 분석 보고서를 **영구적으로 획득(전용 페이지 열람·인쇄·PDF 저장·.md 다운로드)** 하려면 **참여 설문을 1회 완료**해야 한다. 서버 측 하드 차단.

## 결정 사항 (사용자 확정)

1. **강제 수준**: 실제 차단(서버 측). 클라이언트 UI 차단만으로는 불충분.
2. **완료 판정**: 자가 확인 클릭. 외부 Google Form 제출은 직접 검증 불가하므로, 사용자가 '설문참여 완료'를 누르면 서버가 완료로 기록(앱 레벨 하드 차단, 폼 제출 자체는 신뢰 기반).
3. **빈도**: 사용자당 1회. `users` 테이블에 완료 시각 1컬럼.
4. **열람 범위**: **방금 분석한 결과는 모달에 1회 표시**(즉시성/동기부여). 그 외 **영구 획득 경로는 전부 차단** — 전용 보고서 페이지 열람, 인쇄, PDF 저장, .md 다운로드, 대시보드 '내 분석 보고서' 목록의 '보고서 보기'.

### 왜 이 범위인가 (핵심 근거)
- 화면에서 볼 수 있는 콘텐츠의 인쇄(Ctrl+P)는 서버가 막을 수 없다. 따라서 '인쇄까지 하드 차단'은 곧 '콘텐츠 전달 차단'을 의미한다.
- 단, 방금 생성한 결과를 1회 보여주는 것은 허용(사용자는 1~3분 기다려 결과를 받음). 이 모달은 일시적 미리보기이며, PR #125에서 모달 전용 인쇄 CSS가 이미 제거되어 모달 Ctrl+P로는 깔끔한 보고서가 나오지 않는다 → 실질적 '획득' 경로가 아님.
- 깔끔한 보고서 획득 경로(전용 페이지/인쇄/다운로드)는 모두 서버에서 `survey_completed` 검사로 차단 → 진짜 하드 차단 달성.

## 데이터 모델

`users` 테이블에 컬럼 추가:
- `survey_completed_at: DateTime, nullable`. `NULL`=미완료, 값 존재=완료 시각.

마이그레이션: `app/migrations/users_survey_completed_column.py`에 `ensure_users_survey_completed_column(engine)` 추가(`ensure_users_lockout_columns` 패턴 동일: inspect→없으면 `ALTER TABLE users ADD COLUMN survey_completed_at DATETIME`). `app/migrations/__init__.py` export + `app/main.py` 시작 시 호출.

`app/models/users.py`: `survey_completed_at = Column(DateTime, nullable=True)` 추가.

## 서버

### 설문 완료 기록 — 신규 라우터 `app/routers/survey.py`
- `POST /api/survey/complete`
  - 로그인 필요(`get_current_user`).
  - `survey_completed_at`이 NULL이면 `func.now()`로 설정 후 커밋. 이미 값이 있으면 그대로(멱등).
  - 응답: `{ "success": true, "survey_completed": true }`.
- `app/main.py`에 `include_router` 등록.

### 보고서 획득 게이트 — `app/routers/lessonplan_analysis.py`
- 헬퍼: `_survey_completed(user) -> bool` = `user.survey_completed_at is not None`.
- `GET /api/lessonplan/reports/{report_id}` (JSON 본문): 미완료면 `403`
  `{ "detail": "설문 참여 후 보고서를 열람할 수 있습니다.", "survey_required": true }`.
- `GET /api/lessonplan/reports/{report_id}/download`: 미완료면 동일 `403`.
- `POST /api/lessonplan/analyze`: **변경 없음**(방금 결과 1회 표시 허용). `report_id`는 PR #125에서 이미 응답에 포함됨.

### 뷰 컨텍스트 — `app/routers/views.py`
- `GET /reports/view/{report_id}`(전용 페이지): 컨텍스트에 `survey_completed`(bool) 추가. 페이지가 게이트/본문 중 무엇을 그릴지 첫 렌더에 바로 결정(실패 fetch 깜빡임 방지). JSON 403은 하드 enforcement로 병행.

## 클라이언트

### 전용 보고서 페이지 `app/templates/user/report_viewer.html`
- 진입 시 `survey_completed`(컨텍스트) 기준:
  - **완료**: 기존대로 `/api/lessonplan/reports/{id}` fetch→렌더, 인쇄 버튼/다운로드/`?print=1` 자동 인쇄 동작.
  - **미완료**: 본문 대신 **설문 게이트** 표시 — 안내 문구 + `[설문 참여하기]`(Google Form 새 탭) + `[설문참여 완료]`. 인쇄 버튼·다운로드 링크·자동 인쇄는 숨김.
    - `[설문참여 완료]` → `POST /api/survey/complete` → 성공 시 게이트 숨기고 본문 fetch→렌더, 인쇄/다운로드 노출(필요 시 `?print=1`이면 인쇄).
- fetch가 403(`survey_required`)을 받으면(컨텍스트와 무관한 안전망) 동일 게이트 표시.

### 대시보드 `app/templates/user/dashboard.html`
- 방금 분석 결과 모달: **변경 없음** — 본문 1회 표시 + `인쇄&저장`(전용 페이지 `?print=1` 열기, PR #125).
  - 미완료 사용자가 `인쇄&저장`을 누르면 전용 페이지가 열리고 거기서 설문 게이트를 만난다(단일 게이트 위치).
- 기존 설문 모달(`#surveyModal`)의 `설문참여 완료`(`completeSurvey()`)를 `POST /api/survey/complete` 호출로 연결(대시보드에서도 완료 가능). `설문참여`는 폼만 새 탭으로 염.
  - 닫기/X의 기존 설문 안내 동작은 유지(미완료 사용자 nudge). 완료 기록이 실제 잠금 해제로 이어지도록만 보강.

## 데이터 흐름 (미완료 사용자)

1. 업로드 → `분석 시작` → 서버가 보고서 생성·저장(`report_id`) → 모달에 본문 1회 표시.
2. `인쇄&저장` 클릭 → `/reports/view/{id}?print=1` 새 탭 → 페이지가 `survey_completed=false` → 설문 게이트 표시(본문/인쇄/다운로드 없음).
3. `설문 참여하기`(폼) 후 `설문참여 완료` → `POST /api/survey/complete` → 서버 기록.
4. 게이트가 본문 fetch(이제 200)→렌더 + 인쇄/다운로드 노출 + (`?print=1`) 자동 인쇄.
5. 이후 모든 보고서: 게이트 없이 즉시 열람/인쇄/다운로드.

## 에러·엣지

- 멱등 완료: 이미 완료면 `POST complete`는 200, 상태 불변.
- `report_id == None`(저장 실패, 드묾): 영구 경로가 애초에 없음 → 모달 1회 표시만 가능, `인쇄&저장` 비활성(PR #125의 비활성 처리 유지).
- 미인증 접근: 기존 인증 미들웨어가 처리(로그인 리다이렉트).
- 다운로드 직접 호출(URL): 미완료면 403(하드).

## 테스트

- 마이그레이션: `ensure_users_survey_completed_column` 컬럼 추가·멱등.
- `POST /api/survey/complete`: 미완료→완료 기록, 재호출 멱등.
- `GET /api/lessonplan/reports/{id}`: 미완료 403 / 완료 200.
- `GET /api/lessonplan/reports/{id}/download`: 미완료 403 / 완료 200.
- (가능 시) 뷰 컨텍스트 `survey_completed` 전달 확인.
- 회귀: `python -m pytest` 수집 에러 23건 baseline 유지, 신규 회귀 0.

## 범위 밖 (YAGNI)

- Google Forms API 실검증, in-app 설문, 주기적 재설문, 보고서별 설문, 관리자용 설문 통계 — 모두 제외.

## 영향 파일

신규: `app/routers/survey.py`, `app/migrations/users_survey_completed_column.py`, 테스트 1~2개.
수정: `app/models/users.py`, `app/migrations/__init__.py`, `app/main.py`, `app/routers/lessonplan_analysis.py`, `app/routers/views.py`, `app/templates/user/report_viewer.html`, `app/templates/user/dashboard.html`.
