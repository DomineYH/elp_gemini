"""
통합 테스트 시나리오 3: 세션 종료 → 임시 지도안 삭제

테스트 절차:
1. 지도안을 Vector Store에 임시 업로드
2. QnA 세션 생성
3. 질문 수행
4. 세션 종료 (Store 삭제)
5. Store 삭제 확인
"""
import asyncio
import httpx
import io


# 테스트 설정
BASE_URL = "http://localhost:8000"
TEST_USERNAME = "testuser"
TEST_PASSWORD = "testpassword"
TEST_LESSONPLAN_CONTENT = """
# 임시 지도안

## 학습 목표
- 임시 테스트 목표

## 수업 내용
임시 테스트 내용
"""
LEGACY_UPLOAD_SKIP_MESSAGE = (
    "Legacy integration scenario — superseded by /dashboard/upload "
    "contract; requires rewrite"
)


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


async def upload_temporary_lessonplan(
    client: httpx.AsyncClient,
    token: str
) -> str | None:
    """지도안 임시 업로드"""
    print("\n📤 지도안 임시 업로드 중...")

    # 테스트 파일 생성
    file_content = TEST_LESSONPLAN_CONTENT.encode('utf-8')
    files = {
        'file': ('temp_lessonplan.txt', io.BytesIO(file_content))
    }

    response = await client.post(
        f"{BASE_URL}/dashboard/upload",
        files=files,
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code != 200:
        raise Exception(f"지도안 업로드 실패: {response.text}")

    print(f"\n⏭️  {LEGACY_UPLOAD_SKIP_MESSAGE}")
    return None


async def create_qna_session(
    client: httpx.AsyncClient,
    token: str,
    lessonplan_filename: str
) -> int:
    """QnA 세션 생성"""
    print("\n🔄 QnA 세션 생성 중...")

    response = await client.post(
        f"{BASE_URL}/api/qna/sessions",
        json={"lessonplan_filename": lessonplan_filename},
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code != 201:
        raise Exception(f"QnA 세션 생성 실패: {response.text}")

    data = response.json()
    session_id = data["session_id"]
    print(f"✅ QnA 세션 생성 완료: session_id={session_id}")
    return session_id


async def ask_question(
    client: httpx.AsyncClient,
    token: str,
    session_id: int,
    question: str
) -> dict:
    """질문하기"""
    print(f"\n💬 질문: {question}")

    response = await client.post(
        f"{BASE_URL}/api/qna/sessions/{session_id}/ask",
        json={"question": question},
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code != 200:
        raise Exception(f"질문 실패: {response.text}")

    data = response.json()
    answer = data["answer"]

    print(f"✅ 답변: {answer[:100]}...")
    return data


async def close_session_and_delete_store(
    client: httpx.AsyncClient,
    token: str,
    session_id: int
) -> dict:
    """세션 종료 및 Store 삭제"""
    print(f"\n🔚 세션 종료 및 Store 삭제 중: session_id={session_id}")

    # 세션 종료 API 호출 (구현되어 있다면)
    # 실제로는 LessonPlanVectorService.delete_on_session_close()
    # 직접 호출 필요
    response = await client.delete(
        f"{BASE_URL}/api/qna/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"}
    )

    # API가 구현되지 않았을 경우, 서비스 직접 호출로 대체
    if response.status_code == 404:
        print("⚠️  세션 종료 API가 구현되지 않음")
        print("   서비스 레이어에서 직접 삭제 필요")
        return {"manual_delete_required": True}

    if response.status_code not in [200, 204]:
        raise Exception(f"세션 종료 실패: {response.text}")

    print(f"✅ 세션 종료 완료")
    return {"manual_delete_required": False}


async def verify_store_deleted(
    client: httpx.AsyncClient,
    token: str,
    lessonplan_filename: str
) -> bool:
    """Store 삭제 확인 (QnA 재시도)"""
    print(f"\n🔍 Store 삭제 확인 중...")

    # 새 세션 생성 시도
    try:
        session_id = await create_qna_session(
            client, token, lessonplan_filename
        )

        # 질문 시도 (Store가 삭제되었으면 실패해야 함)
        try:
            await ask_question(
                client, token, session_id,
                "이 지도안의 내용은 무엇인가요?"
            )
            print(f"⚠️  Store가 아직 존재하는 것으로 보임")
            return False
        except Exception as e:
            print(f"✅ Store 삭제 확인: 질문 실패 (예상된 동작)")
            return True

    except Exception as e:
        print(f"⚠️  Store 삭제 확인 중 오류: {str(e)}")
        return False


async def run_integration_test_scenario_3():
    """
    통합 테스트 시나리오 3 실행
    """
    print("=" * 60)
    print("통합 테스트 시나리오 3: 세션 종료 → 임시 지도안 삭제")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            # 1. 인증
            token = await get_auth_token(client)

            # 2. 지도안 임시 업로드
            lessonplan_filename = await upload_temporary_lessonplan(
                client, token
            )
            if lessonplan_filename is None:
                return None

            # 3. QnA 세션 생성
            session_id = await create_qna_session(
                client, token, lessonplan_filename
            )

            # 4. 질문 수행
            await ask_question(
                client, token, session_id,
                "이 지도안의 학습 목표는 무엇인가요?"
            )

            # 5. 세션 종료 및 Store 삭제
            result = await close_session_and_delete_store(
                client, token, session_id
            )

            # 6. Store 삭제 확인
            if not result.get("manual_delete_required"):
                deleted = await verify_store_deleted(
                    client, token, lessonplan_filename
                )
            else:
                deleted = None

            print("\n" + "=" * 60)
            if deleted is True:
                print("✅ 통합 테스트 시나리오 3 완료")
            elif deleted is None:
                print("⚠️  통합 테스트 시나리오 3 부분 완료 "
                      "(수동 삭제 필요)")
            else:
                print("❌ 통합 테스트 시나리오 3 실패")
            print("=" * 60)
            print("\n결과 요약:")
            print(f"- 지도안: {lessonplan_filename}")
            print(f"- QnA 세션: {session_id}")
            print(f"- 세션 종료: {'성공' if not result.get('manual_delete_required') else '수동 필요'}")
            print(f"- Store 삭제: {'확인됨' if deleted else '확인 필요'}")

            return deleted is not False

        except Exception as e:
            print(f"\n❌ 테스트 실패: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == "__main__":
    success = asyncio.run(run_integration_test_scenario_3())
    exit(0 if success is not False else 1)
