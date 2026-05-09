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
from app.services.lessonplan_storage_service import LessonPlanStorageService
from app.services.report_storage_service import ReportStorageService
from app.models.analysis_reports import AnalysisReport

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
        self.lessonplan_storage = LessonPlanStorageService()
        self.report_storage = ReportStorageService()

    async def analyze_lesson_plan(
        self,
        session_id: int,
        user_id: int,
        username: str,
    ) -> Dict[str, Any]:
        """
        수업 지도안 체계적 평가

        Args:
            session_id: 채팅 세션 ID
            session_id: 채팅 세션 ID
            user_id: 사용자 ID (로깅용)
            username: 사용자 이름 (Store ID 조회용)

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

                # 2. File Search Store ID 조회 (Phase 1 활용)
                store_ids = await self._get_store_ids(username)
                if not store_ids:
                    return {
                        "success": False,
                        "error": "분석할 문서가 없습니다. 수업 지도안을 먼저 업로드해주세요."
                    }

                # Store ID 분리 및 역할 명확화
                user_store_id = store_ids[0]      # 사용자 업로드 수업 지도안
                rubric_store_id = store_ids[1]    # 평가기준 문서

                logger.info(
                    f"File Search Store 조회 완료:\n"
                    f"  - Rubric Store: {rubric_store_id}\n"
                    f"  - Lesson Store: {user_store_id}"
                )

                # 3. 프롬프트 구성 (Store 역할 명시)
                system_prompt = self.prompt_loader.get_prompt("lesson_analysis")
                full_prompt = self._build_analysis_prompt(
                    system_prompt,
                    criteria_context,
                    rubric_store_id=rubric_store_id,
                    lesson_store_id=user_store_id
                )
                logger.info("프롬프트 구성 완료 (Store 역할 명시 포함)")

                # 4. Gemini API 호출 (File Search - 평가기준 우선 순서)
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        tools=[
                            types.Tool(
                                file_search=types.FileSearch(
                                    file_search_store_names=[rubric_store_id, user_store_id]
                                )
                            )
                        ],
                        temperature=0.7
                    )
                )

                # 5. Markdown 보고서 추출 및 후처리
                raw_report = response.text if response.text else ""
                report = self._post_process_report(raw_report)  # 후처리 적용

                # 6. Citation 추출
                citations = self._extract_citations(response)

                # 응답 시간 계산
                latency_ms = int((time.time() - start_time) * 1000)

                logger.info(f"분석 완료 (응답 시간: {latency_ms}ms)")

                # 보고서 파일 저장 및 DB 기록
                saved_report = None
                if report:
                    try:
                        # 가장 최근 업로드 파일명 조회
                        lessonplans = self.lessonplan_storage.list_lessonplans(
                            username
                        )
                        if lessonplans:
                            # created_at 기준 정렬하여 최신 파일 선택
                            latest = max(
                                lessonplans,
                                key=lambda x: x["created_at"]
                            )
                            original_filename = latest["original_filename"]
                            lessonplan_filename = latest["filename"]
                        else:
                            original_filename = "unknown"
                            lessonplan_filename = "unknown"

                        # 보고서 파일 저장
                        saved_report = self.report_storage.save_report(
                            username=username,
                            original_filename=original_filename,
                            report_content=report,
                        )
                        logger.info(
                            f"보고서 파일 저장 완료: {saved_report['filename']}"
                        )

                        # DB에 분석 기록 저장
                        analysis_record = AnalysisReport(
                            user_id=user_id,
                            lessonplan_filename=lessonplan_filename,
                            lessonplan_original_name=original_filename,
                            report_filename=saved_report["filename"],
                            report_path=saved_report["file_path"],
                            latency_ms=latency_ms,
                        )
                        self.db.add(analysis_record)
                        await self.db.flush()
                        logger.info(
                            f"분석 기록 DB 저장 완료: id={analysis_record.id}"
                        )

                    except Exception as save_error:
                        logger.warning(
                            f"보고서 저장/DB 기록 실패 (분석 결과는 정상): "
                            f"{save_error}"
                        )

                return {
                    "success": True,
                    "report": report,
                    "citations": citations,
                    "latency_ms": latency_ms,
                    "saved_report": saved_report
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
            context_data = await self.criteria_service.get_context(
                "수업 지도안 평가 기준"
            )
            # dictionary에서 context_text 추출
            if isinstance(context_data, dict):
                return context_data.get("context_text", "평가기준 컨텍스트 없음")
            return context_data if context_data else "평가기준 컨텍스트 없음"

        except Exception as e:
            logger.warning(f"평가기준 컨텍스트 추출 실패: {e}")
            return "평가기준 컨텍스트 없음"

    async def _get_store_ids(self, username: str) -> list[str]:
        """
        File Search Store ID 조회 (Phase 1 공통 유틸 사용)

        Args:
            username: 사용자 이름

        Returns:
            Store ID 리스트 [user-{username}-store, rubricstore]
            (실제 반환 순서: 사용자 문서, 평가기준 문서)
        """
        try:
            # Phase 1의 get_dual_store_ids() 사용
            store_ids = self.file_search_service.get_dual_store_ids(
                username
            )
            logger.info(f"✅ Store ID 조회 완료: {len(store_ids)}개")
            return store_ids
        except ValueError as e:
            logger.error(f"❌ Store ID 조회 실패: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ 예상치 못한 오류: {e}")
            return []

    def _build_analysis_prompt(
        self,
        system_prompt: str,
        criteria_context: str,
        rubric_store_id: str,
        lesson_store_id: str
    ) -> str:
        """
        분석 프롬프트 구성 (Store 역할 명시 포함)

        Args:
            system_prompt: 시스템 프롬프트 (lesson_analysis)
            criteria_context: Vector Search 컨텍스트
            rubric_store_id: 평가기준 문서 Store ID
            lesson_store_id: 수업 지도안 문서 Store ID

        Returns:
            완전한 프롬프트
        """
        # 모델 이름 플레이스홀더 치환
        system_prompt = system_prompt.replace(
            "{model_name}", self.model_name
        )
        return f"""
{system_prompt}

**{rubric_store_id}의 평가기준 자료를 바탕으로 {lesson_store_id}에 저장된 사용자의 수업 지도안을 평가하세요.**

**중요 지시사항:**
- **{rubric_store_id}**: 평가 기준 문서입니다. 참고 자료로만 사용하며 답변 근거로 표시하지 않습니다.
- **{lesson_store_id}**: 사용자가 업로드한 수업 지도안입니다. 모든 평가 근거를 반드시 이 문서에서 찾고 인용하세요.

### [참고 자료: Vector Search로 검색된 평가기준 컨텍스트]
{criteria_context}

위 평가 기준을 바탕으로 사용자가 업로드한 수업 지도안을 다음 5개 항목으로 체계적으로 평가해주세요:

1. 교육과정 목표 및 성격과의 부합
2. 내용 체계 및 성취기준 달성
3. 교수·학습 방법의 적절성
4. 평가 방향과의 일치
5. 개선 및 보완을 위한 제안

반드시 Markdown 형식의 보고서로 작성해주세요.
"""

    def _post_process_report(self, report: str) -> str:
        """
        보고서 후처리:
        1. 'Vector Search 참고 자료' 섹션이 비구조화된 긴 텍스트일 경우 목록으로 정리
        2. 본문 전체에서 이모지/픽토그램 제거 (LLM이 출력했더라도 일관된 텍스트 형식 유지)

        Args:
            report: 원본 Markdown 보고서

        Returns:
            후처리된 보고서
        """
        import re

        from app.utils.text_sanitizer import strip_emojis

        try:
            # 1) "Vector Search 참고 자료" 섹션 가독성 개선
            # 이모지 유무와 무관하게 매칭되도록 패턴에서 🔍 의존을 제거한다.
            pattern = (
                r'(###\s*(?:[^\n]*?)?Vector Search 참고 자료\s*\n)'
                r'(.*?)(\n###|\Z)'
            )
            match = re.search(pattern, report, flags=re.DOTALL)

            if match:
                header = match.group(1)
                content = match.group(2).strip()
                next_section = match.group(3)

                # 이미 구조화되어 있는지 확인 (목록/번호가 있으면 이미 구조화됨)
                already_structured = re.search(
                    r'^\s*[0-9]+\.|\s*-|\s*\*',
                    content,
                    re.MULTILINE,
                )
                if not already_structured and len(content) > 100:
                    sentences = re.split(r'(?<=[.!?])\s+', content)
                    sentences = [
                        s.strip() for s in sentences if len(s.strip()) > 20
                    ]
                    formatted = "\n".join([f"- {s}" for s in sentences[:8]])
                    new_section = f"{header}\n{formatted}\n{next_section}"
                    report = (
                        report[: match.start()]
                        + new_section
                        + report[match.end():]
                    )

            # 2) 본문 이모지 제거 (블록 인용 라인은 보존 — 사용자 문서 인용 충실성 유지)
            report = self._sanitize_report_lines(report)

            return report

        except Exception as e:
            logger.warning(f"보고서 후처리 실패 (원본 반환): {e}")
            # 후처리 자체가 실패하더라도 최소한 줄 단위 살균은 시도한다
            try:
                return self._sanitize_report_lines(report)
            except Exception:
                return report

    def _sanitize_report_lines(self, report: str) -> str:
        """
        보고서를 살균한다 — 비-인용 라인들은 멀티라인 블록 단위로 묶어 한 번에
        strip_emojis 를 호출하여, 굵은 영역(`**...**`) 이 여러 줄에 걸친 경우에도
        잔여 공백 정리가 작동하게 한다. 인용 블록(`> **수업 지도안**: ...` 진입,
        새 라벨 또는 비-`>` 라인 만날 때까지) 라인은 verbatim 보존한다.
        """
        import re

        from app.utils.text_sanitizer import strip_emojis

        # 모델이 라벨을 장식하거나 띄어쓰기를 사용해도(예: '> **📄 수업 지도안**:')
        # 인용으로 인정.
        citation_start = re.compile(
            r"^\s*>\s*\*\*[^*]*수업\s*지도안[^*]*\*\*"
        )
        # 새 라벨은 '> **<텍스트>**:' 콜론 형태로만 인식. 콜론 없는 굵은 블록인용은
        # 인용 본문의 일부로 보존.
        blockquote_label = re.compile(r"^\s*>\s*\*\*[^*\n]+\*\*\s*:")
        blockquote_any = re.compile(r"^\s*>")

        sanitized: list[str] = []
        buffer: list[str] = []
        in_citation = False

        def flush_buffer() -> None:
            if buffer:
                sanitized.append(strip_emojis("\n".join(buffer)))
                buffer.clear()

        for line in report.split("\n"):
            if citation_start.match(line):
                flush_buffer()
                in_citation = True
                sanitized.append(line)
            elif (
                in_citation
                and blockquote_any.match(line)
                and not blockquote_label.match(line)
            ):
                # continuation 라인 — verbatim 보존
                sanitized.append(line)
            else:
                # 인용 모드 종료 또는 비인용 — 버퍼에 누적해 멀티라인 단위로 살균
                in_citation = False
                buffer.append(line)

        flush_buffer()
        return "\n".join(sanitized)

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
