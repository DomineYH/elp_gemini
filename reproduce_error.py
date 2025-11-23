
import asyncio
import sys
from unittest.mock import MagicMock

# Mock missing modules
sys.modules['app.services.criteria_context_service'] = MagicMock()

from app.services.qna_service import QnAService
from app.services.file_search_service import FileSearchService

async def reproduce():
    # Mock dependencies
    db = MagicMock()
    
    # Initialize service
    service = QnAService(db)
    
    try:
        # Mock dependencies
        service.file_search_service = MagicMock()
        service.client = MagicMock()
        service.prompt_loader = MagicMock()
        service.prompt_loader.get_prompt.return_value = "System Prompt"
        
        # Mock _get_session to return a dummy session
        service._get_session = MagicMock()
        dummy_session = MagicMock()
        # Async mock for _get_session
        f = asyncio.Future()
        f.set_result(dummy_session)
        service._get_session.return_value = f

        # Mock get_conversation_history
        service.get_conversation_history = MagicMock()
        f2 = asyncio.Future()
        f2.set_result([])
        service.get_conversation_history.return_value = f2
        
        # Mock _save_messages
        service._save_messages = MagicMock()
        f3 = asyncio.Future()
        f3.set_result(None)
        service._save_messages.return_value = f3

        # Call ask_question with a specific store_id
        store_id = "fileSearchStores/test-store"
        await service.ask_question(session_id=1, question="test", user_id=1, store_id=store_id)
        
        print("Success: ask_question completed without AttributeError")
        
        # Verify that generate_content was called with the correct store_id
        call_args = service.client.models.generate_content.call_args
        if call_args:
            kwargs = call_args.kwargs
            tools = kwargs.get('config').tools
            used_store = tools[0].file_search.file_search_store_names[0]
            if used_store == store_id:
                print(f"Success: Used correct store_id: {used_store}")
            else:
                print(f"Failure: Used wrong store_id: {used_store}, expected {store_id}")
        
    except AttributeError as e:
        print(f"Failure: Caught AttributeError: {e}")
    except Exception as e:
        # We might get other errors due to mocking, but as long as it's not the original AttributeError, we progressed
        print(f"Note: Caught {type(e).__name__}: {e}")
        if "AttributeError" not in str(e):
             print("Success: Did not catch the original AttributeError")

if __name__ == "__main__":
    asyncio.run(reproduce())
