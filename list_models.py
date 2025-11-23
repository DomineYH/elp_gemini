from google import genai
from app.config import settings
import asyncio

async def list_models():
    client = genai.Client(
        api_key=settings.GOOGLE_API_KEY,
        http_options={'api_version': 'v1beta'}
    )
    
    print("Listing models for v1beta:")
    for m in client.models.list():
        print(f"- {m.name}")

if __name__ == "__main__":
    asyncio.run(list_models())
