import requests
import json
import sys
import os

BASE_URL = "http://localhost:8000"
SAMPLE_PDF = "/mnt/d/dev/elp_gemini/data/uploads/criteria/1763639522319_test_criteria.pdf"

def test_qna_verification():
    print("\n" + "="*70)
    print("QnA Verification with Criteria")
    print("="*70)

    session = requests.Session()

    # 1. Login
    print("\n[1] Logging in...")
    login_data = {
        "username": "qna_test_user",
        "nickname": "QnA 테스트"
    }
    response = session.post(f"{BASE_URL}/auth/login", data=login_data, allow_redirects=False)

    if response.status_code != 302:
        print(f"❌ Login failed! Status: {response.status_code}")
        print(f"Response: {response.text}")
        return False

    print(f"✅ Login successful")

    # 2. Upload Document
    print("\n[2] Uploading document...")
    if not os.path.exists(SAMPLE_PDF):
        print(f"❌ Sample PDF not found at {SAMPLE_PDF}")
        return False

    with open(SAMPLE_PDF, 'rb') as f:
        files = {'file': ('test_doc.pdf', f, 'application/pdf')}
        data = {'title': 'Test Document for QnA'}
        response = session.post(f"{BASE_URL}/dashboard/upload", files=files, data=data, allow_redirects=False)
    
    if response.status_code != 302:
        print(f"❌ Upload failed! Status: {response.status_code}")
        print(f"Response: {response.text}")
        return False
    
    print("✅ Upload successful (redirected)")

    # 3. Get Document ID
    print("\n[3] Getting Document ID...")
    response = session.get(f"{BASE_URL}/dashboard/list")
    if response.status_code != 200:
        print(f"❌ Failed to list documents! Status: {response.status_code}")
        return False
    
    documents = response.json()
    if not documents:
        print("❌ No documents found after upload!")
        return False
    
    # Get the most recent document
    document = documents[0]
    document_id = document['id']
    print(f"✅ Found document ID: {document_id} (Status: {document['status']})")

    if document['status'] != 'ready':
        print("⚠️ Document is not ready yet. Waiting might be required, but proceeding for now.")

    # 4. Ask a question
    print(f"\n[4] Asking question to document {document_id}...")
    qna_data = {
        "question": "이 문서의 핵심 내용은 무엇인가요? 그리고 평가 기준에 따르면 어떤 점이 중요한가요?"
    }

    response = session.post(
        f"{BASE_URL}/qna/{document_id}",
        json=qna_data
    )

    print(f"  - Status Code: {response.status_code}")

    if response.status_code != 200:
        print(f"❌ QnA API failed!")
        try:
            print(f"  Error: {response.json()}")
        except:
            print(f"  Response: {response.text[:500]}")
        return False

    result = response.json()

    # 5. Analyze Response
    print(f"\n[5] Analyzing Response...")
    answer = result.get('answer', '')
    print(f"  - Answer: {answer}")
    
    print(f"\n[6] Verification Result")
    if answer:
        print("✅ Answer received.")
        return True
    else:
        print("❌ No answer received.")
        return False

if __name__ == "__main__":
    success = test_qna_verification()
    sys.exit(0 if success else 1)
