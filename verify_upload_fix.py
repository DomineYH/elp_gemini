"""
평가기준 업로드 및 Store 재생성 테스트
"""
import asyncio
import logging
import tempfile
import os
from app.services.criteria_vector_service import CriteriaVectorService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    print("=" * 60)
    print("평가기준 업로드 테스트 (Store 재생성 포함)")
    print("=" * 60)
    
    service = CriteriaVectorService()
    
    # 1. 현재 상태 확인
    print("\n[1단계] 현재 평가기준 문서 확인")
    try:
        docs_before = await service.list_criteria_documents()
        print(f"   현재 문서 개수: {len(docs_before)}")
        for doc in docs_before:
            print(f"   - {doc['display_name']}")
    except Exception as e:
        print(f"   조회 실패: {e}")
        docs_before = []
    
    # 2. 테스트용 PDF 생성
    print("\n[2단계] 테스트 파일 생성")
    test_content = b"""%%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000052 00000 n
0000000101 00000 n
trailer<</Size 4/Root 1 0 R>>
startxref
165
%%EOF"""
    
    with tempfile.NamedTemporaryFile(
        mode='wb', 
        suffix='.pdf', 
        delete=False
    ) as f:
        f.write(test_content)
        temp_path = f.name
    
    print(f"   테스트 파일 생성: {temp_path}")
    
    # 3. 평가기준 업로드 (Store 재생성 포함)
    print("\n[3단계] 평가기준 업로드")
    try:
        result = await service.upload_criteria(
            file_path=temp_path,
            display_name="test_criteria.pdf",
            metadata={
                "uploaded_by": "test_admin",
                "admin_id": 1,
            }
        )
        print(f"   ✓ 업로드 성공!")
        print(f"   Document ID: {result['document_id']}")
        print(f"   Store ID: {result['store_id']}")
    except Exception as e:
        print(f"   ✗ 업로드 실패: {e}")
        logger.error("업로드 실패", exc_info=True)
    finally:
        # 임시 파일 삭제
        if os.path.exists(temp_path):
            os.remove(temp_path)
            print(f"   임시 파일 삭제: {temp_path}")
    
    # 4. 최종 상태 확인
    print("\n[4단계] 최종 평가기준 문서 확인")
    try:
        docs_after = await service.list_criteria_documents()
        print(f"   현재 문서 개수: {len(docs_after)}")
        for doc in docs_after:
            print(f"   - {doc['display_name']}")
        
        if len(docs_after) == 1:
            print("\n✓ 테스트 성공: 이전 문서가 삭제되고 새 문서만 존재합니다.")
        else:
            print(f"\n⚠ 예상과 다름: {len(docs_after)}개 문서 존재")
    except Exception as e:
        print(f"   조회 실패: {e}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
