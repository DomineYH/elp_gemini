
import asyncio
import logging
from app.services.file_search_service import FileSearchService

async def main():
    service = FileSearchService()
    client = service.client
    
    print("Methods of client.file_search_stores.documents:")
    print(dir(client.file_search_stores.documents))

if __name__ == "__main__":
    asyncio.run(main())
