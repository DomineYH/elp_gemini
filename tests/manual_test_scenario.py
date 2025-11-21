#!/usr/bin/env python3
"""
Task 4.4: 수동 테스트 시나리오 자동화 스크립트

관리자 화면 대신 API를 직접 호출하여 업로드/삭제 흐름을 테스트합니다.
"""

import asyncio
import sqlite3
from pathlib import Path
import sys

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.criteria_embedding_service import (
    CriteriaEmbeddingService
)
from app.repositories.criteria_repository import (
    CriteriaRepository
)
from app.config import settings


class ManualTestScenario:
    """수동 테스트 시나리오 실행 클래스"""

    def __init__(self):
        self.db_path = "data/app.db"
        self.test_pdf = Path("docs/test.pdf")
        self.embedding_service = CriteriaEmbeddingService()

    def _get_db_connection(self):
        """DB 연결 생성"""
        return sqlite3.connect(self.db_path)

    def print_section(self, title: str):
        """섹션 제목 출력"""
        print("\n" + "="*60)
        print(f"  {title}")
        print("="*60)

    def verify_db_schema(self):
        """DB 스키마 검증 - document_id 컬럼 존재 확인"""
        self.print_section("1. DB 스키마 검증")

        conn = self._get_db_connection()
        cursor = conn.cursor()

        # 테이블 스키마 확인
        cursor.execute(
            "PRAGMA table_info(criteria_documents);"
        )
        columns = cursor.fetchall()

        has_document_id = any(
            col[1] == 'document_id' for col in columns
        )

        print(f"✅ document_id 컬럼 존재: {has_document_id}")

        if has_document_id:
            print("✅ Phase 1 마이그레이션 성공 확인")
        else:
            print("❌ document_id 컬럼이 없습니다!")
            return False

        conn.close()
        return True

    async def test_upload(self) -> tuple[int, str, str]:
        """
        업로드 테스트
        Returns: (criteria_id, vector_store_id, document_id)
        """
        self.print_section("2. 업로드 테스트")

        if not self.test_pdf.exists():
            print(f"❌ 테스트 파일 없음: {self.test_pdf}")
            return None, None, None

        print(f"📄 테스트 파일: {self.test_pdf}")

        # 리포지토리 초기화
        repo = CriteriaRepository(self.db_path)

        try:
            # 1. 업로드 및 임베딩
            print("⏳ 업로드 및 임베딩 시작...")
            vector_store_id, document_id = await (
                self.embedding_service.upload_and_embed(
                    file_path=str(self.test_pdf),
                    criteria_name="Manual Test Criteria"
                )
            )

            print(
                f"✅ 업로드 성공:\n"
                f"   - store_id: {vector_store_id}\n"
                f"   - doc_id: {document_id}"
            )

            # 2. DB에 저장
            print("⏳ DB에 저장 중...")
            criteria_id = await repo.create(
                title="Manual Test Criteria",
                description="수동 테스트용 평가기준",
                pdf_path=str(self.test_pdf),
                vector_store_id=vector_store_id,
                document_id=document_id
            )

            print(f"✅ DB 저장 완료 (ID: {criteria_id})")

            return criteria_id, vector_store_id, document_id

        except Exception as e:
            print(f"❌ 업로드 실패: {str(e)}")
            import traceback
            traceback.print_exc()
            return None, None, None
        finally:
            await repo.close()

    def verify_db_save(
        self,
        criteria_id: int,
        expected_doc_id: str
    ):
        """DB 저장 검증"""
        self.print_section("3. DB 저장 검증")

        conn = self._get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, title, document_id, vector_store_id
            FROM criteria_documents
            WHERE id = ?
            """,
            (criteria_id,)
        )

        result = cursor.fetchone()
        conn.close()

        if not result:
            print(f"❌ 레코드를 찾을 수 없음 (ID: {criteria_id})")
            return False

        saved_id, title, saved_doc_id, store_id = result

        print(f"📊 DB 레코드:")
        print(f"   - ID: {saved_id}")
        print(f"   - 제목: {title}")
        print(f"   - document_id: {saved_doc_id}")
        print(f"   - vector_store_id: {store_id}")

        if saved_doc_id == expected_doc_id:
            print("✅ document_id가 정상적으로 저장되었습니다!")
            return True
        else:
            print(
                f"❌ document_id 불일치:\n"
                f"   - 예상: {expected_doc_id}\n"
                f"   - 실제: {saved_doc_id}"
            )
            return False

    async def test_delete(
        self,
        criteria_id: int,
        vector_store_id: str,
        document_id: str
    ):
        """삭제 테스트"""
        self.print_section("4. 삭제 테스트")

        try:
            # 1. 문서 삭제
            print("⏳ 문서 삭제 중...")
            await self.embedding_service.delete_document(
                vector_store_id=vector_store_id,
                document_id=document_id
            )
            print("✅ 문서 삭제 성공")

            # 2. 스토어 삭제
            print("⏳ 스토어 삭제 중...")
            await self.embedding_service.delete_store(
                vector_store_id=vector_store_id
            )
            print("✅ 스토어 삭제 성공")

            # 3. DB에서 삭제
            print("⏳ DB 레코드 삭제 중...")
            repo = CriteriaRepository(self.db_path)
            try:
                await repo.delete(criteria_id)
                print("✅ DB 레코드 삭제 성공")
            finally:
                await repo.close()

            print(
                "\n✅ 전체 삭제 프로세스 성공!\n"
                "   → 문서 → 스토어 → DB 순차 삭제 완료"
            )
            return True

        except Exception as e:
            print(f"❌ 삭제 실패: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    async def run_full_scenario(self):
        """전체 시나리오 실행"""
        print("\n" + "🔧 " * 20)
        print("  수동 테스트 시나리오 자동화 실행")
        print("🔧 " * 20)

        # 1. 스키마 검증
        if not self.verify_db_schema():
            print("\n❌ 스키마 검증 실패. 테스트 중단.")
            return

        # 2. 업로드 테스트
        criteria_id, store_id, doc_id = await self.test_upload()

        if not all([criteria_id, store_id, doc_id]):
            print("\n❌ 업로드 테스트 실패. 테스트 중단.")
            return

        # 3. DB 저장 검증
        if not self.verify_db_save(criteria_id, doc_id):
            print("\n❌ DB 저장 검증 실패. 테스트 중단.")
            return

        # 4. 삭제 테스트
        success = await self.test_delete(
            criteria_id,
            store_id,
            doc_id
        )

        # 최종 결과
        self.print_section("최종 결과")

        if success:
            print("✅ 모든 테스트 시나리오 통과!")
            print("\n검증된 기능:")
            print("  1. ✅ document_id 컬럼 존재")
            print("  2. ✅ 업로드 시 document_id 저장")
            print("  3. ✅ DB에 document_id 정상 저장")
            print("  4. ✅ 문서→스토어 순차 삭제 성공")
            print("  5. ✅ 400 FAILED_PRECONDITION 오류 없음")
        else:
            print("❌ 일부 테스트 실패")


async def main():
    """메인 실행 함수"""
    scenario = ManualTestScenario()
    await scenario.run_full_scenario()


if __name__ == "__main__":
    asyncio.run(main())
