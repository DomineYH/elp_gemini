"""
벡터 스토어 삭제 테스트
1. 문서 업로드
2. 스토어 확인
3. cleanup 엔드포인트 호출
4. 삭제 확인
"""
import asyncio
import httpx
import os
from google import genai
from app.config import settings

async def list_stores_and_docs(client):
    """모든 스토어와 문서 나열"""
    print("\n" + "=" * 60)
    stores = list(client.file_search_stores.list())
    print(f"📦 Vector Stores ({len(stores)} total):")
    
    total_docs = 0
    for store in stores:
        print(f"\n  Store: {store.display_name}")
        print(f"    ID: {store.name}")
        
        try:
            doc_count = 0
            docs = list(client.file_search_stores.documents.list(parent=store.name))
            for doc in docs:
                doc_count += 1
                total_docs += 1
                print(f"    📄 Document {doc_count}: {doc.name}")
                if hasattr(doc, 'custom_metadata') and doc.custom_metadata:
                    print(f"       Metadata: {doc.custom_metadata}")
            
            if doc_count == 0:
                print(f"    (문서 없음)")
                
        except Exception as e:
            print(f"    ⚠️  문서 목록 가져오기 실패: {str(e)}")
    
    print("=" * 60)
    return total_docs

async def main():
    print("🧪 벡터 스토어 삭제 테스트")
    
    # Google API 클라이언트
    google_client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    
    # 1. 초기 상태 확인
    print("\n1️⃣  초기 상태:")
    initial_docs = await list_stores_and_docs(google_client)
    print(f"초기 문서 수: {initial_docs}")
    
    # 2. 로그인 및 문서 업로드
    async with httpx.AsyncClient(timeout=60.0) as client:
        print("\n2️⃣  로그인 중...")
        response = await client.post(
            "http://localhost:8000/auth/login",
            data={"username": "testuser", "nickname": "testuser"},
            follow_redirects=True
        )
        
        if response.status_code != 200:
            print("❌ 로그인 실패")
            return
        print("✅ 로그인 성공")
        
        # 3. 문서 업로드
        print("\n3️⃣  문서 업로드 중...")
        if not os.path.exists("secret.pdf"):
            print("❌ secret.pdf 파일이 없습니다")
            return
        
        with open("secret.pdf", "rb") as f:
            files = {"file": ("secret.pdf", f, "application/pdf")}
            data = {"title": "Test Document"}
            response = await client.post(
                "http://localhost:8000/dashboard/upload",
                files=files,
                data=data,
                follow_redirects=False
            )
            print(f"업로드 응답: {response.status_code}")
        
        # 업로드 후 인덱싱 대기
        print("⏳ 인덱싱 대기 중 (10초)...")
        await asyncio.sleep(10)
        
        # 4. 업로드 후 상태 확인
        print("\n4️⃣  업로드 후 상태:")
        after_upload_docs = await list_stores_and_docs(google_client)
        print(f"업로드 후 문서 수: {after_upload_docs}")
        
        if after_upload_docs == initial_docs:
            print("⚠️  업로드 후에도 문서 수가 변하지 않았습니다!")
        else:
            print(f"✅ 문서가 {after_upload_docs - initial_docs}개 추가되었습니다")
        
        # 5. cleanup 엔드포인트 호출
        print("\n5️⃣  Cleanup 엔드포인트 호출 중...")
        response = await client.post("http://localhost:8000/dashboard/cleanup")
        print(f"Cleanup 응답: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"Cleanup 결과: {result}")
        else:
            print(f"❌ Cleanup 실패: {response.text}")
        
        # 정리 후 대기
        print("⏳ 정리 대기 중 (5초)...")
        await asyncio.sleep(5)
        
        # 6. 삭제 후 상태 확인
        print("\n6️⃣  삭제 후 상태:")
        after_cleanup_docs = await list_stores_and_docs(google_client)
        print(f"삭제 후 문서 수: {after_cleanup_docs}")
        
        # 결과 분석
        print("\n" + "=" * 60)
        print("📊 테스트 결과:")
        print(f"  초기 문서 수: {initial_docs}")
        print(f"  업로드 후: {after_upload_docs} (증가: {after_upload_docs - initial_docs})")
        print(f"  삭제 후: {after_cleanup_docs} (감소: {after_upload_docs - after_cleanup_docs})")
        
        if after_upload_docs > initial_docs and after_cleanup_docs == initial_docs:
            print("\n✅ 테스트 성공: 문서가 정상적으로 업로드되고 삭제되었습니다!")
        elif after_upload_docs > initial_docs and after_cleanup_docs == after_upload_docs:
            print("\n❌ 테스트 실패: 문서가 업로드되었지만 삭제되지 않았습니다!")
        elif after_upload_docs == initial_docs:
            print("\n❌ 테스트 실패: 문서가 업로드되지 않았습니다!")
        else:
            print(f"\n⚠️  예상치 못한 결과")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
