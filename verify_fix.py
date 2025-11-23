from google import genai
from google.genai import types
from app.config import settings
import asyncio

async def verify():
    print("Initializing client with v1beta...")
    client = genai.Client(
        api_key=settings.GOOGLE_API_KEY,
        http_options={'api_version': 'v1beta'}
    )
    
    print("Sending request with file_search tool...")
    try:
        # We use a dummy store name. If the tool definition is valid, 
        # we expect a "store not found" error or similar, NOT "INVALID_ARGUMENT" about tool_type.
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
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
        print("Response received (unexpected success):", response.text)
    except Exception as e:
        print(f"Caught exception: {type(e).__name__}: {e}")
        if "INVALID_ARGUMENT" in str(e) and "tool_type" in str(e):
            print("FAIL: Still getting tool_type error.")
        elif "NOT_FOUND" in str(e) or "PermissionDenied" in str(e) or "404" in str(e):
            print("SUCCESS: Tool type accepted (failed on store lookup as expected).")
        else:
            print("UNCERTAIN: Got a different error, but likely passed tool validation.")

if __name__ == "__main__":
    asyncio.run(verify())
