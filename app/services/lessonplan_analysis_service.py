"""
수업 지도안 분석 서비스
평가기준 기반 수업지도안 체계적 평가
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from google import genai
from google.api_core import exceptions
from google.genai import types
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.analysis_reports import AnalysisReport
from app.models.lessonplan_uploads import LessonPlanUpload
from app.repositories.app_state_repository import (
    KEY_SYNC_ERROR,
    KEY_SYNC_STATE,
    SYNC_STATE_NEEDS_RESYNC,
    AppStateRepository,
)
from app.services.criteria_vector_service import CriteriaVectorService
from app.services.file_search_service import (
    FileSearchService,
    _sanitize_display_name,
)
from app.services.lessonplan_storage_service import LessonPlanStorageService
from app.services.prompt_loader_service import PromptLoaderService
from app.services.report_storage_service import ReportStorageService
from app.utils.gemini_retry import (
    GeminiQuotaExhausted,
    GeminiServerOverloaded,
    is_transient_lookup_error,
    retry_on_resource_exhausted,
)

logger = logging.getLogger(__name__)

# #439 저장 전 검사. 1~5 항목 번호는 _build_analysis_prompt 가 고정한다.
_REPORT_SECTIONS = [
    re.compile(rf"^#{{1,3}}[ \t]*{n}(?!\d)", re.MULTILINE) for n in range(1, 6)
]
# 구분선·표에 쓰는 글자(공백 - = _ * | . ~ # >)의 반복은 붕괴로 보지 않는다
_REPORT_CONTENT_CHAR = re.compile(r"[^\s\-=_*|.~#>]")
_REPORT_CHAR_RUN = re.compile(r"([^\s\-=_*|.~#>])\1{29,}")
_REPORT_PHRASE_RUN = re.compile(r"(?=([^\n]{2,20}?)\1{9})")
_INVALID_REPORT_MESSAGE = (
    "분석 결과가 올바르게 만들어지지 않았습니다. 다시 시도해주세요."
)
_NOT_RETRIEVED_MESSAGE = (
    "업로드한 지도안 내용을 읽지 못했습니다. "
    "지도안을 다시 업로드한 뒤 분석해 주세요."
)
_INDEX_MISSING_MESSAGE = (
    "지도안 검색 색인이 없습니다. 지도안을 다시 업로드한 뒤 분석해 주세요."
)


def _finish_reason_name(response) -> Optional[str]:
    """첫 후보의 finish_reason 이름. 후보·값이 없거나 문자열이 아니면 None."""
    candidates = getattr(response, "candidates", None) or []
    reason = (
        getattr(candidates[0], "finish_reason", None) if candidates else None
    )
    name = getattr(reason, "name", reason)
    return name if isinstance(name, str) else None


def _report_problems(text: str, finish_reason: Optional[str]) -> list[str]:
    """보고서 원문의 문제 사유 목록(본문은 넣지 않는다). 비면 통과 (#439)."""
    problems = []
    if finish_reason is not None and finish_reason != "STOP":
        problems.append(f"finish_reason={finish_reason}")
    missing = [
        str(n)
        for n, section in enumerate(_REPORT_SECTIONS, 1)
        if not section.search(text)
    ]
    if missing:
        problems.append("절 없음: " + ",".join(missing))
    repeated = bool(_REPORT_CHAR_RUN.search(text)) or any(
        len(set(m[1])) > 1 and _REPORT_CONTENT_CHAR.search(m[1])
        for m in _REPORT_PHRASE_RUN.finditer(text)
    )
    if repeated:
        problems.append("반복")
    return problems


# 줄 전체가 닫는 ** 없는 '**라벨' 인 줄 (#441)
_DANGLING_BOLD_LINE = re.compile(r"^([ \t]*)\*\*([^*\n]*[^*\s])[ \t]*$", re.M)


def _close_dangling_bold(text: str) -> str:
    """빈 줄로 나뉜 문단의 ** 개수가 홀수면 그 문단의 첫 '**라벨' 줄을 닫는다."""
    parts = re.split(r"(\n[ \t]*\n)", text)
    return "".join(
        (
            _DANGLING_BOLD_LINE.sub(r"\1**\2**", part, count=1)
            if part.count("**") % 2
            else part
        )
        for part in parts
    )


async def _mark_criteria_filter_needs_resync(
    db: AsyncSession, exc: Exception
) -> None:
    try:
        state_repo = AppStateRepository(db=db)
        await state_repo.set(KEY_SYNC_STATE, SYNC_STATE_NEEDS_RESYNC)
        await state_repo.set(KEY_SYNC_ERROR, str(exc))
    except Exception:
        logger.warning("평가기준 동기화 필요 상태 표시 실패", exc_info=True)


# Issue #118: 긴 평가 지시 프롬프트는 File Search retrieval 쿼리로서 품질이
# 낮다(지시문 임베딩이 지도안 실제 내용과 의미적으로 불일치). 그 결과 사용자
# 문서를 한 청크도 검색하지 못해, 보고서의 '현재 지도안'/'수업지도안' 인용이
# 모두 '해당 서술 없음'으로 떨어졌다. 평가 전에 내용 지향 질의로 지도안 원문을
# 먼저 검색(1패스)한 뒤 평가 프롬프트에 주입(2패스)한다.
_LESSONPLAN_RETRIEVE_QUERY = (
    "업로드된 수업 지도안 문서에서 다음 항목을 문서에 적힌 문장 그대로 "
    "빠짐없이 인용·발췌하라: 제목, 학습 목표, 성취기준, 차시별 교수·학습 "
    "활동, 평가 계획, 사용 자료. 요약하지 말고 원문을 직접 인용하라."
)


def _retrieve_lessonplan_text(client, model, user_store_id) -> str:
    """1패스: 사용자 스토어에서 지도안 원문을 검색해 텍스트로 반환한다.

    내용 지향 질의를 사용해야 File Search 가 업로드 문서를 안정적으로
    grounding 한다 (issue #118). 응답이 비었거나 검색 근거(grounding chunk)가
    없으면 빈 문자열을 반환한다 (#449).
    """
    response = client.models.generate_content(
        model=model,
        contents=_LESSONPLAN_RETRIEVE_QUERY,
        config=types.GenerateContentConfig(
            tools=[
                types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[user_store_id]
                    )
                ),
            ],
            temperature=0.2,
        ),
    )
    text = response.text or ""
    candidates = response.candidates or []
    metadata = candidates[0].grounding_metadata if candidates else None
    count = len(getattr(metadata, "grounding_chunks", None) or [])
    logger.info("분석 1패스 chars=%d grounding_chunks=%d", len(text), count)
    # 근거 없는 답은 "문서가 확인되지 않습니다" 같은 안내문이다 (#449)
    return text if text.strip() and count else ""


@retry_on_resource_exhausted(max_attempts=3, initial_wait=2.0, max_wait=16.0)
def _call_gemini_with_file_search(
    client,
    model,
    contents,
    rubric_store_id,
    user_store_id,
    rubric_metadata_filter,
) -> types.GenerateContentResponse | None:
    """두 패스 grounded 평가 (issue #118).

    1패스(_retrieve_lessonplan_text): 사용자 스토어에서 지도안 원문을 검색.
    2패스: 검색한 원문을 평가 프롬프트에 주입하고 rubric 스토어(활성 필터
    적용)만으로 평가 보고서를 생성한다. 사용자 문서는 이미 본문에 주입되어
    있으므로 2패스에서는 사용자 스토어 도구를 두지 않는다 — 이중 File Search
    도구 조합이 사용자 문서 retrieval 을 저해하던 issue #86 도 함께 회피된다.

    1패스가 지도안 원문을 얻지 못하면 2패스를 부르지 않고 None 을 돌려준다
    (#449). 재시도와 오류 반환은 analyze_lesson_plan 이 한다.
    """
    lesson_text = _retrieve_lessonplan_text(client, model, user_store_id)
    if not lesson_text:
        return None
    contents = (
        f"{contents}\n\n"
        "**평가 대상 수업 지도안 원문 (아래 내용만을 근거로 평가하고, "
        "'현재 지도안'과 '수업지도안' 인용은 반드시 이 원문에서 "
        "발췌하세요):**\n"
        f"---\n{lesson_text}\n---"
    )

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
            http_options={"api_version": "v1beta"},
        )
        self.prompt_loader = PromptLoaderService()
        self.file_search_service = FileSearchService()
        self.lessonplan_storage = LessonPlanStorageService()
        self.report_storage = ReportStorageService()

    async def analyze_lesson_plan(
        self,
        session_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        수업 지도안 체계적 평가

        Args:
            session_id: 채팅 세션 ID
            user_id: 사용자 ID (User.id)

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
                    await self._find_existing_report_for_latest_upload(user_id)
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

                # 색인 id 가 비면 스토어가 지워졌거나 재업로드 중이다. 대시보드가
                # '분석 시작'을 숨기는 기준을 API 에도 적용한다 (#450)
                if (
                    latest_upload is not None
                    and not latest_upload.fs_document_id
                ):
                    return {
                        "success": False,
                        "error_code": "LESSONPLAN_INDEX_MISSING",
                        "error": _INDEX_MISSING_MESSAGE,
                    }

                legacy_lessonplans = []
                if latest_upload is None:
                    legacy_lessonplans = (
                        self.lessonplan_storage.list_lessonplans(user_id)
                    )
                    has_file_search_documents = await asyncio.to_thread(
                        self._user_file_search_store_has_documents, user_id
                    )
                    if not legacy_lessonplans and not has_file_search_documents:
                        return {
                            "success": False,
                            "error": (
                                "분석할 문서가 없습니다. "
                                "수업 지도안을 먼저 업로드해주세요."
                            ),
                        }

                # 1. File Search Store ID 조회 (Phase 1 활용)
                store_ids = await self._get_store_ids(user_id)
                if not store_ids:
                    return {
                        "success": False,
                        "error": (
                            "평가기준 스토어를 찾을 수 없습니다. "
                            "관리자에게 문의하세요."
                        ),
                    }

                # Store ID 분리 및 역할 명확화
                user_store_id = store_ids[0]  # 사용자 업로드 수업 지도안
                rubric_store_id = store_ids[1]  # 평가기준 문서
                criteria_notice = None

                logger.info(
                    f"File Search Store 조회 완료:\n"
                    f"  - Rubric Store: {rubric_store_id}\n"
                    f"  - Lesson Store: {user_store_id}"
                )

                try:
                    rubric_metadata_filter = (
                        await CriteriaVectorService.active_stable_id_filter(
                            client=self.client,
                            store_display_name=settings.FS_RUBRIC_STORE_NAME,
                        )
                    )
                except Exception as e:
                    # 일시 오류는 이번 요청만 실패시키고 전역 상태는 그대로 둔다 (#465)
                    if is_transient_lookup_error(e):
                        raise
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
                full_prompt = self._build_analysis_prompt(system_prompt)
                logger.info("프롬프트 구성 완료 (Store 역할 명시 포함)")

                # 3. Gemini API 호출 (File Search - 평가기준 우선 순서)
                # 원문이 검사를 통과하지 못하면 두 패스를 한 번 더 부르고,
                # 그래도 나쁘면 저장하지 않는다(저장되면 409 로 굳는다) (#439)
                for attempt in (1, 2):
                    response = await asyncio.to_thread(
                        _call_gemini_with_file_search,
                        self.client,
                        self.model_name,
                        full_prompt,
                        rubric_store_id,
                        user_store_id,
                        rubric_metadata_filter,
                    )
                    if response is None:
                        # 1패스가 지도안을 찾지 못해 2패스를 건너뛰었다 (#449)
                        problems = ["1패스 지도안 검색 실패"]
                        error_code = "LESSONPLAN_NOT_RETRIEVED"
                        error = _NOT_RETRIEVED_MESSAGE
                    else:
                        raw_report = response.text or ""
                        reason = _finish_reason_name(response)
                        tokens = getattr(
                            getattr(response, "usage_metadata", None),
                            "candidates_token_count",
                            None,
                        )
                        logger.info(
                            "분석 응답 attempt=%d finish_reason=%s "
                            "output_tokens=%s chars=%d",
                            attempt,
                            reason,
                            tokens,
                            len(raw_report),
                        )
                        problems = _report_problems(raw_report, reason)
                        error_code = "INVALID_REPORT"
                        error = _INVALID_REPORT_MESSAGE
                    if not problems:
                        break
                    logger.warning(
                        "분석 보고서 검사 실패 attempt=%d %s",
                        attempt,
                        ", ".join(problems),
                    )
                else:
                    return {
                        "success": False,
                        "error_code": error_code,
                        "error": error,
                    }

                # 4. Markdown 보고서 후처리
                criteria_aliases = (
                    await self._collect_active_criteria_display_names()
                )
                lessonplan_original_filename = (
                    self._resolve_lessonplan_original_filename(
                        latest_upload=latest_upload,
                        legacy_lessonplans=legacy_lessonplans,
                    )
                )
                report = self._post_process_report(
                    raw_report,
                    criteria_aliases=criteria_aliases,
                    lessonplan_original_filename=lessonplan_original_filename,
                )

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
                                latest_upload.original_filename or "unknown"
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
                                    lessonplans, key=lambda x: x["created_at"]
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
                                (
                                    latest_upload,
                                    existing_report,
                                ) = await self._find_existing_report_for_latest_upload(
                                    user_id
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
                            user_id=user_id,
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
                                        Path(loser_path).unlink(missing_ok=True)
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
                    "saved_report": saved_report,
                }

        except asyncio.TimeoutError:
            logger.error("분석 타임아웃 (180초 초과)")
            return {"success": False, "error": "분석 시간 초과 (180초)"}

        except GeminiQuotaExhausted as e:
            logger.error(f"Gemini 쿼터 소진 (재시도 후 실패): {e}")
            return {
                "success": False,
                "error": (
                    "현재 분석 요청량이 많습니다. " "잠시 후 다시 시도해주세요."
                ),
                "error_code": "RESOURCE_EXHAUSTED",
            }

        except GeminiServerOverloaded as e:
            logger.error(f"Gemini 서버 혼잡 (재시도 후 실패): {e}")
            return {
                "success": False,
                "error": (
                    "AI 모델이 일시적으로 혼잡합니다. "
                    "잠시 후 다시 시도해주세요."
                ),
                "error_code": "MODEL_OVERLOADED",
            }

        except httpx.TransportError as e:
            # 원문에는 응답 헤더 줄이 섞일 수 있어 종류만 남긴다 (#368)
            logger.error("Gemini 전송 오류: %s", type(e).__name__)
            return {
                "success": False,
                "error": (
                    "AI 서비스 응답이 지연되고 있습니다. "
                    "잠시 후 다시 시도해주세요."
                ),
                "error_code": "MODEL_OVERLOADED",
            }

        except exceptions.GoogleAPIError as e:
            logger.error(f"Google API 오류: {e}")
            return {
                "success": False,
                "error": "AI 서비스 호출 중 오류가 발생했습니다. "
                "잠시 후 다시 시도해주세요.",
            }

        except Exception as e:
            logger.error(f"분석 실패: {e}", exc_info=True)
            return {"success": False, "error": "분석 중 오류 발생"}

    async def _get_store_ids(self, user_id: int) -> list[str]:
        """
        File Search Store ID 조회 (Phase 1 공통 유틸 사용)

        Args:
            user_id: 사용자 ID (User.id)

        Returns:
            Store ID 리스트 [user-{user_id}-store, rubricstore]
            (실제 반환 순서: 사용자 문서, 평가기준 문서)
        """
        try:
            # Phase 1의 get_dual_store_ids() 사용
            store_ids = await asyncio.to_thread(
                self.file_search_service.get_dual_store_ids, user_id
            )
            logger.info(f"✅ Store ID 조회 완료: {len(store_ids)}개")
            return store_ids
        except ValueError as e:
            # rubricstore 없음. 그 밖의 조회 오류는 호출부가 가른다 (#464)
            logger.error(f"❌ Store ID 조회 실패: {e}")
            return []

    def _user_file_search_store_has_documents(self, user_id: int) -> bool:
        store_name = f"user-{user_id}-store"
        safe_store_name = _sanitize_display_name(store_name)
        try:
            file_search_stores = (
                self.file_search_service.client.file_search_stores
            )
            for store in file_search_stores.list():
                if store.display_name not in {store_name, safe_store_name}:
                    continue
                documents = file_search_stores.documents.list(parent=store.name)
                return any(True for _ in documents)
        except Exception as exc:
            logger.warning(f"사용자 File Search Store 문서 확인 실패: {exc}")
        return False

    async def _find_existing_report_for_latest_upload(self, user_id: int):
        """
        사용자의 최신 업로드 이벤트와 그에 연결된 기존 보고서를 함께 조회.

        Returns:
            (LessonPlanUpload | None, AnalysisReport | None)
            - (None, None): 업로드 이력 자체가 없는 사용자
            - (upload, None): 최신 업로드는 있으나 분석 보고서는 아직 없음
            - (upload, report): 이미 분석 완료 → 차단해야 함
        """
        upload_result = await self.db.execute(
            select(LessonPlanUpload)
            .where(LessonPlanUpload.user_id == user_id)
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

    def _build_analysis_prompt(self, system_prompt: str) -> str:
        """
        분석 프롬프트 구성 (Store 역할 명시 포함)

        스토어 이름은 보고서에 그대로 인용되므로 역할 이름만 쓴다 (#174).

        Args:
            system_prompt: 시스템 프롬프트 (lesson_analysis)

        Returns:
            완전한 프롬프트
        """
        prompt_intro = (
            "**평가기준 문서의 자료를 바탕으로 "
            "사용자가 업로드한 수업 지도안을 평가하세요.**"
        )
        rubric_note = (
            "- **평가기준 문서**: 참고 자료로만 사용하며 "
            "답변 근거로 표시하지 않습니다."
        )
        lesson_note = (
            "- **사용자 수업 지도안**: 모든 평가 근거를 반드시 "
            "이 문서에서 찾고 인용하세요."
        )
        id_note = (
            "- File Search 스토어·문서 이름 등 내부 식별자는 "
            "보고서에 쓰지 마세요."
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
{id_note}

{task_intro}

1. 교육과정 목표 및 성격과의 부합
2. 내용 체계 및 성취기준 달성
3. 교수·학습 방법의 적절성
4. 평가 방향과의 일치
5. 개선 및 보완을 위한 제안

반드시 Markdown 형식의 보고서로 작성해주세요.
"""

    def _post_process_report(
        self,
        report: str,
        criteria_aliases: Optional[list[str]] = None,
        lessonplan_original_filename: Optional[str] = None,
    ) -> str:
        """
        보고서 후처리:
        0. `**분석 모델**:` 줄 제거, `**분석 일시**:` 를 서버 KST 시각으로 기입
        1. 'Vector Search 참고 자료' 섹션이 비구조화된 긴 텍스트일 경우
           목록으로 정리
        2. 'File Search 참고 문서' 섹션을 서버 렌더로 교체 (인자 제공 시).
           섹션이 없으면 보고서 끝에 부착.
        3. 본문 전체에서 이모지/픽토그램 제거
           (LLM이 출력했더라도 일관된 텍스트 형식 유지)

        Args:
            report: 원본 Markdown 보고서
            criteria_aliases: 활성 평가기준 표시 이름 목록 (정렬 완료)
            lessonplan_original_filename: 분석 대상 수업지도안 원본 파일명

        Returns:
            후처리된 보고서
        """
        import re

        try:
            # 0) LLM 이 학습된 양식으로 출력했을 수 있는 모델명 라인 제거.
            #    형태: `> - **분석 모델**: <임의 텍스트>` 또는
            #          `> **분석 모델**: <임의 텍스트>` (전후 공백 허용,
            #          dash prefix 옵션)
            report = re.sub(
                r"^\s*>\s*(?:-\s*)?\*\*분석\s*모델\*\*\s*:.*$\n?",
                "",
                report,
                flags=re.MULTILINE,
            )

            # 0-1) 분석 일시는 모델이 알 수 없으므로 서버 KST 시각으로 채운다.
            now = datetime.now(timezone(timedelta(hours=9))).strftime(
                "%Y-%m-%d %H:%M"
            )
            report = re.sub(
                r"^(\s*>\s*(?:-\s*)?\*\*분석\s*일시\*\*\s*:).*$",
                lambda m: f"{m.group(1)} {now}",
                report,
                count=1,
                flags=re.MULTILINE,
            )

            # 1) "Vector Search 참고 자료" 섹션 가독성 개선
            # 이모지 유무와 무관하게 매칭되도록 패턴에서 🔍 의존을 제거한다.
            pattern = (
                r"(###\s*(?:[^\n]*?)?Vector Search 참고 자료\s*\n)"
                r"(.*?)(\n###|\Z)"
            )
            match = re.search(pattern, report, flags=re.DOTALL)

            if match:
                header = match.group(1)
                content = match.group(2).strip()
                next_section = match.group(3)

                # 이미 구조화되어 있는지 확인 (목록/번호가 있으면 이미 구조화됨)
                already_structured = re.search(
                    r"^\s*[0-9]+\.|\s*-|\s*\*",
                    content,
                    re.MULTILINE,
                )
                if not already_structured and len(content) > 100:
                    sentences = re.split(r"(?<=[.!?])\s+", content)
                    sentences = [
                        s.strip() for s in sentences if len(s.strip()) > 20
                    ]
                    formatted = "\n".join([f"- {s}" for s in sentences[:8]])
                    new_section = f"{header}\n{formatted}\n{next_section}"
                    report = (
                        report[: match.start()]
                        + new_section
                        + report[match.end() :]
                    )

            # 2) "File Search 참고 문서" 섹션을 서버 렌더로 교체
            #    (인자 제공 시). 섹션이 없으면 보고서 끝에 부착.
            should_render_refs = (
                criteria_aliases is not None
                or lessonplan_original_filename is not None
            )
            if should_render_refs:
                body = self._render_file_search_references_section(
                    criteria_aliases=criteria_aliases or [],
                    lessonplan_original_filename=(lessonplan_original_filename),
                )
                refs_pattern = (
                    r"(###\s*(?:[^\n]*?)?File Search 참고 문서\s*\n)"
                    r"(.*?)(\n###|\Z)"
                )
                refs_match = re.search(refs_pattern, report, flags=re.DOTALL)
                if refs_match:
                    header = refs_match.group(1)
                    next_section = refs_match.group(3)
                    new_section = f"{header}{body}\n{next_section}"
                    report = (
                        report[: refs_match.start()]
                        + new_section
                        + report[refs_match.end() :]
                    )
                else:
                    # 섹션이 누락된 경우 끝에 부착
                    suffix = "\n\n### File Search 참고 문서\n" f"{body}\n"
                    if not report.endswith("\n"):
                        report += "\n"
                    report += suffix

            # 살균보다 먼저 닫아야 짝 없는 ** 가 다음 줄의 ** 와 묶이지 않는다 (#441)
            report = _close_dangling_bold(report)

            # 3) 본문 이모지 제거. 블록 인용 라인은 사용자 문서
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
        citation_start = re.compile(r"^\s*>\s*\*\*[^*]*수업\s*지도안[^*]*\*\*")
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

    async def _collect_active_criteria_display_names(self) -> list[str]:
        """활성 평가기준의 표시 이름(alias)을 정렬해 반환한다.

        정렬: activated_at 내림차순, stable_id 내림차순 (CriteriaVectorService
        ._get_active_stable_ids 와 동일한 정책).

        alias 가 None/빈 항목은 결과에서 제외하고 경고 로그를 남긴다.
        alias_map fetch 자체가 실패하면 빈 리스트를 반환하고 예외를
        전파하지 않는다.
        """
        from app.services.criteria_alias_map_service import (
            CriteriaAliasMapService,
        )
        from app.services.criteria_reconciliation_service import (
            is_legacy_surrogate_stable_id,
        )

        try:
            alias_svc = CriteriaAliasMapService(
                client=self.client,
                store_display_name=settings.FS_RUBRIC_STORE_NAME,
            )
            fetched = await alias_svc.fetch()
        except Exception as exc:
            logger.warning(
                "활성 평가기준 alias 목록 조회 실패 "
                f"(참고 문서 표시 생략): {exc}"
            )
            return []

        if not fetched:
            return []

        _, alias_map = fetched

        active_entries = [
            (stable_id, entry)
            for stable_id, entry in alias_map.entries.items()
            if (
                entry.status == "active"
                and not is_legacy_surrogate_stable_id(stable_id)
            )
        ]

        active_entries.sort(
            key=lambda item: (item[1].activated_at or "", item[0]),
            reverse=True,
        )

        names: list[str] = []
        for stable_id, entry in active_entries:
            alias = (entry.alias or "").strip()
            if not alias:
                logger.warning(
                    f"활성 평가기준 alias 누락: stable_id={stable_id} "
                    "(보고서 참고 문서 목록에서 제외)"
                )
                continue
            names.append(alias)
        return names

    @staticmethod
    def _resolve_lessonplan_original_filename(
        latest_upload,
        legacy_lessonplans: list,
    ) -> Optional[str]:
        """분석 대상 수업지도안의 원본 파일명을 결정한다.

        - latest_upload 가 있으면 그 original_filename
        - 없으면 legacy_lessonplans 중 created_at 최댓값 항목의
          original_filename
        - 둘 다 없으면 None
        """
        if latest_upload is not None:
            return getattr(latest_upload, "original_filename", None)
        if legacy_lessonplans:
            latest = max(legacy_lessonplans, key=lambda x: x["created_at"])
            return latest.get("original_filename")
        return None

    @staticmethod
    def _render_file_search_references_section(
        criteria_aliases: list[str],
        lessonplan_original_filename: Optional[str],
    ) -> str:
        """### File Search 참고 문서 섹션의 본문(헤더 제외) 마크다운을 생성한다.

        - 활성 평가기준 표시 이름들 (이미 정렬됨)
        - 수업 지도안 원본 파일명 (있을 경우)
        둘 다 비면 placeholder 반환.
        """
        items: list[str] = list(criteria_aliases)
        if lessonplan_original_filename:
            items.append(lessonplan_original_filename)
        if not items:
            return "(표시할 항목이 없습니다)"
        return "\n".join(f"- {item}" for item in items)

    def _extract_citations(self, response) -> Optional[dict]:
        """
        Citation 정보 추출 (QnA 패턴 재사용)

        Args:
            response: Gemini API 응답

        Returns:
            Citation 정보 딕셔너리
        """
        citations = {"used_criteria": [], "grounding_chunks": []}

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
