import asyncio
from app.services.file_search_service import FileSearchService
from app.config import settings

async def verify_service():
    service = FileSearchService()
    # print(f"Client API Version: {service.client._http_options}")
    
    # Use a dummy store name for testing
    store_name = "fileSearchStores/dummy-store"
    
    print(f"Testing search_in_store with default model...")
    try:
        await service.search_in_store(
            query="Hello",
            store_name=store_name
        )
    except Exception as e:
        print(f"Result: {type(e).__name__}: {e}")
        if "INVALID_ARGUMENT" in str(e) and "tool_type" in str(e):
            print("FAIL: Still getting tool_type error.")
        elif "NOT_FOUND" in str(e) or "PermissionDenied" in str(e) or "404" in str(e):
            print("SUCCESS: Tool type accepted (failed on store lookup as expected).")
        else:
            print("UNCERTAIN: Got a different error.")

if __name__ == "__main__":
    asyncio.run(verify_service())
