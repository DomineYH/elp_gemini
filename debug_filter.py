import asyncio
import logging
from app.db import async_session_maker
from app.services.qna_service import QnAService
from app.models.documents import Document
from sqlalchemy import select
from google.genai import types

logging.basicConfig(level=logging.INFO)

async def main():
    print("Debugging Filter Syntax...")
    
    async with async_session_maker() as session:
        result = await session.execute(select(Document).order_by(Document.id.desc()))
        document = result.scalars().first()
        
        if not document:
            print("No document found.")
            return

        print(f"Testing with Document ID: {document.id}, User ID: {document.user_id}")
        
        service = QnAService(session)
        
        filters_to_test = [
            f"metadata.user_id = '{document.user_id}'",
            f"metadata.user_id == '{document.user_id}'",
            f"metadata.key('user_id') == '{document.user_id}'",
            f"user_id = '{document.user_id}'",
            f"metadata.document_id = '{document.id}'"
        ]
        
        for filter_str in filters_to_test:
            print(f"\nTesting filter: {filter_str}")
            try:
                # We need to manually construct the request to override the filter
                # But QnAService.ask_question hardcodes it.
                # So we will instantiate the client and call generate_content directly here.
                
                # Reconstruct context (simplified)
                context = "Context"
                question = "What is the secret password?"
                
                response = service.client.models.generate_content(
                    model=service.qna_model_name,
                    contents=f"{context}\n\n질문: {question}",
                    config=types.GenerateContentConfig(
                        tools=[
                            types.Tool(
                                file_search=types.FileSearch(
                                    file_search_store_names=[document.store_id],
                                    metadata_filter=filter_str
                                )
                            )
                        ],
                        temperature=0.1
                    )
                )
                
                print(f"Response: {response.text}")
                print(f"Metadata: {response.candidates[0].grounding_metadata}")
                
            except Exception as e:
                print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
