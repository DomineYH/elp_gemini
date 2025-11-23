
import asyncio
import logging
import os
# from dotenv import load_dotenv
from app.services.criteria_vector_service import CriteriaVectorService
from app.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    # load_dotenv()
    
    print(f"Checking store: {settings.FS_RUBRIC_STORE_NAME}")
    
    service = CriteriaVectorService()
    client = service.file_search_service.client
    
    try:
        # Find the store first
        store = None
        for s in client.file_search_stores.list():
            if s.display_name == settings.FS_RUBRIC_STORE_NAME:
                store = s
                break
        
        if not store:
            print(f"Store {settings.FS_RUBRIC_STORE_NAME} not found.")
            return

        print(f"Store found: {store.name}")

        # Try listing documents using the corrected method
        print("Listing documents...")
        # Note: The argument name might be 'parent' or 'file_search_store_name' or just positional?
        # Based on google-genai conventions, it might be 'parent=store.name' or similar.
        # But let's try 'file_search_store_name' as in the original code but on the .documents object.
        
        try:
            documents = client.file_search_stores.documents.list(file_search_store_name=store.name)
            print(f"Found {len(list(documents))} documents (using file_search_store_name).")
        except TypeError:
            print("Failed with file_search_store_name, trying 'parent'...")
            try:
                documents = client.file_search_stores.documents.list(parent=store.name)
                print(f"Found {len(list(documents))} documents (using parent).")
            except TypeError:
                print("Failed with parent, trying positional argument...")
                documents = client.file_search_stores.documents.list(store.name)
                print(f"Found {len(list(documents))} documents (using positional).")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
