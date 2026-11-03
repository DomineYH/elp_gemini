# PRD — 학생 페르소나 수업 시뮬레이션

Oct 20, 2026 · @Lee YongHan

elp\_gemini(AI기반 수업설계 피드백 시스템)에 **LLM 기반 학생 페르소나 수업 시뮬레이션**을 추가한다. 예비교사가 업로드한 지도안을 HACHIMI-1M 스키마로 구성한 가상 학생들에게 국면별로 실행해 보고, 그 대화를 바탕으로 지도안 수정 가설을 받는다. 진입점은 지도안 업로드 후 하단 중앙 FAB의 세 번째 버튼이며, UI/UX를 먼저 확정한 뒤 기능을 붙인다.

## 1. 개요와 목표

논문 「예비교사의 수업설계를 위한 LLM 기반 학생 페르소나 시뮬레이션의 가능성 탐색」(이용한·심재권, 2026, KACE 하계)은 연구자가 Claude Code로 수동 실행한 **설계 점검형** 시뮬레이션이었다. 이 PRD는 그 절차를 elp\_gemini 안의 반복 가능한 제품 기능으로 옮긴다.

**문제.** 예비교사는 지도안이 서로 다른 특성의 학생에게 어떻게 읽히고 전개될지 실행 전에 점검할 기회가 거의 없다. 기존 elp\_gemini는 문서의 정합성을 보는 **정적 점검**(RAG 분석 보고서, QnA)만 제공한다.

**해법.** 지도안을 국면(도입/활동/정리)으로 분해하고, HACHIMI-1M 스키마로 구성·번안한 학생 페르소나가 각 국면에 반응하게 한 뒤, 교사(사용자)가 대응하는 **동적 점검**을 추가한다. 종료 후 전체 대화를 분석해 지도안 피드백을 생성한다.

**성공 기준 (MVP).**

| 기준 | 목표 |
| --- | --- |
| 진입 | 지도안 업로드 후 FAB 클릭 1회로 시뮬레이션 시작 |
| 페르소나 | 2\~6명, 무작위 또는 직접 선택, 한국 맥락 번안 적용 |
| 국면 | 지도안에서 국면 3개 이상 자동 추출, 국면별 반응 생성 |
| 진행 | 학생 전원 동의 또는 Skip으로 다음 국면 전이, 마지막 국면까지 완주 |
| 저장 | 모든 발화(교사·학생·시스템)가 DB에 시간순 저장 |
| 피드백 | 교사 발화 추천 · 진행 방향 · 변경 방향의 3개 섹션 생성 |
| 지연 | 국면당 학생 반응 생성 10초 이내(4명 기준) |

**명시적 비목표.** 학생 행동 예측 정확도 검증, 실시간 음성, 다인 동시 접속, 지도안 자동 수정. 피드백은 예측이 아니라 **지도안의 잠재적 취약점 가설**로만 제시한다(논문 §5).

## 2. 기존 시스템(elp\_gemini) 분석

[DomineYH/elp\_gemini](https://github.com/DomineYH/elp_gemini) 는 FastAPI(async) + SQLAlchemy(aiosqlite, SQLite WAL) + Jinja2/Tailwind CDN + Google Gemini(`google-genai`, 기본 모델 `gemini-3.1-flash-lite`) + Google File Search Tool(RAG) 구조다. 이번 기능은 다음 지점에 올라탄다.

| 영역 | 현재 코드 | 시뮬레이션이 쓰는 방식 |
| --- | --- | --- |
| 업로드 | `POST /dashboard/upload` (`app/routers/views.py`): PDF를 `app/static/uploads/{user_id}/`에 저장, pypdf로 텍스트 추출, user-{id}-store에 File Search 업로드, `lessonplan_uploads` 행 생성 | `extracted_text`와 `upload_id`를 재사용해 국면 분해. 추가 업로드 없음 |
| 진입 UI | `dashboard.html` 하단 중앙 FAB 2개(`QnA 챗봇`, `분석 시작`), 가로 배치(issue #101) | 세 번째 버튼 `수업 시뮬레이션` 추가. `viewer.html`에도 동일 추가 |
| LLM 호출 | `services/lessonplan_analysis_service.py`: 2패스 grounded 호출, `utils/gemini_retry.py`의 429 재시도 데코레이터 | 같은 `genai.Client`·재시도 유틸 재사용. 시뮬레이션은 File Search 없이 지도안 텍스트를 프롬프트에 직접 주입(국면 텍스트가 짧음) |
| 프롬프트 | `prompt/prompt.md`를 `PromptLoaderService`가 섹션별 로드(`evaluation`, `qna`) | 같은 파일에 `sim_student`, `sim_agree`, `sim_feedback` 섹션 추가. 관리자 `/admin/prompts`에서 편집 가능 |
| DB | `chat_sessions`/`chat_messages`(QnA 전용, role=user/assistant 2값), `analysis_reports`, `lessonplan_uploads` | QnA 테이블을 재사용하지 않고 전용 테이블 신설(화자가 N명, 국면·페르소나 메타 필요). §6 참조 |
| 보고서 | `report_storage_service.py`가 Markdown 파일로 저장 후 `analysis_reports`에 경로 기록 | 피드백 보고서도 같은 방식으로 `.md` 저장. 기존 `report_viewer.html`로 열람 |
| 관리자 | `/admin/qna-logs`, `/admin/exports`(bulk export) | 시뮬레이션 로그 조회·CSV export 항목 추가(Phase 4) |

**제약.** 프로젝트 `CLAUDE.md`는 수술적 변경과 단순성을 요구한다(불필요한 추상화 금지, 인접 코드 리팩터링 금지). 따라서 새 기능은 `app/routers/simulation.py`, `app/services/simulation_service.py`, `app/models/simulation_*.py`, `app/templates/user/simulation.html`에 격리하고, 기존 파일 변경은 FAB 버튼 1개 추가와 `main.py` 라우터 등록, `prompt.md` 섹션 추가로 제한한다.

## 3. 사용자 흐름

&#91;embedded content: 시뮬레이션 상태 전이 · 국면 루프 1개, 결정 2개\]

국면 루프 안에서 교사는 학생 반응을 보고 발화를 입력하거나, 학생 전원이 동의 표시를 내면 다음 국면으로 넘어간다. Skip은 동의 없이 전이하며 시스템 메시지로 기록된다. 마지막 국면이 끝나면 대화록과 피드백으로 이어진다.

## 4. 기능 요구사항

| ID | 요구사항 | 상세 | 우선순위 |
| --- | --- | --- | --- |
| F1 | FAB 진입 | 지도안 업로드 완료(`document` 존재) 시 하단 중앙 FAB에 `수업 시뮬레이션` 버튼 노출. 클릭 → `GET /simulation/new?upload_id=` | Must |
| F2 | 국면 분해 | 업로드 시 추출된 `extracted_text`를 Gemini로 도입·활동1\~n·정리 국면으로 분해해 `simulation_phases`에 저장(국면명, 시간, 교사 발문, 과업, 자료, 유의점). 자동 분해 실패 시 사용자가 수동으로 국면 경계를 지정 | Must |
| F3 | 페르소나 데이터셋 | HACHIMI-1M `sample_data/merged_students_10k_EN.jsonl`(MIT)을 `data/personas/`에 1회 적재. 필드: id, age, gender, grade, developmental\_stage, strengths, weaknesses, academic\_level, personality, values, social\_relationships, creativity, mental\_health | Must |
| F4 | 페르소나 선택 | (a) 무작위: 학년 필터 + 학업 수준 4범주 균등 추출, (b) 직접 선택: 표에서 체크. 인원 2\~6명(기본 4). 한국식 가명을 무작위 부여, 세션 내 고유 | Must |
| F5 | 한국 맥락 번안 | 선택된 원본 레코드를 번안 프롬프트로 1회 변환: 학업 수준 High/Medium/Low/Poor → 높은 도달/안정적 도달/부분 도달/추가 지원 필요, 중국 교과명 → 한국 초등 교과명, 가치관·심리 필드 → 관찰 가능한 행동 기술(낙인·임상 표현 금지). 원본과 번안본 모두 `simulation_personas`에 저장 | Must |
| F6 | 국면 반응 생성 | 국면 진입 시 각 페르소나가 교사 발문·과업에 대한 행동·발화·산출물을 1회 생성. 교사 발화 입력 시 대상(전체/특정 학생)이 응답. 페르소나별 독립 호출(병렬, `asyncio.gather`) | Must |
| F7 | 동의 상태 | 각 학생 응답에 구조화 필드 `ready_for_next: bool`을 포함시켜 "과업을 마쳤다고 판단"을 표시. 전원 true면 `다음 국면으로` 활성화 | Must |
| F8 | Skip | 동의 없이 다음 국면 전이. 시스템 메시지(`type=skip`)로 기록. 피드백에서 Skip된 국면은 "교사 개입 전 전이"로 표시 | Must |
| F9 | 대화 저장 | 교사·학생·시스템 발화 전부 `simulation_messages`에 생성 즉시 저장(세션, 국면, 화자, 본문, 구조화 메타, 모델명, 지연). 페이지 새로고침 후 복원 | Must |
| F10 | 대화록 | 세션 종료 후 시간순 전체 발화 열람, 국면 필터, 화자 색 유지 | Must |
| F11 | AI 피드백 | 대화록 + 지도안 텍스트 + 페르소나 요약을 입력해 ① 교사 발화 추천(실제 발화 ↔ 추천 발화 쌍), ② 수업 활동 진행 방향, ③ 수업 활동 변경 방향을 생성. 상단에 잠재적 위험 시나리오(R1\~R4 유형 참고) 요약. Markdown 저장 후 `report_viewer.html`로 열람 | Must |
| F12 | 지도안 발문 불러오기 | 입력창 옆 버튼으로 현재 국면의 지도안 발문을 입력창에 채움 | Should |
| F13 | 재실행 | 같은 지도안으로 다른 페르소나 구성으로 새 세션 시작 | Should |
| F14 | 관리자 로그 | `/admin/simulation-logs`에서 세션 목록·대화 열람·CSV export | Could |
| F15 | 모둠 대화 모드 | 논문 §3.3의 집단 수준(학생 간 다중 화자 대화) 생성 | Could (Phase 5) |
| F16 | 커스텀 페르소나 | 설정 화면의 \`직접 만들기\`로 사용자가 학생 페르소나를 작성. 양식은 HACHIMI-1M 레코드 스키마와 동일(age, gender, grade, developmental\_stage{piaget/erikson/kohlberg}, strengths\[\], weaknesses\[\], academic\_level 4범주, personality, values, social\_relationships, creativity, mental\_health). JSON 붙여넣기 가져오기/내보내기 지원. 저장 시 사용자 라이브러리(\`persona\_library\`)에 남고 후보 표에 '내가 만듦' 표시로 추가되며, 데이터셋 페르소나와 섞어 선택 가능. 저장 시 같은 번안 프롬프트(F5)를 통과시켜 adapted\_profile 생성 | Must |
| F17 | 관리자 피드백 커스텀 | \`/admin/simulation/settings\`에서 피드백 생성에 적용할 지침을 설정: (a) 커스텀 사용 on/off, (b) 필수 포함 관점 체크(성취기준 연계, UDL, 디지털 도구, 발문 유형, 형성평가 시점 등), (c) 기존 평가기준 문서(/admin/criteria 활성 문서) 연결, (d) 자유 서술 추가 지침. off이거나 비어 있으면 기본값(prompt.md \`sim\_feedback\`) 그대로 사용. 버전 관리하며 보고서에 적용 버전을 기록. 기본 제약(가설·단정 금지·낙인 금지)은 항상 유지 | Must |

**해석 한계의 제품 내 명시(필수).** 설정 화면과 피드백 화면에 "생성 반응은 프로필을 조건화한 가설이며 실제 학생 행동이나 예측이 아니다"를 고정 문구로 표시한다. 피드백 문구에서 "학생이 \~할 것이다"식 단정 표현을 금지하는 프롬프트 제약을 둔다.

## 5. UI/UX 명세

확정 시안은 별도 HTML 아티팩트 「페르소나 수업 시뮬레이션」(화면 0\~4를 전환하며 조작 가능)이며, 이 절은 그 시안을 구현 명세로 옮긴 것이다. 기존 `base.html`의 네비게이션과 Tailwind 유틸리티 클래스를 그대로 쓰고, 추가 폰트·CSS 프레임워크는 도입하지 않는다.

| 화면 | 경로 | 핵심 컴포넌트 | 규칙 |
| --- | --- | --- | --- |
| 0 대시보드 | `/dashboard` (기존) | FAB 3개 가로 배치 `[QnA 챗봇] [분석 시작] [수업 시뮬레이션]` | 세 번째 버튼은 보라(`violet-700`) 계열로 구분, `document` 존재 시에만 렌더. `viewer.html`에도 동일 |
| 1 페르소나 설정 | `/simulation/new` | 좌: 선택 방식 라디오(무작위/직접), 인원 슬라이더 2\~6, 학년·학업수준 필터, 번안 안내. 우: 후보 표(id, 가명, 학업(번안), 강점/약점, 행동 요약), 선택 칩, `시뮬레이션 시작` | 가명은 `다시 추출`로 재부여. 표 행 체크가 인원 슬라이더와 양방향 동기화 |
| 2 시뮬레이션 | `/simulation/{session_id}` | 상단: 국면 스테퍼(완료/현재/대기 pill), 현재 국면 카드(교사 발문·자료·유의점). 중앙: **교사 발화 버블(화면 가로 중앙, 파랑)**, 아래 **학생 좌석 그리드**(1\~4열 반응형). 하단: 동의 카운터 `n / N`, `Skip ▸`, `다음 국면으로 →`. 최하단 고정: 전체 학생용 입력창 + `지도안 발문` + `말하기` | 학생 버블은 각자의 좌석 카드 안에서 세로로 쌓임(최근이 아래). 학생별 고유 색(왼쪽 4px 보더 + 연한 배경)은 세션 내 고정, 대화록·피드백에서도 동일 색. 응답 대기 중 typing 점 3개. 학생 카드 클릭 → 1:1 플로팅 대화창(그 학생의 현재 국면 이력 + 전용 입력창, 닫기/ESC/배경 클릭으로 교실 화면 복귀). 1:1에서 한 발화와 반응은 좌석 카드와 대화록에 (이름에게) 표기로 함께 기록되고, 하단 채팅창은 항상 전원에게 간다. 동의 시 좌석 헤더 pill이 `✓ 다음 단계 OK`로 변경. 전원 동의 전 `다음 국면` 버튼은 비활성(회색) |
| 3 대화록 | `/simulation/{session_id}/transcript` | 시간순 타임라인(mm:ss, 국면 pill, 화자명, 본문), 국면 필터, `AI 피드백 받기` | 화자 점 색 = 세션 색. 시스템 전이(동의/Skip)는 회색 작은 글씨 |
| 4 피드백 | `/simulation/{session_id}/feedback` | 상단: 위험 시나리오 카드 4개(제목·장면·근거 유형). 본문: 탭 3개 ① 교사 발화 추천(실제 ↔ 추천 2열 카드) ② 진행 방향 ③ 변경 방향. 하단: Markdown 저장, 다른 학생으로 재실행, 지도안으로 돌아가기 | 모델명·지연 표시(기존 분석 보고서 규칙과 동일). 상단 고정 문구로 해석 한계 명시 |
| 1-b 페르소나 작성 | \`/simulation/new\` 내 모달 | 선택 방식 라디오에 \`직접 만들기\` 추가 + \`+ 새 페르소나 만들기\` 버튼 → HACHIMI-1M 필드 순서대로 배치된 폼(age/gender/grade/academic\_level, developmental\_stage 3항목, strengths/weaknesses, 서술 5필드), 접이식 JSON 미리보기·가져오기, \`저장하고 후보에 추가\` | academic\_level 선택지에 한국 번안명을 병기. mental\_health·values 입력란에 '임상 용어 없이 수업 중 행동으로' placeholder. 저장된 항목은 후보 표 id 열에 \`내가 만듦\` pill |
| A 관리자 설정 | \`/admin/simulation/settings\` | 좌: \`커스텀 피드백 지침 사용\` 토글, 필수 관점 체크 그리드(①②③은 고정·비활성), 평가기준 문서 연결 pill, 추가 지침 textarea, \`기본 프롬프트 보기\` / \`미리보기\` / \`저장(새 버전)\`. 우: 버전 이력, 적용 범위 | 토글 off면 입력 영역이 흐려지고 비활성. 상단 pill에 현재 적용 상태(\`기본값 사용 중\` / \`커스텀 v3 적용\`) 표시. 기존 \`/admin/prompts\` 레이아웃과 같은 관리자 nav에 메뉴 추가 |

**색 규칙.** 교사 = `--teacher #1d4ed8`(기존 QnA 파랑과 동일). 학생 팔레트 6종(장미·청록·호박·보라·올리브·남색)을 인원 순으로 배정하며, 같은 세션의 모든 화면에서 동일하다. 학업 수준은 색이 아니라 텍스트 pill로만 표시한다(색을 능력 서열로 읽히지 않게).

**반응형.** 좌석 그리드는 `sm:2열 / lg:4열`, 6명이면 `lg:3열`. 모바일에서 교사 입력창은 하단 고정이며 safe-area 패딩을 둔다.

## 6. 데이터 모델

새 테이블 6개. 기존 `chat_sessions`/`chat_messages`는 QnA(2인 대화) 전용이라 재사용하지 않는다. 모두 `app/models/simulation.py`에 두고, 기존 패턴대로 `app/migrations/simulation_tables.py`에서 `CREATE TABLE IF NOT EXISTS`로 생성한다.

| 테이블 | 컬럼 | 비고 |
| --- | --- | --- |
| `simulation_sessions` | id PK · user\_id FK users · upload\_id FK lessonplan\_uploads · status (`setup` / `running` / `finished`) · current\_phase\_idx int · persona\_count int · model\_name · created\_at · finished\_at | 지도안 1개당 세션 N개. `upload_id`로 기존 업로드·분석 보고서와 연결 |
| `simulation_phases` | id PK · session\_id FK · idx int · name (도입/활동1/…) · minutes int null · teacher\_prompt text · task text · materials text · cautions text · source\_span text | F2 국면 분해 결과. `source_span`은 원문 발췌(피드백 근거용) |
| `simulation_personas` | id PK · session\_id FK · seat\_idx int · display\_name (가명) · color\_key (`p1`…`p6`) · source\_dataset (`hachimi-1m`) · source\_record\_id int · raw\_profile JSON · adapted\_profile JSON · adapted\_level (높은 도달 등) | 원본·번안본 동시 보관(논문 §3.2 재현성). 같은 source\_record\_id가 다른 세션에 재사용 가능 |
| `simulation_messages` | id PK · session\_id FK · phase\_idx int · seq int · speaker\_type (`teacher` / `student` / `system`) · persona\_id FK null · target\_persona\_id FK null · content text · structured JSON null · model\_name null · latency\_ms null · created\_at | 학생 메시지의 `structured` = `{action, utterance, artifact, misconception, ready_for_next}`. 시스템 메시지 `structured.type` = `phase_enter` / `agree_advance` / `skip` / `end` |
| \`persona\_library\` | id PK · user\_id FK users · title · raw\_profile JSON(HACHIMI 스키마) · adapted\_profile JSON · created\_at · updated\_at | F16 사용자 작성 페르소나. 세션 생성 시 \`simulation\_personas.source\_dataset='custom'\`, \`source\_record\_id\`=이 테이블 id로 복사해 세션에 스냅샷으로 고정(라이브러리 수정이 지난 세션에 영향 없음) |
| \`simulation\_feedback\_settings\` | id PK · version int · enabled bool · required\_aspects JSON · criteria\_ids JSON · extra\_instructions text · created\_by FK users · created\_at | F17. 최신 행이 현재 설정. \`enabled=false\`이면 기본 프롬프트. \`simulation\_sessions.feedback\_settings\_version\`(컬럼 1개 추가)에 생성 시 적용 버전 기록 |

피드백 보고서는 새 테이블 없이 기존 `analysis_reports`와 같은 방식으로 `.md` 파일 저장 후 `simulation_sessions.feedback_report_path`(컬럼 1개 추가)에 경로를 기록한다. `(session_id, seq)` 유니크 인덱스로 순서를 보장하고, `(session_id, phase_idx)` 인덱스로 국면 필터를 지원한다.

## 7. API 설계

라우터 `app/routers/simulation.py`, prefix `/api/simulation`(JSON) + `/simulation`(HTML). 모든 엔드포인트는 기존 `get_current_user` 의존성으로 세션 소유자만 접근한다. 응답은 동기 JSON이며, 학생 반응 생성은 페르소나별 병렬 호출 후 한 번에 반환한다(SSE 스트리밍은 Phase 3 선택 항목).

| 메서드 · 경로 | 입력 | 출력 | 비고 |
| --- | --- | --- | --- |
| `GET /simulation/new?upload_id=` | — | 페르소나 설정 HTML | 국면 분해가 안 돼 있으면 이 시점에 수행(F2) |
| `GET /api/simulation/personas?grade=&level=&n=&seed=` | 필터 | 후보 페르소나 목록(원본 요약) | 무작위 추출, seed로 재현 |
| `POST /api/simulation/sessions` | `{upload_id, persona_record_ids[] 또는 random:{n, grade, level}}` | `{session_id, personas[], phases[]}` | 번안(F5) 실행, 가명·색 배정, 세션 `status=running`, 국면 0 진입 메시지 생성 |
| `GET /simulation/{sid}` | — | 시뮬레이션 HTML | 저장된 메시지로 복원 |
| `GET /api/simulation/sessions/{sid}` | — | 세션·국면·페르소나·메시지 전체 | 새로고침 복원용 |
| `POST /api/simulation/sessions/{sid}/phases/{idx}/enter` | — | 각 페르소나의 국면 초기 반응 N개 | 국면 진입 시 1회. 중복 호출 시 기존 반환(멱등) |
| `POST /api/simulation/sessions/{sid}/say` | `{content, target_persona_id?}` | 교사 메시지 + 응답 학생 메시지들(`ready_for_next` 포함) | target\_persona\_id 없으면(하단 채팅창) 전원 응답, 있으면(1:1 플로팅 창) 그 학생만 응답 |
| `POST /api/simulation/sessions/{sid}/advance` | `{mode: "agree" / "skip"}` | 다음 국면 정보 + 초기 반응 | `agree`인데 전원 동의가 아니면 409 |
| `POST /api/simulation/sessions/{sid}/finish` | — | `{status:"finished"}` | 이후 `say`/`advance`는 409 |
| `GET /simulation/{sid}/transcript` | `?phase=` | 대화록 HTML |  |
| `POST /api/simulation/sessions/{sid}/feedback` | — | `{report_id, markdown}` | 1회 생성 후 캐시(기존 분석 보고서 dedup 패턴) |
| `GET /simulation/{sid}/feedback` | — | 피드백 HTML | 기존 `report_viewer.html` 재사용 |
| `GET /api/simulation/sessions` | `?upload_id=` | 내 세션 목록 | 대시보드 "지난 세션" 영역에 노출(Phase 4) |
| \`GET / POST / PUT / DELETE /api/simulation/persona-library\` | HACHIMI 스키마 JSON | 라이브러리 항목(원본+번안) | POST 시 스키마 검증(필수 필드·academic\_level 4값) 후 번안 1회 실행. \`sessions\` 생성 입력의 \`persona\_record\_ids\`에 \`custom:\<id>\` 형태로 섞어 전달 |
| \`GET / POST /api/admin/simulation/feedback-settings\` | \`{enabled, required\_aspects\[\], criteria\_ids\[\], extra\_instructions}\` | 현재 설정 + 버전 이력 / 새 버전 | 관리자 전용(\`admin\_csrf\` 적용). \`POST .../preview\`는 샘플 세션으로 피드백 1회 생성해 미리보기 |

오류 처리는 기존 `utils/gemini_retry.py`의 `GeminiQuotaExhausted` / `GeminiServerOverloaded`를 그대로 받아 429/503으로 매핑하고, 프런트는 재시도 버튼을 보인다.

## 8. Gemini 프롬프트 설계

모든 프롬프트는 `prompt/prompt.md`에 섹션으로 추가해 `PromptLoaderService`로 로드하고, 관리자 화면에서 버전 관리한다. 모델은 `GEMINI_SIM_MODEL`(기본 `gemini-3.1-flash-lite`, 설정값 1개 추가)이며, 학생 반응과 동의 판정은 `response_mime_type="application/json"` + `response_schema`로 구조화 출력을 강제한다.

| 섹션 | 입력 | 출력 스키마 | 논문에서 가져온 제약 |
| --- | --- | --- | --- |
| `sim_phase_split` | 지도안 전문 | `[{name, minutes, teacher_prompt, task, materials, cautions, source_span}]` | 국면은 도입·활동·정리 구조(§3.3). 원문 발췌를 `source_span`에 그대로 담아 환각 방지 |
| `sim_adapt_persona` | HACHIMI 원본 레코드 1건 | `{adapted_level, strengths_ko[], weaknesses_ko[], behavior_summary, speech_style, support_needs}` | 석차 범주 → 성취기준 도달도·지원 요구로 재정의, 가치관·심리 상태는 관찰 가능하고 변화 가능한 행동으로, 낙인·임상 판단 금지(§4.4) |
| `sim_student` | 번안 프로필 + 국면 정보 + 해당 국면 대화 이력 + 교사 최신 발화 | `{action, utterance, artifact, misconception, ready_for_next, confidence}` | (1) 프로필과 모순되는 반응 금지 (2) 모르는 개념은 모르는 상태 유지 (3) 초등 6학년 수준 언어 (4) 교사 개입 없이 스스로 어려움을 해결하지 않음 (5) **과잉 협조 금지**: 지원 필요가 명시된 학생은 앞 단계 미완 시 다음 과업에 자발적으로 진입하지 않음(§4.2의 부정 사례) |
| `sim_feedback` | 지도안 전문 + 국면 목록 + 전체 대화록 + 페르소나 요약 + Skip/동의 이력 | Markdown: ① 위험 시나리오(장면·근거 유형: 입력 재현/상호작용/프로필·구조 결합) ② 교사 발화 추천(실제↔추천, 의도) ③ 진행 방향 ④ 변경 방향(발문·비계·자료·평가) | 결과는 가설이며 예측이 아님을 매 섹션 명시. "\~할 것이다" 단정 금지. 위치→기후 단정, 지역 고정 이미지 등 환경결정론적 서술이 대화에 있으면 반례 자료 추가를 권고(§4.4) |

`ready_for_next` 판정 규칙(프롬프트 내 명시): 과업 산출물이 지도안 요구 형식을 충족했고 추가 질문이 없을 때만 true. 추가 지원 필요 학생은 교사 발화로 직접 안내받기 전에는 false를 유지한다. 재현성 기록을 위해 메시지마다 `model_name`, temperature(기본 0.7), latency를 저장한다.

**피드백 프롬프트 조립 규칙(F17).** 최종 시스템 프롬프트 = `sim_feedback` 기본 본문 + (관리자 설정이 `enabled`일 때만) `[추가 관점]` 체크 항목 + `[참고 평가기준]` 연결 문서 발췌(File Search 또는 텍스트 주입) + `[추가 지침]` 자유 서술. 기본 본문의 고정 제약(가설로만 제시, 단정 표현 금지, 낙인 금지, 3개 섹션 구조)은 커스텀 지침보다 뒤에 한 번 더 붙여 우선하게 한다. 커스텀 페르소나(F16)는 데이터셋 레코드와 동일한 `sim_adapt_persona` 경로를 타므로 별도 프롬프트가 없다.

## 9. 개발 단계

UI/UX를 먼저 확정하고(이 PRD와 함께 완료) 정적 화면을 앱에 붙인 뒤, 뒤에서부터 실제 기능으로 교체한다. 각 Phase는 독립 PR 1개이며 프로젝트 관례대로 `docs/superpowers/specs/`에 설계 문서, `docs/superpowers/plans/`에 작업 계획을 둔다.

| Phase | 범위 | 완료 조건 (검증) |
| --- | --- | --- |
| 0 · UI/UX 확정 | HTML 시안 4화면(완료). 색·레이아웃·동의/Skip 동작 확정 | 사용자 승인 |
| 1 · 정적 UI 이식 | FAB 버튼 추가(`dashboard.html`, `viewer.html`), `templates/user/simulation_setup.html` · `simulation.html` · `simulation_transcript.html` · `simulation_feedback.html`을 시안 그대로 Jinja2로 이식, 라우터는 목(mock) JSON 반환 | 로그인 후 업로드 → FAB → 4화면을 목 데이터로 끝까지 클릭 가능. Playwright 스모크 1건 |
| 2 · 데이터·페르소나 | 테이블 4개 + 마이그레이션, HACHIMI 샘플 적재 스크립트(`scripts/load_personas.py`), `personas` API, 세션 생성, 번안 프롬프트 | 무작위/직접 선택으로 세션 생성 시 `simulation_personas`에 원본·번안본 저장. 단위 테스트: 번안 출력 스키마 검증, 가명 고유성 |
| 3 · 시뮬레이션 코어 | 국면 분해, `enter` / `say` / `advance` / `finish`, 구조화 응답, 메시지 저장·복원 | 4명 기준 국면 진입 반응 10초 이내. 새로고침 후 대화 복원. 전원 동의 전 `advance(agree)` 409. 통합 테스트: Gemini mock으로 국면 5개 완주 |
| 4 · 피드백·운영 | `feedback` 생성·캐시, Markdown 저장, `report_viewer` 연결, 대시보드 "지난 세션" 목록, 관리자 로그·export | 피드백 3섹션 + 위험 요약 생성. 보고서 이모지 검사(`scripts/check_no_emojis_in_reports.py`) 통과 |
| 5 · 확장(선택) | 모둠 다중 화자 대화, SSE 스트리밍, 페르소나 없음 조건 비교(연구용 A/B) | 별도 PRD |

**Phase 1을 먼저 두는 이유.** 시안의 좌석 그리드·동의 카운터·하단 고정 입력창은 데스크톱과 모바일에서 실제 Jinja2 레이아웃(`base.html`의 nav, container 폭)과 충돌 여부를 먼저 봐야 한다. 기능보다 레이아웃이 먼저 깨진다.

## 10. 비기능 요구사항과 리스크

| 항목 | 요구 / 리스크 | 대응 |
| --- | --- | --- |
| 비용 | 세션 1회 ≈ 국면 5 × 페르소나 4 × (진입 1 + 교사 발화 평균 2) ≈ 60회 호출 + 피드백 1회. flash-lite 기준 수백 원 수준이나 사용자 수에 비례 | 인원 상한 6, 세션당 교사 발화 상한(기본 40회, 설정값), 피드백 1회 캐시 |
| 지연 | 국면 진입 시 N명 응답을 기다려야 함 | 페르소나별 병렬 호출, 좌석마다 typing 표시, 429 시 기존 재시도 데코레이터 |
| 해석 한계 | 생성 반응을 실제 학생 행동으로 오해 (논문 §5) | 설정·피드백 화면 고정 문구, 피드백 프롬프트의 단정 금지 제약, 보고서 제목에 "가설" 명시 |
| 과잉 협조 | 지원 필요 학생이 너무 유능하게 반응 (§4.2 부정 사례) | `sim_student` 제약 (5), `ready_for_next` 보수적 판정 규칙 |
| 편향 | 환경결정론·지역 고정 이미지(사막-낙타) 재생산 (§4.4) | 피드백 프롬프트가 반례 자료 추가를 권고. 학업 수준을 색으로 표시하지 않음 |
| 데이터 라이선스 | HACHIMI-1M 샘플은 MIT. 전체 데이터셋은 "곧 공개" 상태 | 샘플 10k만 사용, 출처를 설정 화면에 표기. 전체 공개 시 적재 스크립트만 교체 |
| 개인정보 | 페르소나는 합성 데이터이나 가명이 실제 학생과 겹칠 수 있음 | 가명 풀을 흔한 이름으로 제한하고 성(姓)을 붙이지 않음. 교사 발화에 실명이 들어가도 저장은 하되 export 시 관리자 확인 |
| 재현성 | 동일 입력에 다른 출력 (논문도 재현성을 전제하지 않음) | 메시지별 모델·temperature·latency 저장, seed로 페르소나 추출 재현 |
| 기존 코드 영향 | `CLAUDE.md`의 수술적 변경 원칙 | 기존 파일 변경은 FAB 버튼·라우터 등록·설정값·프롬프트 섹션으로 한정 |

## 11. 열린 질문

- [ ] 국면 분해를 Gemini 자동 + 사용자 수정으로 할지, 업로드 직후 항상 사용자 확인 단계를 둘지 (자동 분해가 틀리면 전체 시뮬레이션이 어긋남)
- [ ] 학생 응답을 국면 진입 시 자동 생성할지, 교사가 첫 발화를 해야 생성할지 (시안은 자동 생성)
- [ ] `ready_for_next`를 학생 JSON 필드로 둘지, 별도 판정 호출(`sim_agree`)로 분리할지 — 전자가 호출 수 절반
- [ ] 피드백 보고서를 기존 `analysis_reports` 테이블에 `kind='simulation'`으로 넣을지, `simulation_sessions`에 경로만 둘지 (PRD는 후자)
- [ ] HACHIMI 영어 샘플을 쓸지 중국어 샘플을 쓸지 — 번안 프롬프트 품질에 영향. 영어 샘플 기본
- [ ] 모둠 다중 화자 대화(논문 집단 수준)를 MVP에 넣을지 — 현재 Phase 5
- [ ] 교사 발화 상한(40회)과 페르소나 상한(6명) 수치 확정

## 참고

- 이용한, 심재권. 예비교사의 수업설계를 위한 LLM 기반 학생 페르소나 시뮬레이션의 가능성 탐색. 한국컴퓨터교육학회 하계 학술발표논문집 30(2), 2026.
- [HACHIMI-1M 데이터셋 (Hugging Face)](https://huggingface.co/datasets/sii-research/HACHIMI-1M) — 샘플 10k, JSONL, MIT
- [DomineYH/elp\_gemini](https://github.com/DomineYH/elp_gemini) — 기존 시스템
- 이용한, 심재권. RAG 기반 LLM을 활용한 수업 과정안 자동평가 프레임워크 설계. 융합과학기술사회연구 3(2), 2024.
