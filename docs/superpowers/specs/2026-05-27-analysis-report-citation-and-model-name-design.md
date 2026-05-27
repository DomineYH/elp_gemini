# 분석 보고서 - 참고 문서 결정론적 표시 및 모델명 노출 제거

- 작성일: 2026-05-27
- 작성자: Claude (with DomineYH)
- 관련 코드: `app/services/lessonplan_analysis_service.py`, `prompt/prompt.md`
- 관련 이슈: TBD (이 문서 등록 후 채움)

## 1. 배경

수업 지도안 분석 보고서(`lesson_analysis`)는 Gemini가 생성한 Markdown 보고서로, 보고서 말미에 `### File Search 참고 문서` 섹션이 포함된다. 현재 두 가지 문제가 있다.

1. **참고 문서 신뢰성 문제**
   `File Search 참고 문서` 섹션의 항목은 LLM이 자유 형식으로 생성한다. 그 결과 (a) 표시 이름이 누락되거나 (b) 활성화된 평가기준이 아닌 다른 문서가 섞이거나 (c) 같은 평가기준의 별칭이 매번 달라지는 등 결정론적이지 않다. 사용자는 "지금 어떤 평가기준이 분석에 적용되었는가?"를 보고서에서 신뢰성 있게 확인할 수 없다.

2. **모델명 노출**
   보고서 상단의 `**분석 모델**: {model_name}` 줄은 내부 모델 식별자를 사용자에게 그대로 노출한다. 이는 정보 가치가 낮고, 모델 교체 시점이 보고서마다 노출되어 일관성을 저해한다.

## 2. 목표 및 비목표

### 2.1 목표

- `File Search 참고 문서` 섹션에 **현재 활성화된 평가기준의 표시 이름(alias)** 과 **분석 대상 수업 지도안의 원본 파일명**을 결정론적으로 표시한다.
- 보고서에서 모델명 줄을 제거한다.
- 신규 분석부터 적용한다. 이미 디스크에 저장된 과거 보고서는 변경하지 않는다.

### 2.2 비목표

- 과거 보고서 마이그레이션은 수행하지 않는다.
- 보고서 양식의 다른 섹션은 변경하지 않는다.
- 분석 일시(`분석 일시: ...`) 표시는 그대로 유지한다.
- 평가기준의 alias 자체를 변경하거나 정렬 정책을 새로 도입하지 않는다 (기존 `_get_active_stable_ids`의 정렬 정책을 따른다 — `activated_at` 내림차순).

## 3. 설계

### 3.1 전체 흐름

```
[Gemini 응답]
   ↓ raw_report
[_post_process_report]
   ↓ (1) 기존: Vector Search 참고 자료 정리
   ↓ (2) 신규: File Search 참고 문서 섹션 서버 렌더로 치환
   ↓ (3) 기존: 이모지/픽토그램 살균
[최종 보고서]
```

### 3.2 데이터 소스

활성 평가기준 표시 이름은 `CriteriaAliasMapService.fetch()`가 반환하는 `AliasMap.entries`에서 얻는다. 이미 `analyze_lesson_plan`에서 `CriteriaVectorService.active_stable_id_filter`가 동일한 fetch를 호출한다. 같은 데이터를 재활용하여 추가 API 호출을 피한다.

- 필터링: `entry.status == "active"` 이며 `is_legacy_surrogate_stable_id(stable_id)` 가 False인 항목만.
- 정렬: `(activated_at, stable_id)` 내림차순. 기존 `_get_active_stable_ids`와 동일.
- 표시 값: `entry.alias`. `None` 또는 빈 문자열이면 해당 항목은 표시 목록에서 **제외**한다 (alias 없는 평가기준은 사용자에게 보여줄 이름이 없는 비정상 상태).
  - 정상적인 평가기준 관리 흐름에서는 alias가 항상 존재해야 한다. alias 누락은 운영 이슈로 별도 관찰 필요 — 본 변경은 누락된 경우 안전하게 침묵하고 로그로만 남긴다.

수업 지도안 표시 값은 `latest_upload.original_filename`을 사용한다. `analyze_lesson_plan` 흐름에서 이미 확보된 값이다.

### 3.3 새 헬퍼

`LessonPlanAnalysisService`에 다음 두 헬퍼를 추가한다.

```python
async def _collect_active_criteria_display_names(self) -> list[str]:
    """alias_map에서 active 평가기준의 display name(alias)을 가져와
    activated_at 내림차순으로 정렬해 반환한다. alias가 None/빈 항목은 제외."""
```

```python
def _render_file_search_references_section(
    self,
    criteria_aliases: list[str],
    lessonplan_original_filename: Optional[str],
) -> str:
    """### File Search 참고 문서 섹션의 본문(헤더 제외) 마크다운을 생성한다.
    - 활성 평가기준 표시 이름들
    - 수업 지도안 원본 파일명 (있을 경우)
    빈 입력에 대해서는 '(표시할 항목이 없습니다)' placeholder를 반환한다."""
```

### 3.4 후처리 변경

`_post_process_report`는 현재 다음을 수행한다.

1. `### Vector Search 참고 자료` 섹션을 목록화
2. 이모지/픽토그램 살균

여기에 단계 (1)과 (2) 사이에 **신규 단계**를 추가한다.

3. `### File Search 참고 문서` 섹션 본문을 서버 렌더 콘텐츠로 치환

검출 정규식 (기존 패턴과 동형):

```python
pattern = (
    r'(###\s*(?:[^\n]*?)?File Search 참고 문서\s*\n)'
    r'(.*?)(\n###|\Z)'
)
```

처리:

- 헤더 라인은 그대로 유지.
- 본문은 `_render_file_search_references_section`의 반환값으로 치환.
- 다음 섹션 경계(`\n###` 또는 문서 끝)는 보존.
- 만약 섹션 자체가 검출되지 않으면, 보고서 끝에 새 섹션을 부착한다 (LLM이 섹션을 누락한 fallback).

후처리에 필요한 데이터(`criteria_aliases`, `lessonplan_original_filename`)는 `_post_process_report`의 새 인자로 전달한다. 호출 지점은 `analyze_lesson_plan` 내부 한 곳뿐이므로 변경 범위가 작다.

### 3.5 모델명 제거

#### 3.5.1 프롬프트 템플릿 (`prompt/prompt.md`)

```diff
 > **분석 개요**
 > - **분석 일시**: [YYYY-MM-DD HH:MM]
-> - **분석 모델**: {model_name}
```

`> **분석 개요**` 블록은 유지하고 `**분석 모델**` 줄만 삭제한다.

#### 3.5.2 코드 (`_build_analysis_prompt`)

```diff
- # 모델 이름 플레이스홀더 치환
- system_prompt = system_prompt.replace(
-     "{model_name}", self.model_name
- )
```

이 두 줄을 제거한다. `self.model_name`은 다른 곳(`generate_content`)에서 여전히 사용되므로 필드 자체는 유지.

#### 3.5.3 잔여 안전망

LLM이 학습된 패턴으로 `**분석 모델**:` 줄을 자체적으로 생성할 가능성이 있다. 후처리에서 다음 정규식 라인을 한 번 제거한다.

```python
report = re.sub(
    r'^\s*>\s*-\s*\*\*분석 모델\*\*\s*:.*$\n?',
    '',
    report,
    flags=re.MULTILINE,
)
```

`_post_process_report`의 가장 앞부분 (다른 섹션 처리 전)에서 1회 적용한다.

### 3.6 동작 매트릭스

| 상황 | File Search 참고 문서 | 모델명 줄 |
|---|---|---|
| 활성 평가기준 N개, 수업지도안 정상 | "- alias1\n- alias2\n... \n- 원본파일명.pdf" | 제거됨 |
| 활성 평가기준 0개 | (이 분기는 `analyze_lesson_plan`에서 `NO_ACTIVE_CRITERIA`로 조기 종료하여 보고서 자체가 생성되지 않음) | n/a |
| 활성 평가기준 있으나 모두 alias 누락 | "- 원본파일명.pdf" + WARNING 로그 | 제거됨 |
| 수업지도안 파일명 미상 (legacy) | "- alias1\n- alias2" | 제거됨 |
| LLM이 섹션 누락 | 보고서 끝에 새 섹션 추가 | 제거됨 |
| LLM이 모델명 줄 자체 생성 | n/a | 후처리 정규식으로 제거 |

## 4. 영향 범위

### 4.1 변경되는 파일

- `prompt/prompt.md` — 모델명 줄 1개 삭제
- `app/services/lessonplan_analysis_service.py`
  - `_build_analysis_prompt`: `{model_name}` 치환 코드 제거
  - `_post_process_report`: 새 단계 추가, 시그니처에 `criteria_aliases`, `lessonplan_original_filename` 인자 추가
  - 헬퍼 신규 추가: `_collect_active_criteria_display_names`, `_render_file_search_references_section`
  - `analyze_lesson_plan`: alias 수집 호출 추가, `_post_process_report` 호출 시 새 인자 전달

### 4.2 변경되지 않는 부분

- DB 스키마 변경 없음
- API 응답 스키마 변경 없음 (`report` 문자열 내용만 바뀜)
- 보고서 파일 저장 경로/형식 변경 없음
- 기타 보고서 섹션(평가 항목 1~5, 종합 평가 등) 처리 로직 변경 없음

### 4.3 호환성

- 과거 보고서는 디스크의 .md 파일 그대로 유지. 조회 시점에도 별도 처리 없음.
- 신규 보고서만 새 표시 양식을 따른다.

## 5. 검증 계획

### 5.1 단위 테스트

`tests/unit/services/test_lessonplan_analysis_service.py`에 다음 케이스 추가:

1. `_render_file_search_references_section`
   - 평가기준 alias 2개 + lessonplan 파일명 → 3개 항목 마크다운 반환
   - 평가기준 alias 0개 + lessonplan 파일명 → 1개 항목 마크다운 반환
   - 평가기준 alias 0개 + lessonplan 없음 → placeholder 반환
2. `_post_process_report` (신규 단계만)
   - `### File Search 참고 문서` 섹션이 LLM 출력에 포함된 경우 → 본문이 서버 렌더 콘텐츠로 교체됨
   - LLM이 섹션을 생성하지 않은 경우 → 보고서 끝에 추가됨
   - LLM이 `**분석 모델**: ...` 줄을 출력한 경우 → 라인 제거됨
3. `_collect_active_criteria_display_names`
   - alias_map 활성 항목 정렬 결과의 alias 추출
   - alias가 None인 항목은 제외
   - alias_map fetch 실패 시 빈 리스트 반환 (예외 안 던짐)

### 5.2 통합 테스트

기존 `analyze_lesson_plan` 통합 테스트(있다면)에 대해, 모킹된 Gemini 응답이 모델명 줄을 포함하고 임의의 "File Search 참고 문서" 섹션을 포함하더라도 최종 보고서가 양 변경을 모두 반영하는지 1개 케이스 추가.

### 5.3 수동 검증

- 활성 평가기준 2개 + 수업지도안 업로드 후 분석 → 보고서에서 두 alias가 표기되는지 확인
- 활성 평가기준 1개 토글 OFF → 다시 분석 → 보고서에서 해당 alias 사라지는지 확인
- 모델명 줄이 보이지 않는지 확인

## 6. 위험 및 완화

| 위험 | 완화 |
|---|---|
| alias_map fetch에 추가 시간이 들어 분석 지연 | 이미 `active_stable_id_filter` 호출에서 fetch 중. 새 헬퍼는 동일 호출을 재사용하므로 추가 비용 미미. 필요하면 함께 호출하여 1회만 수행. |
| LLM이 후처리 검출 패턴을 우회하는 변형 헤더 생성 (예: `### 📁 File Search 참고 문서`) | 정규식이 이모지/접두사를 허용한다 (`Vector Search 참고 자료` 패턴과 동일). 추가로 살균 단계에서 이모지가 제거되어 일관성 유지. |
| 모델명 줄 제거 정규식이 본문 내 무관한 라인 매칭 | `> - **분석 모델**:` 형태는 보고서 표준 헤더에서만 사용되므로 충돌 가능성 낮음. 단위 테스트로 회귀 방지. |
| 표시 이름(alias)이 너무 길어 보고서 시각 품질 저하 | `AliasMapEntry.alias`는 max 255자. 변경 없음. UI 처리는 별도 이슈. |

## 7. 향후 작업 (별도 이슈)

- 과거 보고서에 대한 일회성 마이그레이션 스크립트 (사용자 요구가 있을 경우)
- 보고서 헤더 블록 전체를 서버 측에서 렌더하도록 확장 (현재는 분석 일시만 LLM이 채움)
