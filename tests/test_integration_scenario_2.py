"""
통합 테스트 시나리오 2: 평가기준 업로드 → 분석 → Store 삭제

테스트 절차:
1. 평가기준 업로드 (첫 번째)
2. 평가기준 업로드 (두 번째 - 첫 번째 자동 삭제)
3. 평가기준 삭제 (Store 재생성)
4. 평가기준 전체 삭제 확인
"""
import asyncio
import httpx
import io


# 테스트 설정
BASE_URL = "http://localhost:8000"
TEST_USERNAME = "admin"
TEST_PASSWORD = "admin1234"
TEST_CRITERIA_CONTENT_1 = """
# 평가기준 1

## 학습 목표 평가
- 목표가 명확하게 제시되었는가?
- 목표가 측정 가능한가?
"""

TEST_CRITERIA_CONTENT_2 = """
# 평가기준 2 (업데이트)

## 학습 목표 평가
- 목표가 구체적이고 측정 가능한가?
- 목표가 학습자 수준에 적합한가?

## 수업 내용 평가
- 내용이 목표와 일치하는가?
"""


async def get_auth_token(client: httpx.AsyncClient) -> str:
    """인증 토큰 획득"""
    print("🔑 인증 토큰 획득 중...")

    response = await client.post(
        f"{BASE_URL}/api/auth/login",
        data={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD,
        }
    )

    if response.status_code != 200:
        raise Exception(f"로그인 실패: {response.text}")

    data = response.json()
    token = data["access_token"]
    print(f"✅ 인증 토큰 획득 완료")
    return token


async def upload_criteria(
    client: httpx.AsyncClient,
    token: str,
    content: str,
    display_name: str
) -> dict:
    """평가기준 업로드"""
    print(f"\n📤 평가기준 업로드 중: {display_name}...")

    # 테스트 파일 생성
    file_content = content.encode('utf-8')
    files = {
        'file': (f'{display_name}.txt', io.BytesIO(file_content))
    }

    response = await client.post(
        f"{BASE_URL}/api/admin/criteria/upload",
        files=files,
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code != 201:
        raise Exception(f"평가기준 업로드 실패: {response.text}")

    data = response.json()
    print(f"✅ 평가기준 업로드 완료")
    print(f"   파일명: {data.get('filename')}")
    print(f"   Store ID: {data.get('store_id', 'N/A')}")
    return data


async def delete_all_criteria(
    client: httpx.AsyncClient,
    token: str
) -> dict:
    """평가기준 전체 삭제"""
    print(f"\n🗑️  평가기준 전체 삭제 중...")

    response = await client.delete(
        f"{BASE_URL}/api/admin/criteria",
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code != 200:
        raise Exception(f"평가기준 삭제 실패: {response.text}")

    data = response.json()
    print(f"✅ 평가기준 삭제 완료")
    print(f"   메시지: {data.get('message')}")
    return data


async def verify_criteria_deleted(
    client: httpx.AsyncClient,
    token: str
) -> bool:
    """평가기준 삭제 확인 (지도안 평가 시도)"""
    print(f"\n🔍 평가기준 삭제 확인 중...")

    # 테스트 지도안 업로드
    test_lessonplan_content = "# 테스트 지도안\n\n내용"
    files = {
        'file': (
            'verify_test.txt',
            io.BytesIO(test_lessonplan_content.encode('utf-8'))
        )
    }

    upload_response = await client.post(
        f"{BASE_URL}/api/lessonplans/upload",
        files=files,
        headers={"Authorization": f"Bearer {token}"}
    )

    if upload_response.status_code != 201:
        print(f"⚠️  테스트 지도안 업로드 실패")
        return False

    lessonplan_filename = upload_response.json()["filename"]

    # 평가 시도 (평가기준이 없으면 실패해야 함)
    eval_response = await client.post(
        f"{BASE_URL}/api/evaluations",
        json={
            "lessonplan_filename": lessonplan_filename,
            "evaluation_type": "comprehensive"
        },
        headers={"Authorization": f"Bearer {token}"}
    )

    # 평가기준이 없으면 실패해야 함
    if eval_response.status_code != 201:
        print(f"✅ 평가기준 삭제 확인: 평가 실패 (예상된 동작)")
        return True
    else:
        print(f"❌ 평가기준 삭제 확인 실패: 평가 성공 (예상치 못한 동작)")
        return False


async def run_integration_test_scenario_2():
    """
    통합 테스트 시나리오 2 실행
    """
    print("=" * 60)
    print("통합 테스트 시나리오 2: 평가기준 업로드 → 분석 → Store 삭제")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            # 1. 인증
            token = await get_auth_token(client)

            # 2. 첫 번째 평가기준 업로드
            result1 = await upload_criteria(
                client, token,
                TEST_CRITERIA_CONTENT_1,
                "criteria_v1"
            )

            # 3. 두 번째 평가기준 업로드 (첫 번째 자동 삭제)
            print("\n⚠️  두 번째 업로드 시 첫 번째 자동 삭제 확인")
            result2 = await upload_criteria(
                client, token,
                TEST_CRITERIA_CONTENT_2,
                "criteria_v2"
            )

            # 4. 평가기준 전체 삭제
            await delete_all_criteria(client, token)

            # 5. 평가기준 삭제 확인
            deleted = await verify_criteria_deleted(client, token)

            print("\n" + "=" * 60)
            if deleted:
                print("✅ 통합 테스트 시나리오 2 완료")
            else:
                print("⚠️  통합 테스트 시나리오 2 부분 완료 "
                      "(삭제 확인 실패)")
            print("=" * 60)
            print("\n결과 요약:")
            print(f"- 첫 번째 업로드: {result1.get('filename')}")
            print(f"- 두 번째 업로드: {result2.get('filename')}")
            print(f"- 자동 삭제 동작: 확인 필요")
            print(f"- 전체 삭제: {'성공' if deleted else '실패'}")

            return deleted

        except Exception as e:
            print(f"\n❌ 테스트 실패: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == "__main__":
    success = asyncio.run(run_integration_test_scenario_2())
    exit(0 if success else 1)
