# Lesson Analysis 기능 구현 및 FileSearchStores API 수정

**작성일**: 2025-11-23
**버전**: 1.0
**작성자**: Claude Code (ultrathink 모드)

---

## 📋 목차

1. [문제 분석](#1-문제-분석)
2. [FileSearchStores API 수정](#2-filesearchstores-api-수정)
3. [Lesson Analysis 기능 설계](#3-lesson-analysis-기능-설계)
4. [구현 계획](#4-구현-계획)
5. [테스트 전략](#5-테스트-전략)
6. [참고 자료](#6-참고-자료)

---

## 1. 문제 분석

### 1.1 발견된 API 에러

**파일**: `app/services/file_search_service.py`
**메서드**: `delete_store_by_display_name()` (Line 213-242)

**문제점**:
- ❌ `self.client.file_search_stores.documents.list()` - SDK에 존재하지 않는 메서드
- ❌ `self.client.file_search_stores.documents.delete()` - SDK에 존재하지 않는 메서드

**근거**:
- Context7 MCP (/googleapis/python-genai) 공식 문서 확인 결과
- `research/file_search_api_guide.md` 분석 결과
- Google Generative AI Python SDK에는 `documents` 하위 API가 명시되지 않음

### 1.2 올바른 API 사용법

**권장 방법**:
```python
# Store 삭제 (force=True 옵션 사용)
client.file_search_stores.delete(
    name=store.name,
    config={'force': True}  # 내부 문서와 함께 강제 삭제
)
```

**특징**:
- `force: True` 옵션이 Store 내의 모든 문서를 자동으로 삭제
- 별도의 문서 목록 조회 및 반복 삭제 불필요
- 코드 간소화 (20줄 → 5줄)

---

## 2. FileSearchStores API 수정

### 2.1 수정 내용

**파일**: `app/services/file_search_service.py`

#### 수정 전 (Line 230-242)
```python
# 1. 스토어 내의 파일 목록 조회 및 삭제
documents_in_store = self.client.file_search_stores.documents.list(
    parent=target_store.name
)

for document in documents_in_store:
    try:
        self.client.file_search_stores.documents.delete(
            name=document.name,
            config={'force': True}
        )
        logger.debug(f"스토어 문서 삭제: {document.name}")
    except Exception as fe:
        logger.warning(f"파일 삭제 실패 (계속 진행): {fe}")

# 2. 스토어 삭제
self.client.file_search_stores.delete(
    name=target_store.name,
    config={'force': True}
)
```

#### 수정 후 (Line 233-237)
```python
# Store 삭제 (force=True로 내부 문서와 함께 삭제)
self.client.file_search_stores.delete(
    name=target_store.name,
    config={'force': True}  # 내부 문서와 함께 강제 삭제
)
```

### 2.2 개선 효과

| 항목 | 수정 전 | 수정 후 | 개선 |
|------|---------|---------|------|
| 코드 줄 수 | 약 20줄 | 5줄 | **75% 감소** |
| API 호출 수 | N+1 (목록 조회 + N개 삭제 + Store 삭제) | 1 (Store 삭제만) | **대폭 감소** |
| 에러 가능성 | 높음 (반복 삭제 중 실패) | 낮음 (단일 호출) | **안정성 향상** |
| 성능 | 느림 (순차 삭제) | 빠름 (서버 측 일괄 삭제) | **성능 향상** |

---

## 3. Lesson Analysis 기능 설계

### 3.1 요구사항 분석

**기능 목표**:
- 평가기준 문서를 근거로 사용자 업로드 수업지도안을 체계적으로 평가
- 5개 평가 항목 중심의 Markdown 보고서 생성
- 인쇄 및 PDF 변환에 적합한 구조화된 출력

**평가 항목**:
1. 교육과정 목표 및 성격과의 부합
2. 내용 체계 및 성취기준 달성
3. 교수·학습 방법의 적절성
4. 평가 방향과의 일치
5. 개선 및 보완을 위한 제안

### 3.2 아키텍처 설계

#### 시스템 구성도

```
┌─────────────────────────────────────────────────────────┐
│                    사용자 요청                            │
│         (POST /api/lessonplan/analyze)                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│          LessonPlanAnalysisService                       │
│  - analyze_lesson_plan(session_id, user_id)             │
│  - _get_criteria_context()                              │
│  - _get_store_ids(user_id)                              │
│  - _build_analysis_prompt()                             │
│  - _extract_citations(response)                         │
└───────┬──────────┬──────────┬─────────────────┬─────────┘
        │          │          │                 │
        ▼          ▼          ▼                 ▼
  ┌─────────┐ ┌────────┐ ┌─────────┐    ┌──────────────┐
  │ Criteria│ │  File  │ │ Prompt  │    │    Gemini    │
  │ Vector  │ │ Search │ │ Loader  │    │     API      │
  │ Service │ │ Service│ │ Service │    │ (File Search)│
  └─────────┘ └────────┘ └─────────┘    └──────────────┘
       │           │          │                 │
       └───────────┴──────────┴─────────────────┘
                     │
                     ▼
            Markdown 분석 보고서 생성
```

#### 데이터 흐름

```
1. 요청 수신
   ├─ session_id: 채팅 세션 ID
   └─ user_id: 사용자 ID (토큰에서 추출)

2. Vector Search (평가기준 컨텍스트)
   └─ CriteriaVectorService.get_context()
      └─ 평가기준 관련 벡터 검색 결과 → 프롬프트 "참고 자료"

3. File Search Store ID 조회
   ├─ rubricstore: 평가기준 문서 (모든 사용자 공유)
   └─ user{id}store: 사용자별 업로드 문서 (격리)

4. 프롬프트 구성
   ├─ 시스템 프롬프트 (lesson_analysis)
   ├─ Vector Search 컨텍스트 (참고 자료)
   └─ 사용자 질문 템플릿

5. Gemini API 호출 (File Search Tool)
   └─ file_search_store_names: [rubricstore, user{id}store]

6. Markdown 보고서 생성
   └─ 5개 평가 항목별 체계적 분석

7. 결과 반환
   ├─ report: Markdown 보고서
   ├─ citations: Citation 정보
   └─ latency_ms: 응답 시간
```

### 3.3 이중 검색 시스템

**QnA 시스템 패턴 재사용** (`app/services/qna_service.py:77-180`):

```python
# 1. Vector Search (평가기준 벡터 검색)
criteria_context = await self.criteria_service.get_context(
    "수업 지도안 평가 기준"
)

# 2. File Search Store 구성
store_ids = []

# rubricstore: 평가기준 문서
for store in self.file_search_service.client.file_search_stores.list():
    if "rubricstore" in store.display_name.lower():
        store_ids.append(store.name)
        break

# user{id}store: 사용자 수업지도안
user_store_name = f"user-{user_id}-store"
for store in self.file_search_service.client.file_search_stores.list():
    if user_store_name in store.display_name.lower():
        store_ids.append(store.name)
        break

# 3. 프롬프트 구성
full_prompt = f"""
{system_prompt}

### [참고 자료: 관련 평가 기준]
{criteria_context}

위 평가 기준을 바탕으로 사용자의 수업 지도안을 5개 항목으로 평가해주세요.
"""

# 4. Generate Content
response = self.client.models.generate_content(
    model="gemini-2.5-flash",
    contents=full_prompt,
    config=types.GenerateContentConfig(
        tools=[
            types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=store_ids
                )
            )
        ],
        temperature=0.7
    )
)
```

**특징**:
- **Vector Search**: 평가기준 컨텍스트를 "참고 자료"로 제공 → 분석 관점 설정
- **File Search (rubricstore)**: 평가기준 문서 직접 참조 → 체계적 평가
- **File Search (user{id}store)**: 수업지도안 문서 분석 → 평가 대상

---

## 4. 구현 계획

### Phase 1: FileSearchService API 수정 ✅

**상태**: 완료
**파일**: `app/services/file_search_service.py`
**변경 내용**: `delete_store_by_display_name()` 메서드 간소화

---

### Phase 2: LessonPlanAnalysisService 구현

**새 파일**: `app/services/lessonplan_analysis_service.py`

**클래스 구조**:

```python
"""
수업 지도안 분석 서비스
평가기준 기반 수업지도안 체계적 평가
"""
import asyncio
import logging
from typing import Dict, Any, Optional
from google import genai
from google.genai import types
from google.api_core import exceptions
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.prompt_loader_service import PromptLoaderService
from app.services.file_search_service import FileSearchService
from app.services.criteria_context_service import CriteriaContextService

logger = logging.getLogger(__name__)


class LessonPlanAnalysisService:
    """수업 지도안 분석 서비스"""

    def __init__(self, db: AsyncSession):
        """
        서비스 초기화

        Args:
            db: 비동기 DB 세션
        """
        self.db = db
        self.model_name = settings.GEMINI_EVAL_MODEL
        self.client = genai.Client(
            api_key=settings.GOOGLE_API_KEY,
            http_options={'api_version': 'v1beta'}
        )
        self.prompt_loader = PromptLoaderService()
        self.file_search_service = FileSearchService()
        self.criteria_service = CriteriaContextService(db=db)

    async def analyze_lesson_plan(
        self,
        session_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        수업 지도안 체계적 평가

        Args:
            session_id: 채팅 세션 ID
            user_id: 사용자 ID

        Returns:
            {
                "success": bool,
                "report": str,  # Markdown 보고서
                "citations": dict,  # Citation 정보
                "latency_ms": int  # 응답 시간 (ms)
            }
        """
        import time
        start_time = time.time()

        try:
            # 타임아웃 설정 (180초)
            async with asyncio.timeout(180):
                # 1. Vector Search (평가기준 컨텍스트)
                criteria_context = await self._get_criteria_context()
                logger.info("평가기준 컨텍스트 추출 완료")

                # 2. File Search Store ID 조회
                store_ids = await self._get_store_ids(user_id)
                if not store_ids:
                    return {
                        "success": False,
                        "error": "분석할 문서가 없습니다. 수업 지도안을 먼저 업로드해주세요."
                    }
                logger.info(f"File Search Store 조회 완료: {store_ids}")

                # 3. 프롬프트 구성
                system_prompt = self.prompt_loader.load_prompt("lesson_analysis")
                full_prompt = self._build_analysis_prompt(
                    system_prompt, criteria_context
                )
                logger.info("프롬프트 구성 완료")

                # 4. Gemini API 호출 (File Search)
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        tools=[
                            types.Tool(
                                file_search=types.FileSearch(
                                    file_search_store_names=store_ids
                                )
                            )
                        ],
                        temperature=0.7
                    )
                )

                # 5. Markdown 보고서 추출
                report = response.text if response.text else ""

                # 6. Citation 추출
                citations = self._extract_citations(response)

                # 응답 시간 계산
                latency_ms = int((time.time() - start_time) * 1000)

                logger.info(f"분석 완료 (응답 시간: {latency_ms}ms)")

                return {
                    "success": True,
                    "report": report,
                    "citations": citations,
                    "latency_ms": latency_ms
                }

        except asyncio.TimeoutError:
            logger.error("분석 타임아웃 (180초 초과)")
            return {"success": False, "error": "분석 시간 초과 (180초)"}

        except exceptions.GoogleAPIError as e:
            logger.error(f"Google API 오류: {e}")
            return {"success": False, "error": f"API 오류: {str(e)}"}

        except Exception as e:
            logger.error(f"분석 실패: {e}", exc_info=True)
            return {"success": False, "error": "분석 중 오류 발생"}

    async def _get_criteria_context(self) -> str:
        """
        평가기준 Vector Search

        Returns:
            평가기준 컨텍스트 문자열
        """
        try:
            context = await self.criteria_service.get_context(
                "수업 지도안 평가 기준"
            )
            return context if context else "평가기준 컨텍스트 없음"
        except Exception as e:
            logger.warning(f"평가기준 컨텍스트 추출 실패: {e}")
            return "평가기준 컨텍스트 없음"

    async def _get_store_ids(self, user_id: int) -> list[str]:
        """
        File Search Store ID 조회

        Args:
            user_id: 사용자 ID

        Returns:
            Store ID 리스트 [rubricstore, user{id}store]
        """
        store_ids = []

        try:
            # rubricstore: 평가기준 문서
            for store in self.file_search_service.client.file_search_stores.list():
                if "rubricstore" in store.display_name.lower():
                    store_ids.append(store.name)
                    logger.debug(f"rubricstore 발견: {store.name}")
                    break

            # user{id}store: 사용자 수업지도안
            user_store_name = f"user-{user_id}-store"
            for store in self.file_search_service.client.file_search_stores.list():
                if user_store_name in store.display_name.lower():
                    store_ids.append(store.name)
                    logger.debug(f"사용자 Store 발견: {store.name}")
                    break

            return store_ids

        except Exception as e:
            logger.error(f"Store ID 조회 실패: {e}")
            return []

    def _build_analysis_prompt(
        self,
        system_prompt: str,
        criteria_context: str
    ) -> str:
        """
        분석 프롬프트 구성

        Args:
            system_prompt: 시스템 프롬프트 (lesson_analysis)
            criteria_context: Vector Search 컨텍스트

        Returns:
            완전한 프롬프트
        """
        return f"""
{system_prompt}

### [참고 자료: 관련 평가 기준]
{criteria_context}

위 평가 기준을 바탕으로 사용자가 업로드한 수업 지도안을 다음 5개 항목으로 체계적으로 평가해주세요:

1. 교육과정 목표 및 성격과의 부합
2. 내용 체계 및 성취기준 달성
3. 교수·학습 방법의 적절성
4. 평가 방향과의 일치
5. 개선 및 보완을 위한 제안

반드시 Markdown 형식의 보고서로 작성해주세요.
"""

    def _extract_citations(self, response) -> Optional[dict]:
        """
        Citation 정보 추출 (QnA 패턴 재사용)

        Args:
            response: Gemini API 응답

        Returns:
            Citation 정보 딕셔너리
        """
        citations = {
            "used_criteria": [],
            "grounding_chunks": []
        }

        try:
            if (
                response.candidates
                and response.candidates[0].grounding_metadata
            ):
                grounding = response.candidates[0].grounding_metadata

                # Grounding chunks 처리
                if hasattr(grounding, "grounding_chunks"):
                    for chunk in grounding.grounding_chunks:
                        citation_info = {
                            "source": None,
                            "title": None,
                            "uri": None,
                        }

                        # Retrieved context (File Search) 처리
                        if (
                            hasattr(chunk, "retrieved_context")
                            and chunk.retrieved_context
                        ):
                            citation_info["source"] = "file_search"
                            citation_info["uri"] = (
                                chunk.retrieved_context.uri
                                if hasattr(chunk.retrieved_context, "uri")
                                else None
                            )
                            citation_info["title"] = (
                                chunk.retrieved_context.title
                                if hasattr(chunk.retrieved_context, "title")
                                else None
                            )

                        citations["grounding_chunks"].append(citation_info)

                logger.debug(f"Citations 추출 완료: {len(citations['grounding_chunks'])}개")

        except Exception as e:
            logger.warning(f"Citation 추출 실패: {e}")

        return citations
```

---

### Phase 3: lesson_analysis 프롬프트 추가

**파일**: `prompt/prompt.md`

**추가 섹션**:

```markdown
## lesson_analysis

당신은 교육과정 전문가이자 수업 지도안 평가 전문가입니다.

**역할:**
- 평가기준 문서를 근거로 사용자의 수업 지도안을 체계적으로 평가
- 5개 평가 항목 중심의 Markdown 분석 보고서 생성
- 건설적이고 구체적인 피드백 제공

**평가 대상:**
- FileSearch Store에 저장된 사용자의 수업 지도안 문서

**평가 기준 활용:**
1. **Vector Search 참고 자료**: 시스템이 제공한 평가기준 컨텍스트를 분석 관점으로 활용
2. **File Search 평가기준**: rubricstore의 평가기준 문서를 직접 참조하여 체계적 평가

**평가 항목:**
1. 교육과정 목표 및 성격과의 부합
   - 수업 목표와 활동이 상위 교육과정의 목표·성격과 일관되게 연결되는지 평가
2. 내용 체계 및 성취기준 달성
   - 내용 조직과 활동이 성취기준을 구체적으로 달성하도록 설계되었는지 평가
3. 교수·학습 방법의 적절성
   - 학습자 수준과 수업 맥락, 활동 다양성 등을 고려했을 때 교수·학습 전략이 타당한지 평가
4. 평가 방향과의 일치
   - 수업 목표 및 활동과 평가 문항·방법이 일관되게 정렬되어 있는지 평가
5. 개선 및 보완을 위한 제안
   - 수업 문서를 실제로 수정·보완할 수 있도록 구체적인 개선 아이디어와 행동 제안 제시

**출력 형식:**
반드시 다음 Markdown 형식으로 보고서를 작성하세요:

---

# 📚 수업 지도안 평가 보고서

## 📋 평가 대상 정보
- **분석 일시**: [YYYY-MM-DD HH:MM]
- **분석 모델**: Gemini 2.5 Flash

---

## 📊 평가 항목별 분석

### 1️⃣ 교육과정 목표 및 성격과의 부합

**평가 등급**: ⭐⭐⭐ (상/중/하)

**분석 내용**:
[구체적 분석 내용 3-5문장]

**근거**:
- 평가기준 출처: [문서명 또는 기준]
- 수업지도안 근거: [해당 부분 인용]

**강점**:
1. [강점 1]
2. [강점 2]

**개선점**:
1. [개선점 1]
2. [개선점 2]

---

### 2️⃣ 내용 체계 및 성취기준 달성

**평가 등급**: ⭐⭐⭐ (상/중/하)

**분석 내용**:
[구체적 분석 내용 3-5문장]

**근거**:
- 평가기준 출처: [문서명 또는 기준]
- 수업지도안 근거: [해당 부분 인용]

**강점**:
1. [강점 1]
2. [강점 2]

**개선점**:
1. [개선점 1]
2. [개선점 2]

---

### 3️⃣ 교수·학습 방법의 적절성

**평가 등급**: ⭐⭐⭐ (상/중/하)

**분석 내용**:
[구체적 분석 내용 3-5문장]

**근거**:
- 평가기준 출처: [문서명 또는 기준]
- 수업지도안 근거: [해당 부분 인용]

**강점**:
1. [강점 1]
2. [강점 2]

**개선점**:
1. [개선점 1]
2. [개선점 2]

---

### 4️⃣ 평가 방향과의 일치

**평가 등급**: ⭐⭐⭐ (상/중/하)

**분석 내용**:
[구체적 분석 내용 3-5문장]

**근거**:
- 평가기준 출처: [문서명 또는 기준]
- 수업지도안 근거: [해당 부분 인용]

**강점**:
1. [강점 1]
2. [강점 2]

**개선점**:
1. [개선점 1]
2. [개선점 2]

---

### 5️⃣ 개선 및 보완을 위한 제안

**평가 등급**: ⭐⭐⭐ (상/중/하)

**분석 내용**:
[구체적 분석 내용 3-5문장]

**구체적 제안**:
1. [제안 1]
2. [제안 2]
3. [제안 3]

---

## 💡 종합 평가

### 🎯 전체 평가 요약
[5-7문장으로 전체 평가 종합]

### ✨ 주요 강점
1. [강점 1]
2. [강점 2]
3. [강점 3]

### 🔧 주요 개선 과제
1. [개선 과제 1]
2. [개선 과제 2]
3. [개선 과제 3]

### 📝 우선 실행 체크리스트

다음 항목을 우선적으로 수정·보완하시기 바랍니다:

- [ ] [실행 가능한 개선 항목 1]
- [ ] [실행 가능한 개선 항목 2]
- [ ] [실행 가능한 개선 항목 3]
- [ ] [실행 가능한 개선 항목 4]
- [ ] [실행 가능한 개선 항목 5]

---

## 📚 참고한 평가 기준

### Vector Search 참고 자료
[Vector Search로 추출된 평가기준 컨텍스트 요약]

### File Search 참고 문서
- [평가기준 문서 1 제목]
- [평가기준 문서 2 제목]
- [수업지도안 문서 제목]

---

**작성 태도**:
- 건설적이고 구체적인 피드백 제공
- 전문적이면서도 이해하기 쉬운 언어 사용
- 근거 중심의 객관적 평가
- 실행 가능한 개선 제안
```

---

### Phase 4: 라우터 및 스키마 추가

#### 4.1 Pydantic 스키마

**새 파일**: `app/schemas/lessonplan_analysis.py`

```python
"""
수업 지도안 분석 스키마
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class LessonPlanAnalysisRequest(BaseModel):
    """분석 요청 스키마"""
    session_id: int = Field(..., description="채팅 세션 ID", gt=0)


class LessonPlanAnalysisResponse(BaseModel):
    """분석 응답 스키마"""
    success: bool = Field(..., description="성공 여부")
    report: Optional[str] = Field(None, description="Markdown 보고서")
    citations: Optional[Dict[str, Any]] = Field(None, description="Citation 정보")
    latency_ms: Optional[int] = Field(None, description="응답 시간 (ms)")
    error: Optional[str] = Field(None, description="에러 메시지")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "report": "# 📚 수업 지도안 평가 보고서\n\n...",
                "citations": {
                    "used_criteria": ["평가기준 1", "평가기준 2"],
                    "grounding_chunks": [...]
                },
                "latency_ms": 12350
            }
        }
```

#### 4.2 API 라우터

**새 파일**: `app/routers/lessonplan_analysis.py`

```python
"""
수업 지도안 분석 라우터
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.services.lessonplan_analysis_service import LessonPlanAnalysisService
from app.schemas.lessonplan_analysis import (
    LessonPlanAnalysisRequest,
    LessonPlanAnalysisResponse
)

router = APIRouter(prefix="/api/lessonplan", tags=["lessonplan"])


@router.post("/analyze", response_model=LessonPlanAnalysisResponse)
async def analyze_lesson_plan(
    request: LessonPlanAnalysisRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    수업 지도안 체계적 평가

    평가기준 문서를 근거로 사용자의 수업 지도안을 5개 항목으로 평가하고
    Markdown 형식의 분석 보고서를 생성합니다.

    **평가 항목:**
    1. 교육과정 목표 및 성격과의 부합
    2. 내용 체계 및 성취기준 달성
    3. 교수·학습 방법의 적절성
    4. 평가 방향과의 일치
    5. 개선 및 보완을 위한 제안

    **처리 시간:** 약 30-180초
    """
    try:
        service = LessonPlanAnalysisService(db=db)
        result = await service.analyze_lesson_plan(
            session_id=request.session_id,
            user_id=current_user["id"]
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("error", "분석 중 오류 발생")
            )

        return LessonPlanAnalysisResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 오류: {str(e)}"
        )
```

#### 4.3 메인 앱 라우터 등록

**파일**: `app/main.py`

```python
# 기존 import에 추가
from app.routers import lessonplan_analysis

# 기존 라우터 등록 후 추가
app.include_router(lessonplan_analysis.router)
```

---

### Phase 5: 테스트 코드 작성

**새 파일**: `tests/test_lessonplan_analysis_service.py`

```python
"""
LessonPlanAnalysisService 테스트
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.lessonplan_analysis_service import LessonPlanAnalysisService


@pytest.fixture
def mock_db():
    """Mock DB 세션"""
    return AsyncMock()


@pytest.fixture
def service(mock_db):
    """LessonPlanAnalysisService 인스턴스"""
    return LessonPlanAnalysisService(db=mock_db)


class TestLessonPlanAnalysisService:
    """LessonPlanAnalysisService 단위 테스트"""

    @pytest.mark.asyncio
    async def test_get_criteria_context_success(self, service):
        """Vector Search 컨텍스트 추출 성공"""
        # Given
        expected_context = "평가기준 컨텍스트 내용"
        service.criteria_service.get_context = AsyncMock(
            return_value=expected_context
        )

        # When
        result = await service._get_criteria_context()

        # Then
        assert result == expected_context
        service.criteria_service.get_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_criteria_context_failure(self, service):
        """Vector Search 실패 시 기본값 반환"""
        # Given
        service.criteria_service.get_context = AsyncMock(
            side_effect=Exception("DB 오류")
        )

        # When
        result = await service._get_criteria_context()

        # Then
        assert result == "평가기준 컨텍스트 없음"

    @pytest.mark.asyncio
    async def test_get_store_ids_success(self, service):
        """Store ID 조회 성공"""
        # Given
        user_id = 123
        mock_stores = [
            MagicMock(display_name="rubricstore", name="fileSearchStores/rubric123"),
            MagicMock(display_name="user-123-store", name="fileSearchStores/user123"),
        ]
        service.file_search_service.client.file_search_stores.list = MagicMock(
            return_value=mock_stores
        )

        # When
        result = await service._get_store_ids(user_id)

        # Then
        assert len(result) == 2
        assert "fileSearchStores/rubric123" in result
        assert "fileSearchStores/user123" in result

    @pytest.mark.asyncio
    async def test_get_store_ids_not_found(self, service):
        """Store 없을 시 빈 리스트 반환"""
        # Given
        user_id = 999
        mock_stores = [
            MagicMock(display_name="other-store", name="fileSearchStores/other"),
        ]
        service.file_search_service.client.file_search_stores.list = MagicMock(
            return_value=mock_stores
        )

        # When
        result = await service._get_store_ids(user_id)

        # Then
        assert result == []

    def test_build_analysis_prompt(self, service):
        """프롬프트 구성 테스트"""
        # Given
        system_prompt = "당신은 평가 전문가입니다."
        criteria_context = "평가기준 1\n평가기준 2"

        # When
        result = service._build_analysis_prompt(system_prompt, criteria_context)

        # Then
        assert system_prompt in result
        assert criteria_context in result
        assert "참고 자료" in result
        assert "5개 항목" in result

    def test_extract_citations_success(self, service):
        """Citation 추출 성공"""
        # Given
        mock_response = MagicMock()
        mock_candidate = MagicMock()
        mock_grounding = MagicMock()
        mock_chunk = MagicMock()
        mock_retrieved_context = MagicMock()

        mock_retrieved_context.uri = "fileSearchStores/xxx/documents/yyy"
        mock_retrieved_context.title = "평가기준 문서"
        mock_chunk.retrieved_context = mock_retrieved_context
        mock_grounding.grounding_chunks = [mock_chunk]
        mock_candidate.grounding_metadata = mock_grounding
        mock_response.candidates = [mock_candidate]

        # When
        result = service._extract_citations(mock_response)

        # Then
        assert result is not None
        assert len(result["grounding_chunks"]) == 1
        assert result["grounding_chunks"][0]["source"] == "file_search"
        assert result["grounding_chunks"][0]["uri"] == "fileSearchStores/xxx/documents/yyy"

    def test_extract_citations_no_grounding(self, service):
        """Citation 없을 시 빈 딕셔너리 반환"""
        # Given
        mock_response = MagicMock()
        mock_response.candidates = []

        # When
        result = service._extract_citations(mock_response)

        # Then
        assert result["grounding_chunks"] == []

    @pytest.mark.asyncio
    @patch("app.services.lessonplan_analysis_service.genai.Client")
    async def test_analyze_lesson_plan_success(self, mock_client, service):
        """전체 분석 프로세스 성공"""
        # Given
        session_id = 1
        user_id = 123

        # Mock Vector Search
        service.criteria_service.get_context = AsyncMock(
            return_value="평가기준 컨텍스트"
        )

        # Mock Store IDs
        service._get_store_ids = AsyncMock(
            return_value=["fileSearchStores/rubric", "fileSearchStores/user123"]
        )

        # Mock Gemini API
        mock_response = MagicMock()
        mock_response.text = "# 평가 보고서\n\n분석 내용..."
        mock_response.candidates = []
        service.client.models.generate_content = MagicMock(
            return_value=mock_response
        )

        # When
        result = await service.analyze_lesson_plan(session_id, user_id)

        # Then
        assert result["success"] is True
        assert "# 평가 보고서" in result["report"]
        assert result["latency_ms"] > 0

    @pytest.mark.asyncio
    async def test_analyze_lesson_plan_no_stores(self, service):
        """Store 없을 시 에러 반환"""
        # Given
        session_id = 1
        user_id = 999

        service.criteria_service.get_context = AsyncMock(
            return_value="평가기준 컨텍스트"
        )
        service._get_store_ids = AsyncMock(return_value=[])

        # When
        result = await service.analyze_lesson_plan(session_id, user_id)

        # Then
        assert result["success"] is False
        assert "분석할 문서가 없습니다" in result["error"]

    @pytest.mark.asyncio
    async def test_analyze_lesson_plan_timeout(self, service):
        """타임아웃 에러 처리"""
        # Given
        session_id = 1
        user_id = 123

        import asyncio
        service.criteria_service.get_context = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        # When
        result = await service.analyze_lesson_plan(session_id, user_id)

        # Then
        assert result["success"] is False
        assert "시간 초과" in result["error"]
```

**통합 테스트 파일**: `tests/test_lessonplan_analysis_integration.py`

```python
"""
LessonPlanAnalysisService 통합 테스트
"""
import pytest
from httpx import AsyncClient
from app.main import app


@pytest.mark.integration
class TestLessonPlanAnalysisIntegration:
    """API 엔드포인트 통합 테스트"""

    @pytest.mark.asyncio
    async def test_analyze_endpoint_success(self):
        """분석 엔드포인트 성공"""
        async with AsyncClient(app=app, base_url="http://test") as client:
            # 인증 토큰 필요 (테스트 환경에서는 mock)
            headers = {"Authorization": "Bearer test_token"}
            payload = {"session_id": 1}

            response = await client.post(
                "/api/lessonplan/analyze",
                json=payload,
                headers=headers
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "report" in data

    @pytest.mark.asyncio
    async def test_analyze_endpoint_invalid_session(self):
        """잘못된 세션 ID"""
        async with AsyncClient(app=app, base_url="http://test") as client:
            headers = {"Authorization": "Bearer test_token"}
            payload = {"session_id": -1}

            response = await client.post(
                "/api/lessonplan/analyze",
                json=payload,
                headers=headers
            )

            assert response.status_code == 422  # Validation error
```

---

## 5. 테스트 전략

### 5.1 테스트 범위

| 항목 | 테스트 방법 | 커버리지 목표 |
|------|-----------|---------------|
| 단위 테스트 | Pytest + Mock | ≥ 80% |
| 통합 테스트 | Pytest + AsyncClient | ≥ 70% |
| API 테스트 | FastAPI TestClient | ≥ 90% |
| 성능 테스트 | 타임아웃 및 응답 시간 측정 | - |

### 5.2 테스트 시나리오

#### 단위 테스트
1. **Vector Search 컨텍스트 추출**
   - ✅ 성공 케이스
   - ✅ 실패 시 기본값 반환

2. **Store ID 조회**
   - ✅ rubricstore + user{id}store 조회 성공
   - ✅ Store 없을 시 빈 리스트 반환
   - ✅ 예외 발생 시 에러 처리

3. **프롬프트 구성**
   - ✅ 시스템 프롬프트 + 컨텍스트 결합
   - ✅ 5개 평가 항목 포함 확인

4. **Citation 추출**
   - ✅ Grounding metadata 파싱
   - ✅ 없을 시 빈 딕셔너리 반환

#### 통합 테스트
1. **전체 분석 프로세스**
   - ✅ Vector Search → Store 조회 → API 호출 → 보고서 생성
   - ✅ Markdown 형식 검증
   - ✅ 응답 시간 측정 (180초 이내)

2. **에러 핸들링**
   - ✅ 타임아웃 처리
   - ✅ Store 없을 시 에러 메시지
   - ✅ API 오류 처리

#### API 테스트
1. **POST /api/lessonplan/analyze**
   - ✅ 인증된 사용자 성공
   - ✅ 인증 실패 (401)
   - ✅ 잘못된 요청 (422)
   - ✅ 서버 오류 (500)

### 5.3 성능 테스트

**목표**:
- 평균 응답 시간: 30-60초
- 최대 응답 시간: 180초 (타임아웃)
- 동시 요청 처리: 5개

**테스트 방법**:
```python
import asyncio
import time

async def performance_test():
    service = LessonPlanAnalysisService(db=db)

    start = time.time()
    result = await service.analyze_lesson_plan(
        session_id=1,
        user_id=123
    )
    latency = time.time() - start

    assert latency < 180  # 타임아웃 이내
    assert result["success"] is True
```

---

## 6. 참고 자료

### 6.1 공식 문서

1. **Google Generative AI Python SDK**
   - Context7 Library ID: `/googleapis/python-genai`
   - 버전: v1_33_0
   - 문서: https://googleapis.github.io/python-genai

2. **Gemini API**
   - Context7 Library ID: `/websites/ai_google_dev_gemini-api`
   - 문서: https://ai.google.dev/gemini-api

3. **File Search API Guide**
   - 로컬 파일: `research/file_search_api_guide.md`

### 6.2 내부 코드 참조

1. **QnA 서비스** (`app/services/qna_service.py`)
   - 이중 검색 시스템 패턴 (Line 77-180)
   - Citation 추출 로직 (Line 293-334)

2. **File Search 서비스** (`app/services/file_search_service.py`)
   - Store 관리 (Line 75-92)
   - 파일 업로드 (Line 94-196)

3. **Criteria Context 서비스** (`app/services/criteria_context_service.py`)
   - Vector Search 구현

### 6.3 프로젝트 문서

1. **CLAUDE.md**
   - QnA 시스템 아키텍처 설명
   - 이중 검색 시스템 동작 원리

2. **docs/database_migration_guide.md**
   - DB 스키마 및 마이그레이션 가이드

---

## 부록: API 문서 요약

### FileSearchStores API (Python SDK)

| 메서드 | 설명 | 파라미터 | 반환값 |
|--------|------|----------|--------|
| `list()` | Store 목록 조회 | - | `Iterable[Store]` |
| `create()` | Store 생성 | `config={'display_name': str}` | `Store` |
| `get()` | Store 조회 | `name: str` | `Store` |
| `delete()` | Store 삭제 | `name: str, config={'force': bool}` | `None` |
| `upload_to_file_search_store()` | 파일 업로드 | `file_search_store_name: str, file: str, config: dict` | `Operation` |

**주요 참고사항**:
- ❌ `documents.list()` - **존재하지 않음**
- ❌ `documents.delete()` - **존재하지 않음**
- ✅ `force=True` 옵션으로 Store 및 내부 문서 일괄 삭제 가능

### Generate Content API (File Search Tool)

```python
from google.genai import types

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="질문",
    config=types.GenerateContentConfig(
        tools=[
            types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=["fileSearchStores/xxx", "fileSearchStores/yyy"],
                    metadata_filter='filename="doc.pdf" AND user_id=123',
                    top_k=10
                )
            )
        ],
        temperature=0.7
    )
)
```

**파라미터**:
- `file_search_store_names`: Store ID 리스트 (최대 2개 권장)
- `metadata_filter`: AIP-160 표준 필터 (AND, OR 지원)
- `top_k`: 최대 결과 개수 (기본값: 10)

---

*문서 작성 완료 - 2025-11-23*
*오므니시아의 뜻에 따라 기계령이 안식하길.*
