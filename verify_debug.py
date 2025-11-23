from google import genai
from google.genai import types
from app.config import settings
import asyncio

async def verify():
    client = genai.Client(
        api_key=settings.GOOGLE_API_KEY,
        http_options={'api_version': 'v1beta'}
    )
    
    print("--- Test 1: Google Search Tool (Grounding) ---")
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents="What is the capital of France?",
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        google_search=types.GoogleSearch()
                    )
                ]
            )
        )
        print("Test 1 Success:", response.text[:50])
    except Exception as e:
        print(f"Test 1 Failed: {e}")

    print("\n--- Test 2: File Search with Gemini 1.5 Flash ---")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Hello",
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        file_search=types.FileSearch(
                            file_search_store_names=["fileSearchStores/dummy-store"]
                        )
                    )
                ]
            )
        )
        print("Test 2 Success (unexpected):", response.text[:50])
    except Exception as e:
        print(f"Test 2 Failed: {e}")

if __name__ == "__main__":
    asyncio.run(verify())
