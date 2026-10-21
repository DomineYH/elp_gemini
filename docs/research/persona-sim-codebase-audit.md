# PRD §2·§7·§9 "기존 시스템 분석" vs 실제 코드 대조 (#130)

대상: `refactoring/persona_sim/PRD — 학생 페르소나 수업 시뮬레이션.md` §2, §7, §9.
기준 커밋: `49c224a` (main HEAD, 2026-10-21). 모든 경로는 저장소 루트 기준, `file:line`은 해당 커밋의 행 번호.

## 1. 항목별 "PRD 주장 → 실제"

### 1.1 Gemini 429/503 재시도

| PRD 주장 | 실제 | 근거 |
| --- | --- | --- |
| `utils/gemini_retry.py`의 429 재시도 데코레이터 | **파일 존재.** 경로는 `app/utils/gemini_retry.py`. 429(ClientError)와 5xx(ServerError 500/502/503/504) 모두 재시도 | `app/utils/gemini_retry.py:32`, `:43-56` |
| `GeminiQuotaExhausted` / `GeminiServerOverloaded`를 그대로 받아 429/503 매핑 | 예외 클래스는 그 파일에 정의. 데코레이터 `retry_on_resource_exhausted(max_attempts=3, initial_wait=2.0, max_wait=16.0)`는 **동기 callable 전용**(tenacity, 지수 백오프) | `app/utils/gemini_retry.py:35-40`, `:59-99` |
| 같은 재시도 유틸 재사용 | 현재 적용 지점은 **1곳**: `lessonplan_analysis_service._call_gemini_with_file_search` (모듈 레벨 sync 함수). QnA/평가 서비스의 `generate_content` 호출에는 미적용 | `app/services/lessonplan_analysis_service.py:34-37`, `:89-97`; 미적용: `app/services/qna_service.py:293`, `app/services/eval_service.py:171` |
| 429/503으로 매핑 | 서비스가 예외를 `{"success": False, "error_code": "RESOURCE_EXHAUSTED" \| "MODEL_OVERLOADED"}` dict로 바꾸고, 라우터가 `HTTPException(429/503, headers={"Retry-After": "30"})`로 변환. 라우터 레벨 매핑이지 예외 전파가 아님 | `app/services/lessonplan_analysis_service.py:509-529`; `app/routers/lessonplan_analysis.py:68-83` |
| 프런트 재시도 버튼 | 대시보드 `startAnalysis()`는 non-2xx를 `alert()`로만 처리. 재시도 버튼 없음 | `app/templates/user/dashboard.html:1181-1196` |
| 이슈 #51/#53/#120 | #51(429) → 커밋 `d754497`(헬퍼 추가), `b6db69e`/`facb09e`(PR #52). #53 제목은 503 재시도 요청이나 `git log --grep '#53'` 매칭 커밋 없음. #120(503) → `a714323` (PR #121)이 `gemini_retry.py`에 ServerError 분기 추가 | `git log --oneline --grep='429\|503\|#120'` |

### 1.2 모델 설정

| PRD 주장 | 실제 | 근거 |
| --- | --- | --- |
| 기본 모델 `gemini-3.1-flash-lite` | **맞음.** `GEMINI_QNA_MODEL`, `GEMINI_EVAL_MODEL` 모두 기본값 `gemini-3.1-flash-lite` | `app/config.py:62-67` |
| 같은 `genai.Client` 재사용 | 공용 클라이언트 없음. 서비스마다 `genai.Client(api_key=settings.GOOGLE_API_KEY, http_options={'api_version': 'v1beta'})`를 `__init__`에서 생성. `FileSearchService.get_client()`만 클래스 싱글톤 | `app/services/lessonplan_analysis_service.py:147-151`; `app/services/qna_service.py:43-44`; `app/services/eval_service.py:37-38`; `app/services/file_search_service.py:113-123` |
| 시뮬레이션용 설정값 추가 자리 | `GEMINI_EVAL_MODEL` 블록 바로 뒤(`# File Search` 주석 앞) | `app/config.py:65-69` |

### 1.3 보고서 열람·저장

| PRD 주장 | 실제 | 근거 |
| --- | --- | --- |
| 기존 `report_viewer.html`로 열람 | **템플릿 존재.** `app/templates/user/report_viewer.html`. 라우트 `GET /reports/view/{report_id}` (HTML shell, `report_id`만 전달). 페이지 JS가 `GET /api/lessonplan/reports/{id}`로 JSON을 받아 `marked.parse`로 렌더, 다운로드 링크는 `/api/lessonplan/reports/{id}/download` | `app/routers/views.py:282-310`; `app/templates/user/report_viewer.html:29-30`, `:52`, `:104`, `:123` |
| — | 분석 직후에는 새 창이 아니라 대시보드 **인라인 모달** `#analysisModal`에 `showAnalysisResult(markdown)`으로 표시. "내 보고서" 목록 링크만 `/reports/view/{id}` 사용 | `app/templates/user/dashboard.html:402`, `:1205`, `:981-986` |
| — | `eval_report.html`, `doc_detail.html`, `viewer.html`은 **어떤 라우터도 렌더하지 않음** (`grep -rn '\.html' app/routers`에서 user 템플릿은 `report_viewer.html`만). `base.html`의 `/dashboard/viewer` 링크에 대응 라우트 없음 | `app/routers/views.py:309`; `app/routers/admin/users.py:715`(`admin_report_viewer.html`); `app/templates/base.html:67` |
| 보고서 JSON/목록 API | prefix `/api/lessonplan`: `POST /analyze`, `GET /reports`, `GET /reports/{id}`, `GET /reports/{id}/download` | `app/routers/lessonplan_analysis.py:24`, `:27`, `:100`, `:135`, `:191` |
| `report_storage_service.py`가 Markdown 저장 후 `analysis_reports`에 경로 기록 | **맞음.** `ReportStorageService(base_dir="app/static/reports").save_report(user_id, original_filename, report_content)` → `app/static/reports/{user_id}/{YYYYmmddHHMMSS}_{원본stem}_{uuid8}_reports.md`. 목록은 `*_reports.md` glob. 반환 `{filename, file_path, timestamp}`를 `AnalysisReport(report_filename, report_path, upload_id, latency_ms, ...)`에 기록 | `app/services/report_storage_service.py:17`, `:36-96`, `:148`; `app/services/lessonplan_analysis_service.py:410-432`; `app/models/analysis_reports.py:23-74` |
| — | 별도 `AnalysisStorageService(base_dir="data/analys")`도 존재(구형 경로). 분석 흐름은 `ReportStorageService`를 사용 | `app/services/analysis_storage_service.py:16`; `app/services/lessonplan_analysis_service.py:155` |
| 이모지 검사 `scripts/check_no_emojis_in_reports.py` | **존재.** `app/static/reports/*_reports.md`를 검사(인용 `>` 줄 제외). `make` 타깃과 단위 테스트 있음 | `scripts/check_no_emojis_in_reports.py:11`, `:38`; `Makefile:8`, `:11`; `tests/unit/test_check_no_emojis_in_reports.py` |
| dedup 패턴(1회 생성 후 캐시) | 사용자 **최신** `lessonplan_uploads` 행에 연결된 `analysis_reports`가 있으면 Gemini 호출 없이 `ALREADY_ANALYZED` → 라우터 409 + `X-Report-Id`. DB 유니크 인덱스 `uq_analysis_reports_upload_id`로 race 방어 | `app/services/lessonplan_analysis_service.py:184-205`, `:441-480`, `:584-615`; `app/routers/lessonplan_analysis.py:56-67`; `app/migrations/lessonplan_uploads_table.py:117` |

### 1.4 업로드 흐름

| PRD 주장 | 실제 | 근거 |
| --- | --- | --- |
| `POST /dashboard/upload`: PDF를 `app/static/uploads/{user_id}/`에 저장, pypdf 추출, user-{id}-store 업로드, `lessonplan_uploads` 행 생성 | 경로·순서 **맞음.** 저장 파일명 `{timestamp}_{safe_original}`, URL `/static/uploads/{user_id}/{saved_filename}`. 업로드마다 기존 `user-{id}-store` 삭제 후 재생성 | `app/routers/views.py:86-92`, `:123-136`, `:170-173`, `:179-180`, `:197-204` |
| `extracted_text` 재사용 | **DB에 저장되지 않음.** `lessonplan_uploads` 컬럼은 `id, user_id, filename, original_filename, file_hash, created_at`뿐. `extracted_text`는 업로드 응답의 템플릿 컨텍스트(`document.content`, `extracted_text`)로만 전달되고 사라짐. 재사용하려면 `app/static/uploads/{user_id}/{filename}`을 다시 pypdf로 읽거나 컬럼을 추가해야 함 | `app/models/lessonplan_uploads.py:35-59`; `app/routers/views.py:213-237` |
| `upload_id` 식별자 | `lessonplan_uploads.id` = 정수 PK(autoincrement). 템플릿에는 **전달되지 않음**; 템플릿의 `document.id`는 File Search `document_id`(문자열) | `app/models/lessonplan_uploads.py:35`; `app/routers/views.py:213-222` |
| — | `GET /dashboard`는 `document`를 넘기지 않음 → FAB는 업로드 POST 응답 화면에서만 보임. 분석 서비스는 `session_id`를 쓰지 않고 "해당 사용자의 최신 업로드 행"을 대상으로 삼음(대시보드는 `session_id: 1` 더미 전송) | `app/routers/views.py:60-85`; `app/services/lessonplan_analysis_service.py:597-604`; `app/templates/user/dashboard.html:1161` |
| 유니크 제약 | `(user_id, filename)` 유니크 인덱스 `uq_lessonplan_uploads_synthetic_per_user` | `app/migrations/lessonplan_uploads_table.py:86-88` |

### 1.5 FAB 마크업

| PRD 주장 | 실제 | 근거 |
| --- | --- | --- |
| `dashboard.html` 하단 중앙 FAB 2개(`QnA 챗봇`, `분석 시작`), 가로 배치(#101) | **맞음.** `{% if document %}` 안의 `<div class="fixed bottom-8 left-1/2 -translate-x-1/2 z-40 flex flex-row space-x-4">`에 `<button onclick="toggleChatbot()">`(파랑, "QnA 챗봇") → `<button onclick="startAnalysis()">`(인디고, "분석 시작") 순. 직사각형 `px-5 py-3 rounded-lg` + 아이콘 + 라벨. #101=`8bf78ed`, #108(업로드 후에만 표시, 순서/형태)=`c7112bb` | `app/templates/user/dashboard.html:332-354` |
| `viewer.html`에도 동일 추가 | `viewer.html`의 FAB는 **다른 구조**: 조건 없는 div(같은 위치 클래스), 원형 `p-4 rounded-full` 아이콘 2개 — `<a href="/eval/{{ document.id }}">`(평가 보고서) + `<button onclick="toggleQnAModal()">`. 그리고 이 템플릿은 **라우터에서 렌더되지 않음**(§1.3) | `app/templates/user/viewer.html:38-60` |

### 1.6 마이그레이션 패턴

| PRD 주장 | 실제 | 근거 |
| --- | --- | --- |
| `app/migrations/simulation_tables.py`에서 `CREATE TABLE IF NOT EXISTS` | 기존 패턴은 `async def ensure_<name>(engine: AsyncEngine) -> bool`: `run_sync`로 PRAGMA(`table_info`, `index_list`, `sqlite_master`)를 조회해 테이블/컬럼/인덱스 존재를 직접 확인한 뒤 `CREATE TABLE ...` / `CREATE INDEX ...`를 실행하고 변경 여부(bool) 반환. `IF NOT EXISTS`가 아니라 사전 조회 방식 | `app/migrations/lessonplan_uploads_table.py:19-37`, `:39-74`, `:76-92` |
| — | 함수는 `app/migrations/__init__.py`에서 re-export하고 `app/main.py`의 `@app.on_event("startup")`에서 순서대로 호출 | `app/migrations/__init__.py:17`, `:32`; `app/main.py:23-34`, `:237-303` |
| 호출 순서 | `ensure_criteria_file_path_column`(242) → `ensure_criteria_display_alias_column`(246) → `ensure_criteria_stable_id_column`(252) → `ensure_app_state_table`(258) → `ensure_users_lockout_columns`(262) → `drop_user_profiles`(268) → `drop_users_email_column`(272) → `ensure_lessonplan_uploads_table`(276) → `rename_chat_session_in_service_teacher_label`(282) → `rename_preservice_university_regions`(289) → `_drop_legacy_invite_codes_table_if_enabled`(303) | `app/main.py:242-303` |
| 모델 위치 `app/models/simulation.py`(6테이블 1파일) | 기존 관례는 테이블당 파일 1개(`analysis_reports.py`, `lessonplan_uploads.py`, `chat_sessions.py`, `chat_messages.py`, ...) | `app/models/` |
| 라우터 등록 | `app/main.py:368-374` (`auth, qna, evaluations, lessonplan_analysis, views, admin_router, admin_exports`) | `app/main.py:368-374` |
| `chat_messages` role 2값 | **맞음.** `role = Column(SQLEnum(MessageRole))` (user/assistant). `chat_sessions.user_type`(String, nullable) 별도 존재 | `app/models/chat_messages.py:44-48`; `app/models/chat_sessions.py:52-57` |

### 1.7 프롬프트 로더

| PRD 주장 | 실제 | 근거 |
| --- | --- | --- |
| `prompt/prompt.md`를 섹션별 로드(`evaluation`, `qna`) | 실제 로드 키는 **3개**: `evaluation`, `qna`, `lesson_analysis` (실행 확인). 섹션 규칙: 정규식 `\n---\s*\n+## (\S+)\s*\n` — **`---` 구분선 바로 다음 줄의 `## <공백없는_단일토큰>`** 만 섹션 헤더로 인식. 본문 안의 `## 1. 교육과정 ...` 같은 헤더는 토큰에 공백이 있어 섹션으로 잡히지 않음 | `app/services/prompt_loader_service.py:64-90`; `prompt/prompt.md:5-7`, `:22-24`, `:105-107` |
| 관리자 `/admin/prompts`에서 편집 가능 | **맞음, 자동 노출.** `GET /admin/prompts`가 `loader.list_available_prompts()`로 목록을 만들어 템플릿 `{% for prompt in prompts %}`에 넘김 → 새 섹션을 파일에 추가하면 UI에 자동 표시. `POST /admin/api/prompts`, `PUT/DELETE /admin/api/prompts/{prompt_type}`로 생성/수정/삭제 | `app/routers/admin/prompts.py:26`, `:55-80`, `:99`, `:136`, `:173`; `app/templates/admin/admin_prompts.html:28` |
| — | 저장(`_save_prompts`)은 캐시 전체를 `# 시스템 프롬프트` 헤더 + `## {type}` + `---` 형식으로 **파일 전체 재작성**(tmp → `os.replace`). 관리자 라우터는 모듈 싱글톤 `_prompt_loader`를 쓰고, 분석 서비스는 요청마다 `PromptLoaderService()`를 새로 만들어 파일을 다시 읽음 | `app/services/prompt_loader_service.py:162-196`; `app/routers/admin/prompts.py:32-39`; `app/services/lessonplan_analysis_service.py:152` |

### 1.8 관리자

| PRD 주장 | 실제 | 근거 |
| --- | --- | --- |
| `/admin/exports`(bulk export) 페이지 | **페이지 없음.** 실제는 단일 API `GET /admin/api/exports/all.zip` (필터 쿼리 → ZIP 스트리밍: `manifest.csv`, `users.csv`, 보고서 md, 대화 jsonl, 지도안 원본). 관리자 대시보드와 사용자 상세 페이지의 JS가 이 URL로 링크 생성 | `app/routers/admin/exports.py:15-22`; `app/services/admin_export_service.py:460-505`, `:597`, `:623`; `app/templates/admin/admin_dashboard.html:93`; `app/templates/admin/admin_user_detail.html:39` |
| `/admin/qna-logs` | **맞음.** HTML `GET /admin/qna-logs`, JSON `GET /admin/api/qna-logs` | `app/routers/admin/qna_logs.py:20-24`, `:117` |
| 관리자 nav 메뉴 추가 위치 | `base.html`의 `{% block nav_links %}`(관리자: 대시보드/평가기준/사용자)가 기본이지만, **관리자 템플릿 10개가 각자 `nav_links` 블록을 오버라이드**(예: `admin_dashboard.html:7-10` 대시보드/사용자/QnA 로그/프롬프트). 메뉴 1개 추가 = 각 템플릿 블록 수정. 대시보드 카드 링크는 `admin_dashboard.html:103-115` | `app/templates/base.html:35-63`; `grep -rln nav_links app/templates` |
| 관리자 라우터 구성 | `app/routers/admin/__init__.py`의 `router = APIRouter()`(prefix 없음)에 `dashboard, criteria_views, criteria, qna_logs, users, prompts` 포함. `exports.router`는 `main.py`에 별도 등록. 각 서브 라우터가 경로에 `/admin` 직접 명시 | `app/routers/admin/__init__.py:6-24`; `app/main.py:373-374` |
| `admin_csrf` 적용 | Depends가 아니라 **함수 직접 호출** 패턴. GET 뷰에서 `ensure_admin_csrf_token(request)`로 세션 키 `admin_csrf_token` 생성 → 템플릿 `<meta name="csrf-token">` → JS가 헤더 `x-csrf-token` 전송 → 변경 라우트 본문 첫 줄에서 `require_admin_csrf_token(request)` (불일치 403). 인증은 `Depends(get_current_admin)` | `app/utils/admin_csrf.py:9-34`; `app/routers/admin/users.py:745`, `:1029-1035`; `app/templates/admin/admin_qna_logs.html:6`, `:192`; `app/routers/admin/exports.py:21` |

### 1.9 문서 관례

| PRD 주장 | 실제 | 근거 |
| --- | --- | --- |
| `docs/superpowers/specs/`에 설계, `docs/superpowers/plans/`에 계획 | **디렉터리 존재하며 추적 중.** specs 13개(`YYYY-MM-DD-<slug>-design.md`), plans 20개(`YYYY-MM-DD-<slug>.md`). 최근 커밋 2026-06-05~06(`3aabe97`, `3374e38`, `8bf78ed`) | `git ls-files docs/superpowers`; `git log -3 -- docs/superpowers` |
| — | `docs/plans/`(13개, 같은 날짜 접두 관례)도 병행 사용. 최근 2026-06-05(`fdb0420`). `docs/research/`는 이 문서가 처음. 루트 `research/`에는 File Search API 노트 2개 | `git log -3 -- docs/plans`; `ls research` |
| `CLAUDE.md`: 수술적 변경·단순성 | **HEAD에 추적 중**(`git ls-files CLAUDE.md`), 이 작업 트리에서 `git status` clean. 마지막 변경 `1fcbf1e`(2026-05-11). `## 2. Simplicity First`(:17), `## 3. Surgical Changes`(:29). 다른 체크아웃의 `D CLAUDE.md`는 커밋되지 않은 로컬 삭제이며 HEAD 내용이 유효 | `CLAUDE.md:17-44`; `git log -1 -- CLAUDE.md` |
| — | `AGENTS.md`가 `docs/agents/issue-tracker.md` 등을 참조하지만 `docs/agents/`는 없음 | `AGENTS.md`; `ls docs` |

### 1.10 §2 표의 나머지 사실

| PRD 주장 | 실제 | 근거 |
| --- | --- | --- |
| 2패스 grounded 호출 | **맞음.** 1패스 `_retrieve_lessonplan_text(client, model, user_store_id)`, 2패스 `_call_gemini_with_file_search(...)` (#118) | `app/services/lessonplan_analysis_service.py:66`, `:90-100` |
| 테스트 관례(§9 Playwright 스모크) | `tests/e2e/`는 pytest 기반 2개(`test_admin_criteria_sync_badge_smoke.py`, `test_criteria_multi_active.py`). Playwright 의존·테스트 없음 | `ls tests/e2e`; `grep -rl playwright pyproject.toml tests` |

## 2. 구현 스펙이 기댈 지점

- 재시도/예외: `app/utils/gemini_retry.py` — `retry_on_resource_exhausted(...)`(sync 함수에만), `GeminiQuotaExhausted`, `GeminiServerOverloaded`. HTTP 매핑 예시: `app/routers/lessonplan_analysis.py:68-83`(429/503 + `Retry-After: 30`), 서비스 측 dict 변환 예시: `app/services/lessonplan_analysis_service.py:509-529`.
- 클라이언트/모델: `genai.Client(api_key=settings.GOOGLE_API_KEY, http_options={'api_version': 'v1beta'})` (`app/services/lessonplan_analysis_service.py:148-151`); 새 설정값은 `app/config.py:67` 뒤.
- 업로드 식별: `LessonPlanUpload`(`app/models/lessonplan_uploads.py`) — 정수 `id`, 원본 파일은 `app/static/uploads/{user_id}/{filename}`; "현재 지도안" = 사용자 최신 행 조회 쿼리 `app/services/lessonplan_analysis_service.py:597-604`. 추출 텍스트는 DB에 없음(§1.4).
- 보고서 저장/열람: `ReportStorageService.save_report()` (`app/services/report_storage_service.py:36`), 메타 행 `AnalysisReport`(`app/models/analysis_reports.py`), 뷰어 shell `GET /reports/view/{report_id}` + `app/templates/user/report_viewer.html` (JSON 소스 URL이 `/api/lessonplan/reports/{id}`로 고정: `:123`, `:30`), 인라인 모달 `showAnalysisResult` (`app/templates/user/dashboard.html:1205`).
- dedup: `_find_existing_report_for_latest_upload` (`app/services/lessonplan_analysis_service.py:584`) + 409 응답 형식 (`app/routers/lessonplan_analysis.py:56-67`).
- FAB: `app/templates/user/dashboard.html:332-354`의 `{% if document %}` 블록. `viewer.html`은 라우트 없음.
- 마이그레이션: `app/migrations/lessonplan_uploads_table.py:39`의 `ensure_*` 시그니처·PRAGMA 조회 헬퍼(`:19-37`), `app/migrations/__init__.py` export, `app/main.py:276` 뒤 호출 지점. 모델은 `app/models/<table>.py` 파일 분리 관례.
- 프롬프트: `prompt/prompt.md`에 `---` 다음 줄 `## sim_student` 형식으로 추가하면 `PromptLoaderService.get_prompt("sim_student")` (`app/services/prompt_loader_service.py:92`)와 `/admin/prompts` UI에 자동 반영.
- 관리자: 인증 `Depends(get_current_admin)`, CSRF는 `ensure_admin_csrf_token`/`require_admin_csrf_token` 직접 호출(`app/utils/admin_csrf.py`), 템플릿 `<meta name="csrf-token">` + 헤더 `x-csrf-token`; nav는 각 관리자 템플릿의 `{% block nav_links %}`; export는 `GET /admin/api/exports/all.zip`의 `AdminExportService` (`app/services/admin_export_service.py:105`, `:460`).
- 인증 의존성: `get_current_user` (`app/dependencies.py`, 사용 예 `app/routers/lessonplan_analysis.py:11`).
- 문서 위치: 설계 `docs/superpowers/specs/YYYY-MM-DD-<slug>-design.md`, 계획 `docs/superpowers/plans/YYYY-MM-DD-<slug>.md` (또는 `docs/plans/`).
- 이모지 검사: `scripts/check_no_emojis_in_reports.py`는 `app/static/reports/*_reports.md`만 검사(`:38`) — 다른 경로/접미사로 저장하면 검사 대상에서 빠짐.
