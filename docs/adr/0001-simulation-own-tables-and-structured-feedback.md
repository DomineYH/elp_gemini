# 수업 시뮬레이션은 전용 테이블을 쓰고 피드백은 구조화 JSON으로 저장한다

QnA의 `chat_sessions`/`chat_messages`는 화자 2명(user/assistant) 전용이고 `analysis_reports`는 업로드당 보고서 1건 유니크를 전제하므로, 시뮬레이션(화자 N명, 국면·페르소나 메타, 지도안당 세션 N개)은 `simulation_*` 전용 테이블에 둔다. 시뮬레이션 피드백은 시안이 카드·탭 구조라 Markdown을 파싱하지 않고 `response_schema`로 받은 JSON을 `simulation_sessions.feedback_json`에 저장하고, Markdown은 그 JSON에서 렌더해 기존 `ReportStorageService`로 `app/static/reports/`에 저장한다(이모지 검사·관리자 export가 그 경로만 보기 때문).

## Considered Options

- `analysis_reports`에 `kind='simulation'` 행 추가: 컬럼 의미(`lessonplan_filename`, `upload_id` 유니크)가 어긋나고 "내 보고서" 목록에 섞인다. 기각.
- `report_viewer.html` 재사용: JSON 소스 URL이 `/api/lessonplan/reports/{id}`로 고정. 기각.

결정 근거: https://github.com/DomineYH/elp_gemini/issues/136
