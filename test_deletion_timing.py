"""
문서 삭제 후 Store 삭제 시 대기 시간 테스트
"""
import asyncio
import logging
from app.services.file_search_service import FileSearchService
from app.config import settings

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def main():
    service = FileSearchService()
    client = service.client
    store_name = settings.FS_RUBRIC_STORE_NAME
    
    # Store 찾기
    store = None
    for s in client.file_search_stores.list():
        if s.display_name == store_name:
            store = s
            break
    
    if not store:
        print(f"Store {store_name} not found")
        return
    
    print(f"Store found: {store.name}")
    
    # 문서 목록 조회
    print("\n[1] Listing documents...")
    docs = list(client.file_search_stores.documents.list(parent=store.name))
    print(f"Found {len(docs)} documents")
    
    # 문서 삭제
    if docs:
        print("\n[2] Deleting documents...")
        for doc in docs:
            print(f"   Deleting: {doc.name}")
            client.file_search_stores.documents.delete(name=doc.name)
            print(f"   Deleted (call returned)")
        
        # 다양한 대기 시간 테스트
        for wait_time in [0, 1, 3, 5]:
            print(f"\n[3] Waiting {wait_time} seconds...")
            await asyncio.sleep(wait_time)
            
            # 문서가 실제로 삭제되었는지 확인
            print(f"[4] Checking if documents are gone...")
            remaining_docs = list(
                client.file_search_stores.documents.list(parent=store.name)
            )
            print(f"   Remaining documents: {len(remaining_docs)}")
            
            if len(remaining_docs) == 0:
                print(f"\n✓ Documents fully deleted after {wait_time} seconds")
                break
    else:
        print("No documents to delete")

if __name__ == "__main__":
    asyncio.run(main())
