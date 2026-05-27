"""
수업 지도안 분석 서비스
평가기준 기반 수업지도안 체계적 평가
"""
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from google import genai
from google.api_core import exceptions
from google.genai import types
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.analysis_reports import AnalysisReport
from app.models.lessonplan_uploads import LessonPlanUpload
from app.models.users import User
from app.repositories.app_state_repository import (
    AppStateRepository,
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    SYNC_STATE_NEEDS_RESYNC,
)
from app.services.file_search_service import (
    FileSearchService,
    _sanitize_display_name,
)
from app.services.criteria_vector_service import CriteriaVectorService
from app.services.lessonplan_storage_service import LessonPlanStorageService
from app.services.prompt_loader_service import PromptLoaderService
from app.services.report_storage_service import ReportStorageService
from app.utils.gemini_retry import (
    GeminiQuotaExhausted,
    retry_on_resource_exhausted,
)

logger = logging.getLogger(__name__)


async def _mark_criteria_filter_needs_resync(
    db: AsyncSession, exc: Exception
) -> None:
    try:
        state_repo = AppStateRepository(db=db)
        await state_repo.set(KEY_SYNC_STATE, SYNC_STATE_NEEDS_RESYNC)
        await state_repo.set(KEY_SYNC_ERROR, str(exc))
    except Exception:
        logger.warning("평가기준 동기화 필요 상태 표시 실패", exc_info=True)


@retry_on_resource_exhausted(max_attempts=3, initial_wait=2.0, max_wait=16.0)
def _call_gemini_with_file_search(
    client,
    model,
    contents,
    rubric_store_id,
    user_store_id,
    rubric_metadata_filter,
):
    rubric_search_config = {
        "file_search_store_names": [rubric_store_id],
    }
    if rubric_metadata_filter:
        rubric_search_config["metadata_filter"] = rubric_metadata_filter

    return client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            tools=[
                types.Tool(
                    file_search=types.FileSearch(**rubric_search_config)
                ),
                types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[user_store_id]
                    )
                ),
            ],
            temperature=0.7,
        ),
    )


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
                # 0. 중복 분석 차단 — 최신 업로드에 이미 보고서가 있으면
                # 즉시 ALREADY_ANALYZED 반환 (Gemini 호출 안 함)
                latest_upload, existing_report = (
                    await self._find_existing_report_for_latest_upload(
                        username
                    )
                )
                if existing_report is not None:
                    report_file = Path(existing_report.report_path)
                    if report_file.exists():
                        logger.info(
                            f"중복 분석 차단: upload_id={latest_upload.id}, "
                            f"existing report_id={existing_report.id}"
                        )
                        return {
                            "success": False,
                            "error_code": "ALREADY_ANALYZED",
                            "error": "이미 분석된 문서입니다.",
                            "report_id": existing_report.id,
                        }

                    stale_report_id = existing_report.id
                    stale_report_path = existing_report.report_path
                    latest_upload_id = latest_upload.id
                    logger.warning(
                        f"기존 보고서 파일 누락 ({stale_report_path}) — "
                        f"AnalysisReport row id={stale_report_id} "
                        f"삭제 후 재분석"
                    )
                    await self.db.rollback()
                    stale_report = await self.db.get(
                        AnalysisReport, stale_report_id
                    )
                    if stale_report is not None:
                        await self.db.delete(stale_report)
                        await self.db.commit()
                    latest_upload = await self.db.get(
                        LessonPlanUpload, latest_upload_id
                    )

                legacy_lessonplans = []
                if latest_upload is None:
                    legacy_lessonplans = (
                        self.lessonplan_storage.list_lessonplans(username)
                    )
                    has_file_search_documents = (
                        self._user_file_search_store_has_documents(username)
                    )
                    if (
                        not legacy_lessonplans
                        and not has_file_search_documents
                    ):
                        return {
                            "success": False,
                            "error": (
                                "분석할 문서가 없습니다. "
                                "수업 지도안을 먼저 업로드해주세요."
                            )
                        }

                # 1. File Search Store ID 조회 (Phase 1 활용)
                store_ids = await self._get_store_ids(username)
                if not store_ids:
                    return {
                        "success": False,
                        "error": (
                            "분석할 문서가 없습니다. "
                            "수업 지도안을 먼저 업로드해주세요."
                        )
                    }

                # Store ID 분리 및 역할 명확화
                user_store_id = store_ids[0]      # 사용자 업로드 수업 지도안
                rubric_store_id = store_ids[1]    # 평가기준 문서
                criteria_notice = None

                logger.info(
                    f"File Search Store 조회 완료:\n"
                    f"  - Rubric Store: {rubric_store_id}\n"
                    f"  - Lesson Store: {user_store_id}"
                )

                try:
                    rubric_metadata_filter = await (
                        CriteriaVectorService.active_stable_id_filter(
                            client=self.client,
                            store_display_name=settings.FS_RUBRIC_STORE_NAME,
                        )
                    )
                except Exception as e:
                    logger.warning(
                        f"활성 평가기준 필터 조회 실패 (무시): {e}",
                        exc_info=True,
                    )
                    rubric_metadata_filter = None
                    criteria_notice = "평가기준 동기화가 필요합니다."
                    await _mark_criteria_filter_needs_resync(self.db, e)
                if not rubric_metadata_filter and not criteria_notice:
                    logger.info("활성 평가기준 없음 — 수업지도안 분석 생략")
                    return {
                        "success": False,
                        "error_code": "NO_ACTIVE_CRITERIA",
                        "error": (
                            "활성 평가기준이 없습니다. "
                            "관리자에게 평가기준 활성화를 요청해주세요."
                        ),
                    }

                # 2. 프롬프트 구성 (Store 역할 명시)
                system_prompt = self.prompt_loader.get_prompt("lesson_analysis")
                full_prompt = self._build_analysis_prompt(
                    system_prompt,
                    rubric_store_id=rubric_store_id,
                    lesson_store_id=user_store_id
                )
                logger.info("프롬프트 구성 완료 (Store 역할 명시 포함)")

                # 3. Gemini API 호출 (File Search - 평가기준 우선 순서)
                response = await asyncio.to_thread(
                    _call_gemini_with_file_search,
                    self.client, self.model_name, full_prompt,
                    rubric_store_id, user_store_id, rubric_metadata_filter,
                )

                # 4. Markdown 보고서 추출 및 후처리
                raw_report = response.text if response.text else ""
                report = self._post_process_report(raw_report)  # 후처리 적용

                # 5. Citation 추출
                citations = self._extract_citations(response)

                # 응답 시간 계산
                latency_ms = int((time.time() - start_time) * 1000)

                logger.info(f"분석 완료 (응답 시간: {latency_ms}ms)")

                # 보고서 파일 저장 및 DB 기록
                saved_report = None
                if report:
                    try:
                        if latest_upload is not None:
                            original_filename = (
                                latest_upload.original_filename
                                or "unknown"
                            )
                            lessonplan_filename = latest_upload.filename
                        else:
                            # Legacy path: no LessonPlanUpload row yet. Derive
                            # filename + original from on-disk metadata, then
                            # create a synthetic upload row so the dedup
                            # invariant (1:1 upload<->report) holds for
                            # subsequent clicks.
                            lessonplans = legacy_lessonplans
                            if lessonplans:
                                latest = max(
                                    lessonplans,
                                    key=lambda x: x["created_at"]
                                )
                                original_filename = latest["original_filename"]
                                lessonplan_filename = latest["filename"]
                            else:
                                original_filename = "unknown"
                                lessonplan_filename = "unknown"

                            latest_upload = LessonPlanUpload(
                                user_id=user_id,
                                filename=lessonplan_filename,
                                original_filename=original_filename,
                                file_hash=None,
                            )
                            try:
                                self.db.add(latest_upload)
                                await self.db.flush()
                            except IntegrityError:
                                await self.db.rollback()
                                latest_upload, existing_report = await (
                                    self._find_existing_report_for_latest_upload(
                                        username
                                    )
                                )
                                if existing_report is not None:
                                    logger.warning(
                                        "legacy synthetic upload race 감지 "
                                        f"→ ALREADY_ANALYZED 폴백 "
                                        f"(winner report_id="
                                        f"{existing_report.id})"
                                    )
                                    return {
                                        "success": False,
                                        "error_code": "ALREADY_ANALYZED",
                                        "error": "이미 분석된 문서입니다.",
                                        "report_id": existing_report.id,
                                    }
                                if latest_upload is None:
                                    raise
                                original_filename = (
                                    latest_upload.original_filename
                                    or original_filename
                                )
                                lessonplan_filename = latest_upload.filename
                                logger.warning(
                                    "legacy synthetic upload race 감지 "
                                    f"→ 기존 upload_id={latest_upload.id} "
                                    "재사용"
                                )
                            else:
                                logger.info(
                                    f"legacy 사용자에 대해 synthetic "
                                    f"LessonPlanUpload 생성: "
                                    f"id={latest_upload.id}, "
                                    f"filename={lessonplan_filename}"
                                )

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
                        analysis_upload_id = (
                            latest_upload.id
                            if latest_upload is not None
                            else None
                        )
                        analysis_record = AnalysisReport(
                            user_id=user_id,
                            lessonplan_filename=lessonplan_filename,
                            lessonplan_original_name=original_filename,
                            report_filename=saved_report["filename"],
                            report_path=saved_report["file_path"],
                            latency_ms=latency_ms,
                            upload_id=analysis_upload_id,
                        )
                        self.db.add(analysis_record)
                        try:
                            await self.db.flush()
                        except IntegrityError:
                            # Race: another request inserted a report for
                            # this upload_id between our pre-flight check
                            # and this INSERT. Roll back and return
                            # ALREADY_ANALYZED with the winning row's id.
                            # Resolve the winner by the upload_id used for
                            # this INSERT, not by the latest-upload lookup
                            # (which may now return a newer upload).
                            captured_upload_id = analysis_upload_id
                            await self.db.rollback()
                            winner = None
                            if captured_upload_id is not None:
                                async with self.db.begin():
                                    winner_result = await self.db.execute(
                                        select(AnalysisReport)
                                        .where(
                                            AnalysisReport.upload_id
                                            == captured_upload_id
                                        )
                                        .limit(1)
                                    )
                                    winner = winner_result.scalar_one_or_none()
                            if winner is not None:
                                loser_path = saved_report["file_path"]
                                if loser_path != winner.report_path:
                                    try:
                                        Path(loser_path).unlink(
                                            missing_ok=True
                                        )
                                    except Exception as cleanup_error:
                                        logger.warning(
                                            "race fallback orphan report "
                                            "cleanup failed: "
                                            f"{cleanup_error}",
                                            exc_info=True,
                                        )
                                logger.warning(
                                    f"분석 결과 race 감지 → ALREADY_ANALYZED "
                                    f"폴백 (winner report_id={winner.id})"
                                )
                                return {
                                    "success": False,
                                    "error_code": "ALREADY_ANALYZED",
                                    "error": "이미 분석된 문서입니다.",
                                    "report_id": winner.id,
                                }
                            raise
                        logger.info(
                            f"분석 기록 DB 저장 완료: "
                            f"id={analysis_record.id}, "
                            f"upload_id={analysis_record.upload_id}"
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
                    "criteria_notice": criteria_notice,
                    "saved_report": saved_report
                }

        except asyncio.TimeoutError:
            logger.error("분석 타임아웃 (180초 초과)")
            return {"success": False, "error": "분석 시간 초과 (180초)"}

        except GeminiQuotaExhausted as e:
            logger.error(f"Gemini 쿼터 소진 (재시도 후 실패): {e}")
            return {
                "success": False,
                "error": (
                    "현재 분석 요청량이 많습니다. "
                    "잠시 후 다시 시도해주세요."
                ),
                "error_code": "RESOURCE_EXHAUSTED",
            }

        except exceptions.GoogleAPIError as e:
            logger.error(f"Google API 오류: {e}")
            return {"success": False, "error": f"API 오류: {str(e)}"}

        except Exception as e:
            logger.error(f"분석 실패: {e}", exc_info=True)
            return {"success": False, "error": "분석 중 오류 발생"}

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

    def _user_file_search_store_has_documents(self, username: str) -> bool:
        store_name = f"user-{username}-store"
        safe_store_name = _sanitize_display_name(store_name)
        try:
            file_search_stores = (
                self.file_search_service.client.file_search_stores
            )
            for store in file_search_stores.list():
                if store.display_name not in {store_name, safe_store_name}:
                    continue
                documents = file_search_stores.list_documents(
                    file_search_store_name=store.name
                )
                return any(True for _ in documents)
        except Exception as exc:
            logger.warning(
                f"사용자 File Search Store 문서 확인 실패: {exc}"
            )
        return False

    async def _find_existing_report_for_latest_upload(
        self, username: str
    ):
        """
        사용자의 최신 업로드 이벤트와 그에 연결된 기존 보고서를 함께 조회.

        Returns:
            (LessonPlanUpload | None, AnalysisReport | None)
            - (None, None): 업로드 이력 자체가 없는 사용자
            - (upload, None): 최신 업로드는 있으나 분석 보고서는 아직 없음
            - (upload, report): 이미 분석 완료 → 차단해야 함
        """
        result = await self.db.execute(
            select(User)
            .where(User.username == username)
            .limit(1)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return (None, None)

        upload_result = await self.db.execute(
            select(LessonPlanUpload)
            .where(LessonPlanUpload.user_id == user.id)
            .order_by(
                LessonPlanUpload.created_at.desc(),
                LessonPlanUpload.id.desc(),
            )
            .limit(1)
        )
        latest_upload = upload_result.scalar_one_or_none()
        if latest_upload is None:
            return (None, None)

        report_result = await self.db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.upload_id == latest_upload.id)
            .limit(1)
        )
        existing_report = report_result.scalar_one_or_none()
        return (latest_upload, existing_report)

    def _build_analysis_prompt(
        self,
        system_prompt: str,
        rubric_store_id: str,
        lesson_store_id: str
    ) -> str:
        """
        분석 프롬프트 구성 (Store 역할 명시 포함)

        Args:
            system_prompt: 시스템 프롬프트 (lesson_analysis)
            rubric_store_id: 평가기준 문서 Store ID
            lesson_store_id: 수업 지도안 문서 Store ID

        Returns:
            완전한 프롬프트
        """
        prompt_intro = (
            f"**{rubric_store_id}의 평가기준 자료를 바탕으로 "
            f"{lesson_store_id}에 저장된 사용자의 수업 지도안을 평가하세요.**"
        )
        rubric_note = (
            f"- **{rubric_store_id}**: 평가 기준 문서입니다. "
            "참고 자료로만 사용하며 답변 근거로 표시하지 않습니다."
        )
        lesson_note = (
            f"- **{lesson_store_id}**: 사용자가 업로드한 수업 지도안입니다. "
            "모든 평가 근거를 반드시 이 문서에서 찾고 인용하세요."
        )
        task_intro = (
            "위 평가 기준을 바탕으로 사용자가 업로드한 수업 지도안을 "
            "다음 5개 항목으로 체계적으로 평가해주세요:"
        )
        return f"""
{system_prompt}

{prompt_intro}

**중요 지시사항:**
{rubric_note}
{lesson_note}

{task_intro}

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
        1. 'Vector Search 참고 자료' 섹션이 비구조화된 긴 텍스트일 경우
           목록으로 정리
        2. 본문 전체에서 이모지/픽토그램 제거
           (LLM이 출력했더라도 일관된 텍스트 형식 유지)

        Args:
            report: 원본 Markdown 보고서

        Returns:
            후처리된 보고서
        """
        import re

        try:
            # 0) LLM 이 학습된 양식으로 출력했을 수 있는 모델명 라인 제거.
            #    형태: `> - **분석 모델**: <임의 텍스트>` (전후 공백 허용)
            report = re.sub(
                r'^\s*>\s*-\s*\*\*분석\s*모델\*\*\s*:.*$\n?',
                '',
                report,
                flags=re.MULTILINE,
            )

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

            # 2) 본문 이모지 제거. 블록 인용 라인은 사용자 문서
            # 인용 충실성을 위해 보존한다.
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
        strip_emojis 를 호출하여, 굵은 영역(`**...**`) 이 여러 줄에
        걸친 경우에도
        잔여 공백 정리가 작동하게 한다. 인용 블록(`> **수업 지도안**: ...` 진입,
        새 라벨 또는 비-`>` 라인 만날 때까지) 라인은 verbatim 보존한다.
        """
        import re

        from app.utils.text_sanitizer import strip_emojis

        # 모델이 라벨을 장식하거나 띄어쓰기를 사용해도
        # (예: '> **📄 수업 지도안**:') 인용으로 인정.
        citation_start = re.compile(
            r"^\s*>\s*\*\*[^*]*수업\s*지도안[^*]*\*\*"
        )
        # 새 라벨은 '> **<텍스트>**:' 콜론 형태로만 인식.
        # 콜론 없는 굵은 블록인용은 인용 본문의 일부로 보존.
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
                in_citation = False
                if line.strip() == "":
                    # 빈 줄 = 단락 경계: 누적 블록을 flush 하고
                    # 빈 줄은 그대로 유지.
                    # 닫히지 않은 굵은 마커(`**강점` 같은) 가 다음 단락의 헤더를
                    # 침범해 멀티라인 _BOLD_SPAN 이 가로질러 매칭하는 것을 방지.
                    flush_buffer()
                    sanitized.append(line)
                else:
                    # 비인용 라인 누적: 단락 단위로 멀티라인
                    # 굵은 영역 정리 가능.
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

                logger.debug(
                    "Citations 추출 완료: "
                    f"{len(citations['grounding_chunks'])}개"
                )

        except Exception as e:
            logger.warning(f"Citation 추출 실패: {e}")

        return citations
