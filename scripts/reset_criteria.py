#!/usr/bin/env python3
"""
평가 기준 목록 초기화 스크립트
모든 평가 기준 데이터를 안전하게 삭제합니다.
"""
import asyncio
import sys
import os
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.repositories.criteria_repository import CriteriaRepository
from app.services.criteria_embedding_service import CriteriaEmbeddingService


async def reset_all_criteria():
    """모든 평가 기준 데이터 초기화"""

    print("=" * 60)
    print("평가 기준 목록 초기화")
    print("=" * 60)
    print()

    # 데이터베이스 연결
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
    )

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        repo = CriteriaRepository(session)

        # 1. 현재 평가 기준 목록 조회
        print("📋 현재 평가 기준 목록 조회 중...")
        documents, total = await repo.list_all(page=1, page_size=1000)

        if total == 0:
            print("✅ 삭제할 평가 기준이 없습니다.")
            return

        print(f"   총 {total}개의 평가 기준이 발견되었습니다.\n")

        for i, doc in enumerate(documents, 1):
            print(f"   {i}. ID: {doc.id}, 제목: {doc.title}")
            print(f"      상태: {doc.status}, Vector Store ID: {doc.vector_store_id}")
            print(f"      파일: {doc.file_path}\n")

        # 2. 확인 요청
        print("⚠️  경고: 이 작업은 되돌릴 수 없습니다!")
        print("   - Vector DB에서 임베딩 데이터 삭제")
        print("   - 데이터베이스에서 메타데이터 삭제")
        print("   - 파일 시스템에서 파일 삭제")
        print()

        response = input("계속하시겠습니까? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("❌ 취소되었습니다.")
            return

        print()
        print("🗑️  삭제 작업 시작...")
        print()

        # 3. Vector DB 삭제
        print("📡 Vector DB 삭제 중...")
        embedding_service = CriteriaEmbeddingService()
        failed_vectors = []

        for i, doc in enumerate(documents, 1):
            if doc.vector_store_id:
                try:
                    print(f"   [{i}/{total}] Vector Store 삭제: {doc.vector_store_id}")
                    success = await embedding_service.delete_store(doc.vector_store_id)
                    if not success:
                        failed_vectors.append(f"{doc.title} (ID: {doc.vector_store_id})")
                        print(f"      ⚠️  실패: {doc.title}")
                    else:
                        print(f"      ✅ 성공")
                except Exception as e:
                    failed_vectors.append(f"{doc.title} (오류: {str(e)})")
                    print(f"      ❌ 오류: {e}")

        if failed_vectors:
            print()
            print("⚠️  다음 Vector Store 삭제에 실패했습니다:")
            for failed in failed_vectors:
                print(f"   - {failed}")
            print()
            response = input("계속하시겠습니까? (yes/no): ")
            if response.lower() not in ['yes', 'y']:
                print("❌ 취소되었습니다. (데이터베이스는 변경되지 않았습니다)")
                return

        print()

        # 4. 데이터베이스 삭제
        print("🗄️  데이터베이스 삭제 중...")
        deleted_count = await repo.delete_all()
        await session.commit()
        print(f"   ✅ {deleted_count}개의 레코드 삭제 완료")
        print()

        # 5. 파일 삭제
        print("📁 파일 시스템 삭제 중...")
        deleted_files = 0
        failed_files = []

        for i, doc in enumerate(documents, 1):
            file_path = Path(doc.file_path)
            if file_path.exists():
                try:
                    os.remove(file_path)
                    deleted_files += 1
                    print(f"   [{i}/{total}] ✅ 파일 삭제: {file_path.name}")
                except Exception as e:
                    failed_files.append(f"{file_path.name} (오류: {str(e)})")
                    print(f"   [{i}/{total}] ❌ 파일 삭제 실패: {e}")
            else:
                print(f"   [{i}/{total}] ⚠️  파일 없음: {file_path.name}")

        print()
        print(f"   ✅ {deleted_files}개의 파일 삭제 완료")

        if failed_files:
            print()
            print("⚠️  다음 파일 삭제에 실패했습니다:")
            for failed in failed_files:
                print(f"   - {failed}")

        print()
        print("=" * 60)
        print("✅ 평가 기준 목록 초기화 완료")
        print("=" * 60)
        print()
        print("요약:")
        print(f"   - Vector DB: {total - len(failed_vectors)}/{total} 삭제 성공")
        print(f"   - 데이터베이스: {deleted_count}개 레코드 삭제")
        print(f"   - 파일 시스템: {deleted_files}개 파일 삭제")
        print()


if __name__ == "__main__":
    try:
        asyncio.run(reset_all_criteria())
    except KeyboardInterrupt:
        print("\n\n❌ 사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
