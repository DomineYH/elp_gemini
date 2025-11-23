"""
수정된 list_criteria_documents 메서드 검증 스크립트
"""
import asyncio
import logging
from app.services.criteria_vector_service import CriteriaVectorService
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    print(f"평가기준 Store 확인: {settings.FS_RUBRIC_STORE_NAME}")
    print("=" * 60)
    
    service = CriteriaVectorService()
    
    try:
        # 수정된 메서드 호출
        documents = await service.list_criteria_documents()
        
        print(f"\n✓ 조회 성공: {len(documents)}개 문서 발견")
        print("-" * 60)
        
        for i, doc in enumerate(documents, 1):
            print(f"{i}. Document ID: {doc['document_id']}")
            print(f"   Display Name: {doc['display_name']}")
            print()
        
        if documents:
            print("✓ 수정 완료: 웹에서 평가기준이 정상적으로 표시될 것입니다.")
        else:
            print("⚠ Store는 존재하지만 문서가 없습니다. 평가기준을 업로드해야 합니다.")
            
    except Exception as e:
        print(f"✗ 오류 발생: {e}")
        logger.error(f"검증 실패: {str(e)}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
