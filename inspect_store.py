from app.services.file_search_service import FileSearchService
from app.config import settings
import asyncio

async def main():
    service = FileSearchService()
    
    from app.db import async_session_maker
    from app.models.documents import Document
    from sqlalchemy import select
    
    async with async_session_maker() as session:
        result = await session.execute(select(Document).order_by(Document.id.desc()))
        doc = result.scalars().first()
        
        if not doc:
            print("No document found in DB")
            return
            
        print(f"Checking Document ID: {doc.id}")
        print(f"File Search File ID: {doc.file_search_file_id}")
        
        try:
            print("Fetching document from store...")
            doc_info = service.client.file_search_stores.documents.get(name=doc.file_search_file_id)
            print(f"Document Info: {doc_info}")
            print(f"Custom Metadata: {doc_info.custom_metadata}")
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
