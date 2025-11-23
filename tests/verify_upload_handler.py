import asyncio
import os
from unittest.mock import MagicMock, patch
from fastapi import UploadFile
from app.routers.views import upload_document
from app.models.users import User

async def verify_upload():
    print("Verifying upload_document handler...")

    # Mock dependencies
    mock_request = MagicMock()
    mock_user = User(username="testuser", email="test@example.com", hashed_password="pw")
    
    # Create a dummy PDF file
    with open("test.pdf", "wb") as f:
        f.write(b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/Resources <<\n/Font <<\n/F1 4 0 R\n>>\n>>\n/MediaBox [0 0 612 792]\n/Contents 5 0 R\n>>\nendobj\n4 0 obj\n<<\n/Type /Font\n/Subtype /Type1\n/BaseFont /Helvetica\n>>\nendobj\n5 0 obj\n<<\n/Length 44\n>>\nstream\nBT\n/F1 24 Tf\n100 100 Td\n(Hello World) Tj\nET\nendstream\nendobj\nxref\n0 6\n0000000000 65535 f\n0000000010 00000 n\n0000000060 00000 n\n0000000117 00000 n\n0000000236 00000 n\n0000000323 00000 n\ntrailer\n<<\n/Size 6\n/Root 1 0 R\n>>\nstartxref\n417\n%%EOF")

    file_obj = open("test.pdf", "rb")
    mock_upload_file = UploadFile(file=file_obj, filename="test.pdf")

    # Mock FileSearchService
    with patch("app.routers.views.FileSearchService") as MockService:
        mock_service_instance = MockService.return_value
        # Make upload_document an async mock
        from unittest.mock import AsyncMock
        mock_service_instance.upload_document = AsyncMock(return_value={
            "document_id": "doc-123",
            "store_id": "store-123"
        })

        # Call the handler
        try:
            response = await upload_document(
                request=mock_request,
                file=mock_upload_file,
                current_user=mock_user
            )
            
            print("Handler executed successfully.")
            print(f"Response status code: {response.status_code}")
            
            # Verify template context
            context = response.context
            print(f"Document ID: {context['document']['id']}")
            print(f"Extracted Text: {context['extracted_text'][:20]}...")
            
            if "Hello World" in context['extracted_text']:
                print("SUCCESS: Text extraction verified.")
            else:
                print("FAILURE: Text extraction failed.")

            if not os.path.exists("data/temp/test.pdf"):
                print("SUCCESS: Temp file deleted.")
            else:
                print("FAILURE: Temp file not deleted.")

        except Exception as e:
            print(f"Handler failed: {e}")
        finally:
            file_obj.close()
            if os.path.exists("test.pdf"):
                os.remove("test.pdf")

if __name__ == "__main__":
    asyncio.run(verify_upload())
