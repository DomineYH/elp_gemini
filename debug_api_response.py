"""
Google File Search API 응답 구조 디버깅
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services.file_search_service import FileSearchService
from app.config import settings


async def main():
    """디버깅 메인 함수"""
    print("=" * 60)
    print("Google File Search API 응답 구조 분석")
    print("=" * 60)

    # 테스트 파일 찾기
    upload_dir = Path(settings.UPLOAD_DIR)
    pdf_files = list(upload_dir.glob("*.pdf"))

    if not pdf_files:
        print("❌ PDF 파일 없음")
        return

    test_file = pdf_files[0]
    print(f"\n테스트 파일: {test_file.name}")

    # FileSearchService 초기화
    fs_service = FileSearchService()
    store = fs_service._get_or_create_store("main-store")

    print(f"\n1. 스토어 정보:")
    print(f"   - name: {store.name}")
    print(f"   - display_name: {store.display_name}")

    # 저수준 API 호출
    print(f"\n2. API 호출 중...")
    operation = fs_service.client.file_search_stores.upload_to_file_search_store(
        file_search_store_name=store.name,
        file=str(test_file),
        config={
            'chunking_config': {
                'white_space_config': {
                    'max_tokens_per_chunk': 512,
                    'max_overlap_tokens': 100
                }
            },
            'custom_metadata': [
                {"key": "test_key", "string_value": "test_value"}
            ]
        }
    )

    print(f"\n3. Operation 분석:")
    print(f"   - 타입: {type(operation)}")
    print(f"   - done: {operation.done}")

    # response 속성 확인
    if hasattr(operation, 'response'):
        print(f"\n4. Response 분석:")
        response = operation.response
        print(f"   - 타입: {type(response)}")

        # 모든 속성 나열
        print(f"\n   - 사용 가능한 속성:")
        for attr in dir(response):
            if not attr.startswith('_'):
                try:
                    value = getattr(response, attr)
                    if not callable(value):
                        print(f"     {attr}: {value}")
                except Exception as e:
                    print(f"     {attr}: (접근 불가: {e})")

    # Polling 대기
    if not operation.done:
        print(f"\n5. Polling 시작...")
        for i in range(5):
            await asyncio.sleep(5)
            operation = fs_service.client.operations.get(operation)
            print(f"   [{i+1}/5] done: {operation.done}")

            if operation.done:
                print(f"\n6. 완료된 Operation 분석:")
                response = operation.response
                print(f"   - 타입: {type(response)}")

                # 모든 속성 재확인
                print(f"\n   - 사용 가능한 속성:")
                for attr in dir(response):
                    if not attr.startswith('_'):
                        try:
                            value = getattr(response, attr)
                            if not callable(value):
                                print(f"     {attr}: {value}")
                        except Exception as e:
                            print(f"     {attr}: (접근 불가: {e})")

                break


if __name__ == "__main__":
    asyncio.run(main())
