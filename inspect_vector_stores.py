"""
벡터 스토어 및 문서 진단 스크립트
현재 존재하는 모든 스토어와 문서를 확인
"""
import asyncio
from google import genai
from app.config import settings

async def main():
    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    
    print("=" * 60)
    print("벡터 스토어 및 문서 목록")
    print("=" * 60)
    
    # 모든 스토어 나열
    print("\n📦 Vector Stores:")
    stores = list(client.file_search_stores.list())
    
    if not stores:
        print("  ⚠️  스토어가 없습니다")
    else:
        for store in stores:
            print(f"\n  Store: {store.display_name}")
            print(f"    ID: {store.name}")
            
            # 각 스토어의 문서 나열
            try:
                doc_count = 0
                print(f"    📄 Documents:")
                for doc in client.file_search_stores.documents.list(parent=store.name):
                    doc_count += 1
                    print(f"      - {doc.name}")
                    # metadata 확인
                    if hasattr(doc, 'custom_metadata') and doc.custom_metadata:
                        print(f"        Metadata: {doc.custom_metadata}")
                
                if doc_count == 0:
                    print(f"      (문서 없음)")
                else:
                    print(f"    총 문서 수: {doc_count}")
                    
            except Exception as e:
                print(f"      ⚠️  문서 목록 가져오기 실패: {str(e)}")
    
    print("\n" + "=" * 60)
    print(f"총 스토어 수: {len(stores)}")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
