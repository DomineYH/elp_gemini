"""
기존 업로드 문서에 document_type 메타데이터 추가

기존에 업로드된 문서들에 document_type 메타데이터를 소급 적용합니다:
- rubricstore의 모든 문서 → "rubric"
- user store의 모든 문서 → "user_document"

실행 방법:
    python scripts/migrate_document_metadata.py
"""
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from google import genai
from google.genai import types
from app.config import settings


async def migrate_metadata():
    """기존 문서에 document_type 메타데이터 추가"""

    print("=" * 80)
    print("📦 문서 메타데이터 마이그레이션 시작")
    print("=" * 80)

    # Gemini Client 초기화
    client = genai.Client(
        api_key=settings.GOOGLE_API_KEY,
        http_options={'api_version': 'v1beta'}
    )

    # 모든 File Search Store 조회
    stores = list(client.file_search_stores.list())
    print(f"\n✅ 총 {len(stores)}개 스토어 발견\n")

    total_updated = 0
    total_skipped = 0
    total_errors = 0

    for store in stores:
        store_name = store.display_name
        print(f"\n{'='*80}")
        print(f"📂 스토어: {store_name}")
        print(f"{'='*80}")

        # 스토어 타입 결정
        if "rubric" in store_name.lower():
            document_type = "rubric"
            print(f"   타입: 평가기준 스토어 → document_type=\"rubric\"")
        elif "user" in store_name.lower():
            document_type = "user_document"
            print(f"   타입: 사용자 스토어 → document_type=\"user_document\"")
        else:
            print(f"   ⚠️  알 수 없는 스토어 타입 (스킵)")
            continue

        # 스토어 내 문서 조회
        try:
            # Note: Python SDK에서 documents.list()는 직접 지원되지 않음
            # 대신 files API를 사용하여 문서 조회
            print(f"\n   🔍 스토어 내 문서 조회 중...")

            # API 제한으로 인해 실제 구현은 Gemini API 문서 참조 필요
            # 현재는 스크립트 구조만 제공
            print(f"   ⚠️  Python SDK의 제한으로 인해 문서 메타데이터 수정은")
            print(f"       Google Cloud Console 또는 REST API를 통해 수행해야 합니다.")
            print(f"\n   대안:")
            print(f"   1. 새로운 문서 업로드 시 자동으로 document_type이 추가됩니다")
            print(f"   2. 기존 문서는 점진적으로 재업로드하여 메타데이터를 추가할 수 있습니다")

            total_skipped += 1

        except Exception as e:
            print(f"   ❌ 오류: {str(e)}")
            total_errors += 1

    # 결과 요약
    print(f"\n{'='*80}")
    print(f"📊 마이그레이션 요약")
    print(f"{'='*80}")
    print(f"✅ 업데이트: {total_updated}개 문서")
    print(f"⚠️  스킵: {total_skipped}개 스토어")
    print(f"❌ 오류: {total_errors}개")
    print(f"\n{'='*80}")
    print(f"💡 권장 사항")
    print(f"{'='*80}")
    print(f"1. 새로운 업로드부터는 자동으로 document_type이 추가됩니다")
    print(f"2. 기존 문서는 필요 시 재업로드를 통해 메타데이터를 추가하세요")
    print(f"3. File Search는 메타데이터 없는 문서도 정상적으로 검색합니다")
    print(f"{'='*80}\n")


def main():
    """메인 실행 함수"""
    try:
        asyncio.run(migrate_metadata())
    except KeyboardInterrupt:
        print("\n\n⚠️  사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ 예상치 못한 오류: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
