import asyncio
import logging
from app.db import async_session_maker
from app.services.qna_service import QnAService
from app.models.documents import Document
from sqlalchemy import select

# Configure logging to see errors
logging.basicConfig(level=logging.INFO)

async def main():
    print("Debugging QnA Service...")
    
    async with async_session_maker() as session:
        # Get the latest document
        result = await session.execute(select(Document).order_by(Document.id.desc()))
        document = result.scalars().first()
        
        if not document:
            print("No document found.")
            return

        print(f"Testing with Document ID: {document.id}")
        print(f"Store ID: {document.store_id}")
        
        service = QnAService(session)
        
        try:
            response = await service.ask_question(
                document=document,
                question="What is the secret password?",
                user_id=document.user_id
            )
            print("Success!")
            print(response)
        except Exception as e:
            print("Error occurred:")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
