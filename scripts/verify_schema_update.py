#!/usr/bin/env python3
"""
데이터베이스 스키마 업데이트 검증 스크립트

Usage:
    python scripts/verify_schema_update.py
"""
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect
from app.db import engine, Base
from app.models.documents import Document
from app.models.qa_logs import QALog


async def verify_schema():
    """스키마 검증 수행"""
    print("=" * 60)
    print("데이터베이스 스키마 검증 시작")
    print("=" * 60)

    async with engine.begin() as conn:
        # 테이블 존재 확인
        inspector = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn)
        )

        # Document 테이블 검증
        print("\n[Document 테이블 검증]")
        doc_columns = await conn.run_sync(
            lambda sync_conn: inspector.get_columns("documents")
        )

        required_doc_fields = {
            "file_search_file_id": "VARCHAR(255)",
            "store_id": "VARCHAR(255)",
        }

        doc_check = {}
        for col in doc_columns:
            col_name = col["name"]
            if col_name in required_doc_fields:
                doc_check[col_name] = True
                print(
                    f"  ✅ {col_name}: {col['type']} "
                    f"(nullable={col['nullable']})"
                )

        # QALog 테이블 검증
        print("\n[QALog 테이블 검증]")
        qa_columns = await conn.run_sync(
            lambda sync_conn: inspector.get_columns("qa_logs")
        )

        required_qa_fields = {
            "citations": "JSON",
            "sources_count": "INTEGER",
        }

        qa_check = {}
        for col in qa_columns:
            col_name = col["name"]
            if col_name in required_qa_fields:
                qa_check[col_name] = True
                default = col.get("default", "None")
                print(
                    f"  ✅ {col_name}: {col['type']} "
                    f"(nullable={col['nullable']}, default={default})"
                )

        # 결과 요약
        print("\n" + "=" * 60)
        print("검증 결과 요약")
        print("=" * 60)

        all_passed = True

        # Document 검증
        print("\n[Document 필드]")
        for field in required_doc_fields:
            if doc_check.get(field):
                print(f"  ✅ {field}: 정상")
            else:
                print(f"  ❌ {field}: 누락")
                all_passed = False

        # QALog 검증
        print("\n[QALog 필드]")
        for field in required_qa_fields:
            if qa_check.get(field):
                print(f"  ✅ {field}: 정상")
            else:
                print(f"  ❌ {field}: 누락")
                all_passed = False

        print("\n" + "=" * 60)
        if all_passed:
            print("✅ 모든 스키마 업데이트가 정상적으로 적용되었습니다!")
            print("=" * 60)
            return 0
        else:
            print("❌ 일부 필드가 누락되었습니다. 마이그레이션을 확인하세요.")
            print("=" * 60)
            return 1


async def test_model_creation():
    """모델 인스턴스 생성 테스트"""
    print("\n[모델 인스턴스 생성 테스트]")

    try:
        # Document 모델 테스트
        doc = Document(
            user_id=1,
            random_key="test_key_123",
            title="Test Document",
            file_path="/tmp/test.pdf",
            file_size=1024,
            file_search_file_id="documents/test123",
            store_id="fileSearchStores/store456",
        )
        print("  ✅ Document 모델 생성 성공")

        # QALog 모델 테스트
        qa_log = QALog(
            document_id=1,
            user_id=1,
            prompt_id=1,
            question="테스트 질문",
            answer="테스트 답변",
            model_name="gemini-1.5-pro",
            citations={
                "sources": [
                    {
                        "uri": "documents/abc123",
                        "title": "example.pdf",
                    }
                ]
            },
            sources_count=1,
        )
        print("  ✅ QALog 모델 생성 성공 (citations 포함)")

        # Citations 없는 QALog (기존 레코드 호환성)
        qa_log_legacy = QALog(
            document_id=1,
            user_id=1,
            prompt_id=1,
            question="레거시 질문",
            answer="레거시 답변",
            model_name="gemini-1.5-flash",
        )
        print("  ✅ QALog 모델 생성 성공 (citations 없음 - 레거시 호환)")

        return True
    except Exception as e:
        print(f"  ❌ 모델 생성 실패: {e}")
        return False


async def main():
    """메인 실행 함수"""
    try:
        # 1. 스키마 검증
        exit_code = await verify_schema()

        # 2. 모델 인스턴스 생성 테스트
        model_test_passed = await test_model_creation()

        # 3. 최종 결과
        print("\n" + "=" * 60)
        print("전체 검증 완료")
        print("=" * 60)

        if exit_code == 0 and model_test_passed:
            print("✅ 모든 검증 통과!")
            print("\n다음 단계:")
            print("  1. Phase 4: Repository 레이어 업데이트")
            print("  2. Phase 5: Service 레이어 통합")
            return 0
        else:
            print("❌ 일부 검증 실패. 로그를 확인하세요.")
            return 1

    except Exception as e:
        print(f"\n❌ 검증 중 오류 발생: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
