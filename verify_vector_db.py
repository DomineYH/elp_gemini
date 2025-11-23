import asyncio
import httpx
import os

BASE_URL = "http://localhost:8000"

async def login(client):
    response = await client.post(
        f"{BASE_URL}/auth/login",
        data={"username": "admin", "nickname": "admin"},
        follow_redirects=True
    )
    return response.status_code == 200

async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        print("1. Logging in...")
        if not await login(client):
            print("Login failed")
            return

        print("\n2. Uploading secret.pdf...")
        if not os.path.exists("secret.pdf"):
            print("secret.pdf not found")
            return

        with open("secret.pdf", "rb") as f:
            files = {"file": ("secret.pdf", f, "application/pdf")}
            data = {"title": "Secret Doc"}
            response = await client.post(
                f"{BASE_URL}/dashboard/upload",
                files=files,
                data=data,
                follow_redirects=False
            )
            print(f"Upload Response: {response.status_code}")

        # Get Document ID (assuming it's the latest one, or we can parse the redirect but we are not following it)
        # We need the ID to ask a question.
        # Let's fetch the dashboard to find the ID or just query the DB directly if we could, 
        # but let's try to get it from the QnA endpoint by listing or just assuming it's the latest.
        # Actually, the previous script checked the DB. Let's do that for simplicity.
        
        from app.db import async_session_maker
        from app.models.documents import Document
        from sqlalchemy import select
        
        doc_id = None
        async with async_session_maker() as session:
             result = await session.execute(select(Document).order_by(Document.id.desc()))
             doc = result.scalars().first()
             if doc:
                 doc_id = doc.id
                 print(f"Document ID: {doc_id}")
        
        if not doc_id:
            print("Could not find document ID")
            return

        print("\n3. Asking Question...")
        response = await client.post(
            f"{BASE_URL}/qna/{doc_id}",
            json={"question": "What is the secret password?"}
        )
        
        if response.status_code == 200:
            data = response.json()
            answer = data.get("answer", "")
            print(f"Answer: {answer}")
            print(f"Metadata: {data.get('grounding_metadata')}")
            
            if "BLUEBERRY" in answer:
                print("VERIFICATION SUCCESS: Secret password found!")
            else:
                print("VERIFICATION FAILED: Secret password NOT found.")
        else:
            print(f"Chatbot failed: {response.status_code}")
            print(response.text)

if __name__ == "__main__":
    asyncio.run(main())
