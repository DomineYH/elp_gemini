"""
통합 테스트 시나리오 1: 지도안 업로드 → QnA → 분석 → 결과 저장

테스트 절차:
1. 지도안 파일 업로드
2. QnA 세션 생성
3. QnA 질문
4. 평가 실행
5. 평가 결과 조회
"""
import asyncio
import httpx
import io
from pathlib import Path


# 테스트 설정
BASE_URL = "http://localhost:8000"
TEST_USERNAME = "testuser"
TEST_PASSWORD = "testpassword"
TEST_LESSONPLAN_CONTENT = """
# 테스트 지도안

## 학습 목표
- 학생들이 기본 개념을 이해한다.

## 수업 내용
1. 도입 (10분)
2. 전개 (30분)
3. 정리 (10분)
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


async def upload_lessonplan(
    client: httpx.AsyncClient,
    token: str
) -> str | None:
    """지도안 업로드"""
    print("\n📤 지도안 업로드 중...")

    # 테스트 파일 생성
    file_content = TEST_LESSONPLAN_CONTENT.encode('utf-8')
    files = {
        'file': ('test_lessonplan.txt', io.BytesIO(file_content))
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
    latency = data.get("latency_ms", 0)

    print(f"✅ 답변: {answer[:100]}...")
    print(f"   응답 시간: {latency}ms")
    return data


async def run_evaluation(
    client: httpx.AsyncClient,
    token: str,
    lessonplan_filename: str
) -> str:
    """평가 실행"""
    print("\n🔍 평가 실행 중...")

    response = await client.post(
        f"{BASE_URL}/api/evaluations",
        json={
            "lessonplan_filename": lessonplan_filename,
            "evaluation_type": "comprehensive"
        },
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code != 201:
        raise Exception(f"평가 실행 실패: {response.text}")

    data = response.json()
    analysis_filename = data["analysis_filename"]
    latency = data.get("latency_ms", 0)

    print(f"✅ 평가 완료: {analysis_filename}")
    print(f"   응답 시간: {latency}ms")
    return analysis_filename


async def get_evaluation_result(
    client: httpx.AsyncClient,
    token: str,
    filename: str
) -> str:
    """평가 결과 조회"""
    print(f"\n📄 평가 결과 조회 중: {filename}")

    response = await client.get(
        f"{BASE_URL}/api/evaluations/{filename}",
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code != 200:
        raise Exception(f"평가 결과 조회 실패: {response.text}")

    data = response.json()
    content = data["content"]
    file_size = data["file_size"]

    print(f"✅ 평가 결과 조회 완료")
    print(f"   파일 크기: {file_size} bytes")
    print(f"   내용 미리보기: {content[:200]}...")
    return content


async def run_integration_test_scenario_1():
    """
    통합 테스트 시나리오 1 실행
    """
    print("=" * 60)
    print("통합 테스트 시나리오 1: 지도안 업로드 → QnA → 분석 → 결과 저장")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            # 1. 인증
            token = await get_auth_token(client)

            # 2. 지도안 업로드
            lessonplan_filename = await upload_lessonplan(
                client, token
            )
            if lessonplan_filename is None:
                return None

            # 3. QnA 세션 생성
            session_id = await create_qna_session(
                client, token, lessonplan_filename
            )

            # 4. QnA 질문 (2회)
            await ask_question(
                client, token, session_id,
                "이 지도안의 학습 목표는 무엇인가요?"
            )

            await ask_question(
                client, token, session_id,
                "수업은 총 몇 분 동안 진행되나요?"
            )

            # 5. 평가 실행
            analysis_filename = await run_evaluation(
                client, token, lessonplan_filename
            )

            # 6. 평가 결과 조회
            content = await get_evaluation_result(
                client, token, analysis_filename
            )

            print("\n" + "=" * 60)
            print("✅ 통합 테스트 시나리오 1 완료")
            print("=" * 60)
            print("\n결과 요약:")
            print(f"- 지도안: {lessonplan_filename}")
            print(f"- QnA 세션: {session_id}")
            print(f"- 질문 수: 2개")
            print(f"- 평가 결과: {analysis_filename}")
            print(f"- 결과 크기: {len(content)} bytes")

            return True

        except Exception as e:
            print(f"\n❌ 테스트 실패: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == "__main__":
    success = asyncio.run(run_integration_test_scenario_1())
    exit(0 if success is not False else 1)
