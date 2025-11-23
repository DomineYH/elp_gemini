# 수업 지도안 분석 시 `rubricstore` 활용 리뷰 보고서

## 1. 개요 (Executive Summary)
- 수업 지도안 분석 흐름에서 `file_search_tool` 호출 시 `rubricstore`를 명시적으로 포함하고 있으며, 사용자별 스토어와 함께 검색하도록 구현되어 있습니다.
- 동일한 스토어 결합 패턴이 QnA 서비스에도 적용되어 아키텍처 일관성을 유지하지만, 스토어 조회 로직이 중복되고 오류·캐싱 처리 보완 여지가 있습니다.

## 2. 분석 방법론
- 대상 파일: `app/services/lessonplan_analysis_service.py`, `app/services/qna_service.py`
- 코드 리딩으로 `GenerateContent` 호출부, 스토어 ID 조회 함수, 평가기준 벡터 검색 흐름을 확인.
- 라인 번호는 `nl -ba` 기준이며, 실제 호출 순서·도구 전달 여부를 교차 검증.

## 3. 상세 분석 결과
### 3.1 rubricstore 활용 확인
- `lessonplan_analysis_service.analyze_lesson_plan`에서 File Search 호출 시 `store_ids`에 `rubricstore`가 포함됨: `app/services/lessonplan_analysis_service.py:67-120`.
- `store_ids` 구성 과정에서 `rubricstore`를 먼저 탐색해 리스트에 넣고, 이후 사용자 스토어를 추가: `app/services/lessonplan_analysis_service.py:154-186`.

### 3.2 코드 구현 분석
```python
# app/services/lessonplan_analysis_service.py:154-180
store_ids = []
# rubricstore: 평가기준 문서
for store in self.file_search_service.client.file_search_stores.list():
    if "rubricstore" in store.display_name.lower():
        store_ids.append(store.name)
        break
# user-{username}-store: 사용자 수업지도안
user_store_name = f"user-{username}-store"
for store in self.file_search_service.client.file_search_stores.list():
    if user_store_name in store.display_name.lower():
        store_ids.append(store.name)
        break
```
- 위에서 수집된 `store_ids`를 그대로 Gemini `GenerateContent`의 `file_search.file_search_store_names`로 전달해 rubricstore와 사용자 스토어를 동시에 검색: `app/services/lessonplan_analysis_service.py:87-101`.
- 평가기준 벡터 검색(`CriteriaContextService`) 결과는 프롬프트 참고 자료로만 사용되고, 실제 근거 검색은 File Search로 두 스토어를 모두 참조하는 구조.

### 3.3 아키텍처 패턴 분석
- **이중 검색**: (1) 벡터 검색으로 평가기준 컨텍스트 확보(`_get_criteria_context`), (2) File Search로 rubricstore+사용자 스토어 검색.
- **프롬프트 결합**: 벡터 검색 결과를 `[참고 자료: 관련 평가 기준]` 섹션에 삽입한 뒤 File Search를 통해 실질 근거를 수집하는 두 단계 근거 주입 패턴.

## 4. QnA 서비스와의 비교
- `app/services/qna_service.py:119-206`에서 동일하게 `rubricstore` + 사용자 스토어를 `file_search_store_names`로 전달.
- 추가 차이점:
  - rubricstore 미발견 시 `_get_or_create_store`로 생성 시도(라인 136-143).
  - 사용자 스토어도 미존재 시 생성(라인 154-173).
  - 로깅 레벨이 INFO 중심이며, lessonplan 서비스는 rubricstore 발견 로그를 DEBUG로 남김.

## 5. 긍정적인 측면
- 평가기준 원본(`rubricstore`)과 사용자 문서를 동시에 검색해 근거 충실도를 높임.
- 벡터 검색(평가기준 컨텍스트)과 파일 검색(원문 근거) 분리로 답변 품질과 재현성 향상.
- QnA/분석 서비스 간 스토어 사용 패턴을 통일해 유지보수 용이.
- rubricstore 미존재 시 QnA 서비스에서 자동 생성 처리로 운영 안정성 확보.

## 6. 개선 가능한 부분
- **중복 로직**: 두 서비스에서 스토어 조회·생성 로직이 반복됨.
- **에러 처리**: lessonplan 서비스는 rubricstore 미발견 시 조용히 빈 리스트를 반환하여 평가기준 없이 진행될 수 있음.
- **성능/안정성**: 매 호출마다 전체 스토어 목록을 두 번 순회하며, 캐싱·타임아웃·예외 메시지가 부족함.
- **로깅 일관성**: rubricstore 발견 로그 레벨이 서비스마다 다르고, 실패 케이스 로그 메시지 형식도 상이.

## 7. 권장 조치사항
1) FileSearchService에 `get_dual_store_ids(username: str) -> list[str]` 유틸을 추가해 rubricstore + 사용자 스토어 조회/생성을 표준화하고, 두 서비스에서 공통 사용.  
2) rubricstore 미발견 시 명시적 에러 또는 경고를 반환하고, 필요 시 생성 로직을 lessonplan 서비스에도 도입.  
3) 스토어 목록 캐싱(짧은 TTL) 또는 최초 요청 시만 목록 조회하도록 최적화.  
4) 로깅 레벨·메시지 포맷을 INFO/DEBUG 기준으로 통일하고, 실패 시 사용자 영향도와 폴백 경로를 명시.

## 8. 결론
- 현재 구현은 수업 지도안 분석 보고서 작성 시 `file_search_tool`에서 `rubricstore`를 적극 활용하며, 사용자 스토어와 병렬 검색하도록 설계되어 있습니다.  
- 다만 스토어 조회/생성 로직 중복과 일부 에러 처리·로깅 미비가 있으므로, 공통 유틸 추출과 예외·캐싱 보강을 진행하면 안정성과 유지보수성이 개선됩니다.
