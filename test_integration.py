"""
통합 테스트: 로그인 후 문서 동기화 확인
"""
import requests
import sqlite3
from pathlib import Path
import time

BASE_URL = "http://localhost:8001"
TEST_PDF_PATH = "docs/test.pdf"  # 테스트용 PDF 경로


def create_test_pdf():
    """간단한 테스트 PDF 생성"""
    # PDF 헤더만 있는 최소 PDF 파일
    pdf_content = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
/Resources <<
/Font <<
/F1 5 0 R
>>
>>
>>
endobj
4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
(Test Document) Tj
ET
endstream
endobj
5 0 obj
<<
/Type /Font
/Subtype /Type1
/BaseFont /Helvetica
>>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000270 00000 n
0000000363 00000 n
trailer
<<
/Size 6
/Root 1 0 R
>>
startxref
441
%%EOF
"""
    Path(TEST_PDF_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(TEST_PDF_PATH, "wb") as f:
        f.write(pdf_content)
    print(f"✅ 테스트 PDF 생성: {TEST_PDF_PATH}")


def check_db_state(description):
    """DB 상태 확인"""
    print(f"\n{'='*60}")
    print(f"DB 상태 확인: {description}")
    print('='*60)

    conn = sqlite3.connect('data/app.db')
    cursor = conn.cursor()

    # 사용자 목록
    cursor.execute("SELECT id, username, nickname FROM users WHERE username LIKE 'test_user%'")
    users = cursor.fetchall()
    print(f"\n[사용자 목록]")
    for user in users:
        print(f"  - id={user[0]}, username={user[1]}, nickname={user[2]}")

    # 문서 목록
    cursor.execute("""
        SELECT d.id, d.user_id, d.title, d.status, u.username
        FROM documents d
        JOIN users u ON d.user_id = u.id
        WHERE u.username LIKE 'test_user%'
    """)
    docs = cursor.fetchall()
    print(f"\n[문서 목록]")
    for doc in docs:
        print(f"  - doc_id={doc[0]}, user_id={doc[1]}, title={doc[2]}, status={doc[3]}, username={doc[4]}")

    conn.close()

    return users, docs


def test_scenario_1():
    """시나리오 1: 첫 로그인 및 문서 업로드"""
    print("\n" + "="*60)
    print("시나리오 1: 첫 로그인 및 문서 업로드")
    print("="*60)

    session = requests.Session()

    # 1. 로그인
    print("\n[1] 로그인 시도...")
    login_data = {
        "username": "test_user",
        "nickname": "테스트 사용자"
    }
    response = session.post(f"{BASE_URL}/auth/login", data=login_data, allow_redirects=False)
    print(f"  - 응답 코드: {response.status_code}")
    print(f"  - 리다이렉트: {response.headers.get('Location', 'N/A')}")

    if response.status_code != 302:
        print(f"❌ 로그인 실패!")
        return None

    print(f"✅ 로그인 성공!")

    # 2. 대시보드 접근
    print("\n[2] 대시보드 접근...")
    response = session.get(f"{BASE_URL}/")
    print(f"  - 응답 코드: {response.status_code}")

    if response.status_code == 200:
        print(f"✅ 대시보드 접근 성공!")
    else:
        print(f"❌ 대시보드 접근 실패!")
        return None

    # 3. 문서 업로드
    print("\n[3] 문서 업로드...")
    with open(TEST_PDF_PATH, "rb") as f:
        files = {"file": ("test.pdf", f, "application/pdf")}
        data = {"title": "테스트 문서 1"}
        response = session.post(f"{BASE_URL}/docs/upload", data=data, files=files, allow_redirects=False)

    print(f"  - 응답 코드: {response.status_code}")
    print(f"  - 리다이렉트: {response.headers.get('Location', 'N/A')}")

    if response.status_code != 302:
        print(f"❌ 문서 업로드 실패!")
        return session

    print(f"✅ 문서 업로드 성공!")

    # 4. 업로드 완료 대기
    print("\n[4] 문서 인덱싱 대기 (30초)...")
    time.sleep(30)

    # DB 상태 확인
    users, docs = check_db_state("시나리오 1 완료 후")

    return session


def test_scenario_2():
    """시나리오 2: 재로그인 후 문서 확인 (핵심 테스트)"""
    print("\n" + "="*60)
    print("시나리오 2: 재로그인 후 문서 확인 (핵심 테스트)")
    print("="*60)

    session = requests.Session()

    # 1. 다른 nickname으로 재로그인
    print("\n[1] 재로그인 (동일 username, 다른 nickname)...")
    login_data = {
        "username": "test_user",  # 동일
        "nickname": "변경된 닉네임"  # 다름!
    }
    response = session.post(f"{BASE_URL}/auth/login", data=login_data, allow_redirects=False)
    print(f"  - 응답 코드: {response.status_code}")

    if response.status_code != 302:
        print(f"❌ 재로그인 실패!")
        return False

    print(f"✅ 재로그인 성공!")

    # 2. 문서 목록 조회
    print("\n[2] 문서 목록 조회...")
    response = session.get(f"{BASE_URL}/docs")
    print(f"  - 응답 코드: {response.status_code}")

    if response.status_code == 200:
        docs = response.json()
        print(f"  - 문서 개수: {len(docs)}")
        for doc in docs:
            print(f"    • {doc['title']} (status: {doc['status']})")

        # DB 상태 확인
        users, db_docs = check_db_state("시나리오 2 완료 후")

        # 검증
        print("\n" + "="*60)
        print("검증 결과")
        print("="*60)

        # 1. 사용자 수 확인
        if len(users) == 1:
            print("✅ 사용자 중복 생성 없음 (1개)")
        else:
            print(f"❌ 사용자 중복 생성 발생! ({len(users)}개)")
            return False

        # 2. nickname 업데이트 확인
        if users[0][2] == "변경된 닉네임":
            print("✅ Nickname 업데이트 성공")
        else:
            print(f"❌ Nickname 업데이트 실패 (현재: {users[0][2]})")

        # 3. 문서 개수 확인
        if len(docs) >= 1:
            print(f"✅ 이전 문서 유지됨 ({len(docs)}개)")
            return True
        else:
            print(f"❌ 이전 문서가 사라짐!")
            return False
    else:
        print(f"❌ 문서 목록 조회 실패!")
        return False


def main():
    """메인 테스트 실행"""
    print("\n" + "="*60)
    print("문서 동기화 통합 테스트 시작")
    print("="*60)

    try:
        # 테스트 PDF 생성
        create_test_pdf()

        # 초기 DB 상태
        check_db_state("테스트 시작 전")

        # 시나리오 1 실행
        session = test_scenario_1()
        if not session:
            print("\n❌ 시나리오 1 실패! 테스트 중단.")
            return

        # 시나리오 2 실행
        success = test_scenario_2()

        # 최종 결과
        print("\n" + "="*60)
        print("최종 테스트 결과")
        print("="*60)

        if success:
            print("✅ 모든 테스트 통과!")
            print("   - 로그인 시 중복 사용자 생성 없음")
            print("   - Nickname 변경 시에도 기존 문서 유지")
            print("   - 문서 동기화 정상 작동")
        else:
            print("❌ 테스트 실패!")

    except Exception as e:
        print(f"\n❌ 테스트 중 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
