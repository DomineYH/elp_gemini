"""
문서 업로드 디버깅 스크립트
실제 upload_document 호출 결과 확인
"""
import asyncio
import os
import sys
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent))

from app.services.file_search_service import FileSearchService
from app.config import settings


async def main():
    """디버깅 메인 함수"""
    print("=" * 60)
    print("File Search 업로드 디버깅")
    print("=" * 60)

    # 환경 변수 확인
    print(f"\n1. 환경 변수 확인:")
    print(f"   GOOGLE_API_KEY: {'설정됨' if settings.GOOGLE_API_KEY else '❌ 없음'}")
    print(f"   FS_MAIN_STORE_NAME: {settings.FS_MAIN_STORE_NAME}")
    print(f"   FS_UPLOAD_TIMEOUT: {settings.FS_UPLOAD_TIMEOUT}초")
    print(f"   FS_POLL_INTERVAL: {settings.FS_POLL_INTERVAL}초")

    if not settings.GOOGLE_API_KEY:
        print("\n❌ GOOGLE_API_KEY가 설정되지 않았습니다!")
        print("   .env 파일에 GOOGLE_API_KEY를 설정하세요.")
        return

    # 테스트 파일 확인
    print(f"\n2. 업로드 디렉토리 확인:")
    upload_dir = Path(settings.UPLOAD_DIR)

    if not upload_dir.exists():
        print(f"   ❌ 업로드 디렉토리가 없습니다: {upload_dir}")
        return

    pdf_files = list(upload_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"   ❌ PDF 파일이 없습니다: {upload_dir}")
        return

    test_file = pdf_files[0]
    print(f"   ✅ 테스트 파일: {test_file.name}")
    print(f"   파일 크기: {test_file.stat().st_size / 1024:.2f} KB")

    # FileSearchService 초기화
    print(f"\n3. FileSearchService 초기화:")
    try:
        fs_service = FileSearchService()
        print(f"   ✅ 초기화 성공")
    except Exception as e:
        print(f"   ❌ 초기화 실패: {e}")
        return

    # 문서 업로드 시도 (저수준 호출로 변경)
    print(f"\n4. 저수준 API 호출 디버깅:")
    print(f"   파일: {test_file}")
    print(f"   표시 이름: 디버그 테스트 문서")

    try:
        # 저수준 API 호출
        from app.config import settings

        store = fs_service._get_or_create_store("main-store")
        print(f"   ✅ 스토어: {store.name}")

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
                    {"key": "user_id", "string_value": "999"},
                    {"key": "random_key", "string_value": "debug_test"}
                ]
            }
        )

        print(f"\n   Operation 타입: {type(operation)}")
        print(f"   Operation 속성: {dir(operation)}")
        print(f"   Operation.done: {operation.done}")

        if hasattr(operation, 'response'):
            print(f"\n   Response 타입: {type(operation.response)}")
            print(f"   Response 속성: {dir(operation.response)}")

            # 모든 속성 출력
            print(f"\n   Response 값:")
            for attr in dir(operation.response):
                if not attr.startswith('_'):
                    try:
                        value = getattr(operation.response, attr)
                        if not callable(value):
                            print(f"     - {attr}: {value}")
                    except:
                        pass

        # 이제 고수준 API 호출
        print(f"\n5. 고수준 API 호출:")
        result = await fs_service.upload_document(
            file_path=str(test_file),
            display_name="디버그 테스트 문서",
            metadata={
                "user_id": "999",
                "random_key": "debug_test",
                "document_id": "999",
            },
            store_type="main"
        )

        print(f"\n5. ✅ 업로드 성공!")
        print(f"   반환값 타입: {type(result)}")
        print(f"   반환값 키: {list(result.keys())}")
        print(f"   반환값 내용:")
        for key, value in result.items():
            print(f"     - {key}: {value}")

        # 핵심 체크
        print(f"\n6. 핵심 체크:")
        if "document_id" in result:
            print(f"   ✅ 'document_id' 키 존재: {result['document_id']}")
        else:
            print(f"   ❌ 'document_id' 키 없음!")

        if "file_id" in result:
            print(f"   ⚠️ 'file_id' 키 존재 (구버전): {result['file_id']}")

        if "store_id" in result:
            print(f"   ✅ 'store_id' 키 존재: {result['store_id']}")
        else:
            print(f"   ❌ 'store_id' 키 없음!")

    except TimeoutError as e:
        print(f"\n❌ 타임아웃 발생:")
        print(f"   {e}")
        print(f"\n   해결 방법:")
        print(f"   1. 파일 크기 확인 (50MB 이하)")
        print(f"   2. 네트워크 연결 확인")
        print(f"   3. Google API 할당량 확인")

    except Exception as e:
        print(f"\n❌ 업로드 실패:")
        print(f"   에러 타입: {type(e).__name__}")
        print(f"   에러 메시지: {e}")

        import traceback
        print(f"\n   전체 스택 트레이스:")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
