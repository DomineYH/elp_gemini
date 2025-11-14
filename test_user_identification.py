"""
사용자 식별 로직 테스트
username + nickname 조합으로 사용자 식별
"""
import requests
import sqlite3

BASE_URL = "http://localhost:8001"


def check_users():
    """DB에서 사용자 목록 확인"""
    conn = sqlite3.connect('data/app.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, nickname FROM users WHERE username LIKE 'user%' ORDER BY id")
    users = cursor.fetchall()
    conn.close()

    print(f"\n[사용자 목록] (총 {len(users)}명)")
    for user in users:
        print(f"  - id={user[0]}, username={user[1]}, nickname={user[2]}")

    return users


def test_scenario():
    """사용자 식별 테스트 시나리오"""
    print("=" * 60)
    print("사용자 식별 로직 테스트")
    print("=" * 60)

    session = requests.Session()

    # 시나리오 1: 첫 로그인 (user1 + nick1)
    print("\n[시나리오 1] 첫 로그인: username=user1, nickname=nick1")
    response = session.post(
        f"{BASE_URL}/auth/login",
        data={"username": "user1", "nickname": "nick1"},
        allow_redirects=False
    )
    print(f"  응답: {response.status_code}")
    check_users()

    # 시나리오 2: 동일한 조합으로 재로그인 (user1 + nick1)
    print("\n[시나리오 2] 재로그인: username=user1, nickname=nick1 (동일)")
    session2 = requests.Session()
    response = session2.post(
        f"{BASE_URL}/auth/login",
        data={"username": "user1", "nickname": "nick1"},
        allow_redirects=False
    )
    print(f"  응답: {response.status_code}")
    users = check_users()
    expected = 1
    if len(users) == expected:
        print(f"  ✅ 동일 조합 인식 성공! (사용자 수: {len(users)})")
    else:
        print(f"  ❌ 실패! 새 사용자 생성됨 (예상: {expected}, 실제: {len(users)})")

    # 시나리오 3: 같은 username, 다른 nickname (user1 + nick2)
    print("\n[시나리오 3] 다른 사용자: username=user1, nickname=nick2 (nickname 다름)")
    session3 = requests.Session()
    response = session3.post(
        f"{BASE_URL}/auth/login",
        data={"username": "user1", "nickname": "nick2"},
        allow_redirects=False
    )
    print(f"  응답: {response.status_code}")
    users = check_users()
    expected = 2
    if len(users) == expected:
        print(f"  ✅ 새 사용자 생성 성공! (사용자 수: {len(users)})")
    else:
        print(f"  ❌ 실패! (예상: {expected}, 실제: {len(users)})")

    # 시나리오 4: 다른 username, 같은 nickname (user2 + nick1)
    print("\n[시나리오 4] 다른 사용자: username=user2, nickname=nick1 (username 다름)")
    session4 = requests.Session()
    response = session4.post(
        f"{BASE_URL}/auth/login",
        data={"username": "user2", "nickname": "nick1"},
        allow_redirects=False
    )
    print(f"  응답: {response.status_code}")
    users = check_users()
    expected = 3
    if len(users) == expected:
        print(f"  ✅ 새 사용자 생성 성공! (사용자 수: {len(users)})")
    else:
        print(f"  ❌ 실패! (예상: {expected}, 실제: {len(users)})")

    # 시나리오 5: 기존 조합 재확인 (user1 + nick2)
    print("\n[시나리오 5] 재로그인: username=user1, nickname=nick2 (시나리오 3과 동일)")
    session5 = requests.Session()
    response = session5.post(
        f"{BASE_URL}/auth/login",
        data={"username": "user1", "nickname": "nick2"},
        allow_redirects=False
    )
    print(f"  응답: {response.status_code}")
    users = check_users()
    expected = 3
    if len(users) == expected:
        print(f"  ✅ 기존 사용자 인식 성공! (사용자 수: {len(users)})")
    else:
        print(f"  ❌ 실패! 새 사용자 생성됨 (예상: {expected}, 실제: {len(users)})")

    # 최종 검증
    print("\n" + "=" * 60)
    print("최종 검증")
    print("=" * 60)

    conn = sqlite3.connect('data/app.db')
    cursor = conn.cursor()

    # user1 관련 사용자 확인
    cursor.execute("SELECT id, username, nickname FROM users WHERE username LIKE 'user1%' ORDER BY id")
    user1_accounts = cursor.fetchall()
    print(f"\n[user1 관련 계정] (총 {len(user1_accounts)}개)")
    for user in user1_accounts:
        print(f"  - id={user[0]}, username={user[1]}, nickname={user[2]}")

    conn.close()

    # 최종 결과
    print("\n" + "=" * 60)
    if len(user1_accounts) == 2 and len(users) == 3:
        print("✅ 모든 테스트 통과!")
        print("   - username + nickname 조합으로 사용자 식별 성공")
        print("   - 동일한 조합은 기존 사용자로 인식")
        print("   - 다른 조합은 새 사용자로 생성 (고유 username)")
    else:
        print("❌ 테스트 실패!")
        print(f"   - user1 계정 수: {len(user1_accounts)} (예상: 2)")
        print(f"   - 전체 사용자 수: {len(users)} (예상: 3)")


if __name__ == "__main__":
    # 초기 상태 확인
    print("\n초기 DB 상태:")
    check_users()

    # 테스트 실행
    test_scenario()
