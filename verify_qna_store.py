import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
from app.services.qna_service import QnAService

class TestQnAStoreSelection(unittest.TestCase):
    @patch('app.services.qna_service.genai')
    @patch('app.services.qna_service.FileSearchService')
    @patch('app.services.qna_service.PromptLoaderService')
    def test_store_selection(self, MockPromptLoader, MockFileSearchService, MockGenai):
        # Setup mocks
        mock_db = AsyncMock()
        service = QnAService(mock_db)
        
        # Mock FileSearchService instance
        mock_fs_instance = MockFileSearchService.return_value
        mock_fs_instance.main_store_name = "main-store"
        
        # Mock _get_or_create_store to return a mock store with a name
        def side_effect(store_name):
            mock_store = MagicMock()
            mock_store.name = f"id-for-{store_name}"
            return mock_store
        mock_fs_instance._get_or_create_store.side_effect = side_effect

        # Mock other dependencies to avoid errors
        service.prompt_loader.get_prompt.return_value = "System Prompt"
        service.get_conversation_history = AsyncMock(return_value=[])
        service._get_session = AsyncMock(return_value=MagicMock())
        service._save_messages = AsyncMock()
        
        # Mock client response
        mock_response = MagicMock()
        mock_response.text = "Answer"
        mock_response.candidates = []
        service.client.models.generate_content.return_value = mock_response

        # Run the async method
        async def run_test():
            # Test case: No store_id provided, should use user store
            user_id = 123
            await service.ask_question(
                session_id=1,
                question="Test",
                user_id=user_id,
                store_id=None
            )
            
            # Verify that _get_or_create_store was called with user store name
            # It might be called multiple times (init, etc), but we check if it was called with user store
            mock_fs_instance._get_or_create_store.assert_any_call(f"user-{user_id}-store")
            print("SUCCESS: User store was requested.")

        asyncio.run(run_test())

if __name__ == '__main__':
    unittest.main()
