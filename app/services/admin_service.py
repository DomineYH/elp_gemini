"""
관리자 서비스
메트릭 집계, 사용자 활동 조회, QnA 로그 필터링
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from app.models.users import User
from app.models.documents import Document
from app.models.qa_logs import QALog
from app.models.prompts import SystemPrompt
from app.models.evaluations import EvaluationRun, EvaluationReport

logger = logging.getLogger(__name__)


class AdminService:
    """관리자 서비스 클래스"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_dashboard_metrics(self) -> Dict[str, int]:
        """
        대시보드 메트릭 집계

        Returns:
            메트릭 딕셔너리
        """
        try:
            seven_days_ago = datetime.now() - timedelta(days=7)

            # 전체 사용자 수
            total_users = await self.db.scalar(
                select(func.count(User.id))
            )

            # 전체 문서 수 (삭제된 문서 제외)
            total_documents = await self.db.scalar(
                select(func.count(Document.id)).where(
                    Document.status != "deleted"
                )
            )

            # 최근 7일 문서 업로드 수
            documents_last_7days = await self.db.scalar(
                select(func.count(Document.id)).where(
                    and_(
                        Document.uploaded_at >= seven_days_ago,
                        Document.status != "deleted",
                    )
                )
            )

            # 전체 QnA 로그 수
            total_qna_logs = await self.db.scalar(
                select(func.count(QALog.id))
            )

            # 최근 7일 QnA 요청 수
            qna_logs_last_7days = await self.db.scalar(
                select(func.count(QALog.id)).where(
                    QALog.created_at >= seven_days_ago
                )
            )

            # 전체 평가 실행 수
            total_evaluation_runs = await self.db.scalar(
                select(func.count(EvaluationRun.id))
            )

            # 최근 7일 평가 실행 수
            evaluation_runs_last_7days = await self.db.scalar(
                select(func.count(EvaluationRun.id)).where(
                    EvaluationRun.started_at >= seven_days_ago
                )
            )

            # 활성 시스템 프롬프트 수
            active_prompts = await self.db.scalar(
                select(func.count(SystemPrompt.id)).where(
                    SystemPrompt.is_active == True
                )
            )

            return {
                "total_users": total_users or 0,
                "total_documents": total_documents or 0,
                "documents_last_7days": documents_last_7days or 0,
                "total_qna_logs": total_qna_logs or 0,
                "qna_logs_last_7days": qna_logs_last_7days or 0,
                "total_evaluation_runs": total_evaluation_runs or 0,
                "evaluation_runs_last_7days": evaluation_runs_last_7days
                or 0,
                "active_prompts": active_prompts or 0,
            }

        except Exception as e:
            logger.error(f"메트릭 집계 실패: {str(e)}")
            raise

    async def get_users_with_activity(
        self, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        사용자 목록 조회 (활동 정보 포함)

        Args:
            limit: 페이지당 사용자 수
            offset: 페이지 오프셋

        Returns:
            사용자 목록
        """
        try:
            # 사용자 기본 정보 조회
            result = await self.db.execute(
                select(User)
                .order_by(User.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            users = result.scalars().all()

            # 각 사용자의 활동 정보 추가
            users_with_activity = []
            for user in users:
                # 문서 수
                doc_count = await self.db.scalar(
                    select(func.count(Document.id)).where(
                        and_(
                            Document.user_id == user.id,
                            Document.status != "deleted",
                        )
                    )
                )

                # QnA 수
                qna_count = await self.db.scalar(
                    select(func.count(QALog.id)).where(
                        QALog.user_id == user.id
                    )
                )

                users_with_activity.append(
                    {
                        "id": user.id,
                        "email": user.email,
                        "is_admin": user.is_admin,
                        "created_at": user.created_at,
                        "document_count": doc_count or 0,
                        "qna_count": qna_count or 0,
                    }
                )

            return users_with_activity

        except Exception as e:
            logger.error(f"사용자 목록 조회 실패: {str(e)}")
            raise

    async def get_user_detail(
        self, user_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        사용자 상세 정보 조회

        Args:
            user_id: 사용자 ID

        Returns:
            사용자 상세 정보
        """
        try:
            # 사용자 기본 정보
            user = await self.db.get(User, user_id)
            if not user:
                return None

            # 문서 목록
            doc_result = await self.db.execute(
                select(Document)
                .where(
                    and_(
                        Document.user_id == user_id,
                        Document.status != "deleted",
                    )
                )
                .order_by(Document.uploaded_at.desc())
                .limit(20)
            )
            documents = doc_result.scalars().all()

            # 최근 QnA 로그 (최대 10개)
            qna_result = await self.db.execute(
                select(QALog)
                .where(QALog.user_id == user_id)
                .order_by(QALog.created_at.desc())
                .limit(10)
            )
            qna_logs = qna_result.scalars().all()

            # 평가 실행 목록
            eval_result = await self.db.execute(
                select(EvaluationRun)
                .where(EvaluationRun.user_id == user_id)
                .order_by(EvaluationRun.started_at.desc())
                .limit(20)
            )
            evaluation_runs = eval_result.scalars().all()

            return {
                "id": user.id,
                "email": user.email,
                "is_admin": user.is_admin,
                "created_at": user.created_at,
                "documents": [
                    {
                        "id": doc.id,
                        "title": doc.title,
                        "status": doc.status,
                        "uploaded_at": doc.uploaded_at,
                    }
                    for doc in documents
                ],
                "recent_qna_logs": [
                    {
                        "id": log.id,
                        "document_id": log.document_id,
                        "question": log.question[:100] + "..."
                        if len(log.question) > 100
                        else log.question,
                        "created_at": log.created_at,
                    }
                    for log in qna_logs
                ],
                "evaluation_runs": [
                    {
                        "id": run.id,
                        "document_id": run.document_id,
                        "status": run.status,
                        "started_at": run.started_at,
                    }
                    for run in evaluation_runs
                ],
            }

        except Exception as e:
            logger.error(f"사용자 상세 조회 실패: {str(e)}")
            raise

    async def get_qna_logs(
        self,
        user_id: Optional[int] = None,
        document_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        QnA 로그 필터링 및 검색

        Args:
            user_id: 사용자 ID 필터
            document_id: 문서 ID 필터
            start_date: 시작 날짜
            end_date: 종료 날짜
            limit: 페이지당 로그 수
            offset: 페이지 오프셋

        Returns:
            QnA 로그 목록
        """
        try:
            # 기본 쿼리
            query = select(
                QALog,
                Document.title,
                User.email,
                SystemPrompt.version,
            ).join(Document, QALog.document_id == Document.id).join(
                User, QALog.user_id == User.id
            ).join(
                SystemPrompt, QALog.prompt_id == SystemPrompt.id
            )

            # 필터 조건 추가
            conditions = []
            if user_id:
                conditions.append(QALog.user_id == user_id)
            if document_id:
                conditions.append(QALog.document_id == document_id)
            if start_date:
                conditions.append(QALog.created_at >= start_date)
            if end_date:
                conditions.append(QALog.created_at <= end_date)

            if conditions:
                query = query.where(and_(*conditions))

            # 정렬 및 페이지네이션
            query = (
                query.order_by(QALog.created_at.desc())
                .limit(limit)
                .offset(offset)
            )

            result = await self.db.execute(query)
            rows = result.all()

            return [
                {
                    "id": row.QALog.id,
                    "document_id": row.QALog.document_id,
                    "document_title": row.title,
                    "user_id": row.QALog.user_id,
                    "user_email": row.email,
                    "prompt_id": row.QALog.prompt_id,
                    "prompt_version": row.version,
                    "question": row.QALog.question,
                    "answer": row.QALog.answer,
                    "latency_ms": row.QALog.latency_ms,
                    "created_at": row.QALog.created_at,
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"QnA 로그 조회 실패: {str(e)}")
            raise

    async def get_system_prompts(
        self, prompt_type: Optional[str] = None
    ) -> List[SystemPrompt]:
        """
        시스템 프롬프트 목록 조회

        Args:
            prompt_type: 프롬프트 타입 필터

        Returns:
            시스템 프롬프트 목록
        """
        try:
            query = select(SystemPrompt).order_by(
                SystemPrompt.type,
                SystemPrompt.version.desc(),
            )

            if prompt_type:
                query = query.where(SystemPrompt.type == prompt_type)

            result = await self.db.execute(query)
            return result.scalars().all()

        except Exception as e:
            logger.error(f"프롬프트 목록 조회 실패: {str(e)}")
            raise

    async def create_system_prompt(
        self, prompt_type: str, content: str, created_by: int
    ) -> SystemPrompt:
        """
        새 시스템 프롬프트 생성

        Args:
            prompt_type: 프롬프트 타입
            content: 프롬프트 내용
            created_by: 생성자 ID

        Returns:
            생성된 시스템 프롬프트
        """
        try:
            # 현재 타입의 최대 버전 찾기
            max_version = await self.db.scalar(
                select(func.max(SystemPrompt.version)).where(
                    SystemPrompt.type == prompt_type
                )
            )
            new_version = (max_version or 0) + 1

            # 새 프롬프트 생성
            prompt = SystemPrompt(
                type=prompt_type,
                version=new_version,
                content=content,
                is_active=False,  # 기본적으로 비활성
                created_by=created_by,
            )
            self.db.add(prompt)
            await self.db.commit()
            await self.db.refresh(prompt)

            logger.info(
                f"새 프롬프트 생성: type={prompt_type}, "
                f"version={new_version}"
            )
            return prompt

        except Exception as e:
            logger.error(f"프롬프트 생성 실패: {str(e)}")
            await self.db.rollback()
            raise

    async def activate_system_prompt(
        self, prompt_id: int
    ) -> SystemPrompt:
        """
        시스템 프롬프트 활성화 (동일 타입의 다른 프롬프트는 비활성화)

        Args:
            prompt_id: 활성화할 프롬프트 ID

        Returns:
            활성화된 시스템 프롬프트
        """
        try:
            # 대상 프롬프트 가져오기
            prompt = await self.db.get(SystemPrompt, prompt_id)
            if not prompt:
                raise ValueError("프롬프트를 찾을 수 없습니다")

            # 동일 타입의 다른 프롬프트 비활성화
            await self.db.execute(
                select(SystemPrompt)
                .where(
                    and_(
                        SystemPrompt.type == prompt.type,
                        SystemPrompt.id != prompt_id,
                    )
                )
                .with_for_update()
            )

            result = await self.db.execute(
                select(SystemPrompt).where(
                    and_(
                        SystemPrompt.type == prompt.type,
                        SystemPrompt.id != prompt_id,
                    )
                )
            )
            old_prompts = result.scalars().all()

            for old_prompt in old_prompts:
                old_prompt.is_active = False

            # 대상 프롬프트 활성화
            prompt.is_active = True
            await self.db.commit()

            logger.info(
                f"프롬프트 활성화: id={prompt_id}, "
                f"type={prompt.type}, version={prompt.version}"
            )
            return prompt

        except Exception as e:
            logger.error(f"프롬프트 활성화 실패: {str(e)}")
            await self.db.rollback()
            raise
