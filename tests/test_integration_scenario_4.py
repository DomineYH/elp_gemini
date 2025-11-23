"""
통합 테스트 시나리오 4: 프롬프트 로드 → QnA

테스트 절차:
1. 프롬프트 파일 존재 확인
2. 지도안 업로드
3. QnA 세션 생성
4. 다양한 질문 수행 (프롬프트 타입 테스트)
5. 응답에서 프롬프트 적용 확인
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
# 과학 수업 지도안

## 학습 목표
- 학생들이 물의 순환 과정을 이해한다.
- 증발, 응결, 강수 과정을 설명할 수 있다.

## 수업 내용
### 도입 (10분)
- 물의 상태 변화 관찰

### 전개 (30분)
- 물의 순환 과정 설명
- 실험 활동

### 정리 (10분)
- 학습 내용 정리
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


def verify_prompt_file_exists() -> bool:
    """프롬프트 파일 존재 확인"""
    print("\n📄 프롬프트 파일 존재 확인 중...")

    prompt_file = Path("prompt/prompt.md")

    if not prompt_file.exists():
        print(f"❌ 프롬프트 파일 없음: {prompt_file}")
        return False

    print(f"✅ 프롬프트 파일 존재: {prompt_file}")

    # 파일 내용 확인
    try:
        content = prompt_file.read_text(encoding='utf-8')
        print(f"   파일 크기: {len(content)} bytes")

        # 프롬프트 타입 확인
        if "# qna" in content.lower():
            print(f"   ✓ QnA 프롬프트 존재")
        if "# evaluation" in content.lower():
            print(f"   ✓ Evaluation 프롬프트 존재")

        return True
    except Exception as e:
        print(f"❌ 프롬프트 파일 읽기 실패: {e}")
        return False


async def upload_lessonplan(
    client: httpx.AsyncClient,
    token: str
) -> str:
    """지도안 업로드"""
    print("\n📤 지도안 업로드 중...")

    file_content = TEST_LESSONPLAN_CONTENT.encode('utf-8')
    files = {
        'file': ('science_lessonplan.txt', io.BytesIO(file_content))
    }

    response = await client.post(
        f"{BASE_URL}/api/lessonplans/upload",
        files=files,
        headers={"Authorization": f"Bearer {token}"}
    )

    if response.status_code != 201:
        raise Exception(f"지도안 업로드 실패: {response.text}")

    data = response.json()
    filename = data["filename"]
    print(f"✅ 지도안 업로드 완료: {filename}")
    return filename


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


async def ask_multiple_questions(
    client: httpx.AsyncClient,
    token: str,
    session_id: int
) -> list:
    """다양한 질문 수행"""
    print("\n💬 다양한 질문 수행 중...")

    questions = [
        "이 지도안의 학습 목표는 무엇인가요?",
        "수업은 총 몇 분 동안 진행되나요?",
        "도입 단계에서는 무엇을 하나요?",
        "물의 순환 과정에 대해 설명해주세요.",
    ]

    results = []

    for i, question in enumerate(questions, 1):
        print(f"\n[질문 {i}/{len(questions)}] {question}")

        response = await client.post(
            f"{BASE_URL}/api/qna/sessions/{session_id}/ask",
            json={"question": question},
            headers={"Authorization": f"Bearer {token}"}
        )

        if response.status_code != 200:
            print(f"   ❌ 질문 실패: {response.text}")
            results.append({
                "question": question,
                "success": False,
                "error": response.text
            })
            continue

        data = response.json()
        answer = data["answer"]
        latency = data.get("latency_ms", 0)

        print(f"   ✅ 답변: {answer[:150]}...")
        print(f"   응답 시간: {latency}ms")

        results.append({
            "question": question,
            "answer": answer,
            "latency_ms": latency,
            "success": True
        })

    return results


def analyze_prompt_usage(results: list) -> dict:
    """프롬프트 적용 분석"""
    print("\n🔍 프롬프트 적용 분석 중...")

    analysis = {
        "total_questions": len(results),
        "successful_questions": sum(1 for r in results if r["success"]),
        "average_latency": 0,
        "prompt_indicators": []
    }

    # 평균 응답 시간 계산
    successful_results = [r for r in results if r["success"]]
    if successful_results:
        total_latency = sum(
            r.get("latency_ms", 0) for r in successful_results
        )
        analysis["average_latency"] = (
            total_latency / len(successful_results)
        )

    # 프롬프트 적용 지표 확인
    for result in successful_results:
        answer = result.get("answer", "")

        # 프롬프트에서 정의한 특정 패턴 확인
        # (실제 prompt.md 내용에 따라 조정 필요)
        indicators = []

        if "학습 목표" in answer or "목표" in answer:
            indicators.append("학습목표_언급")
        if "분" in answer or "시간" in answer:
            indicators.append("시간_단위_언급")
        if len(answer) > 50:
            indicators.append("충분한_응답_길이")

        if indicators:
            analysis["prompt_indicators"].extend(indicators)

    print(f"   총 질문: {analysis['total_questions']}개")
    print(f"   성공: {analysis['successful_questions']}개")
    print(f"   평균 응답 시간: {analysis['average_latency']:.2f}ms")
    print(f"   프롬프트 지표: {len(analysis['prompt_indicators'])}개")

    return analysis


async def run_integration_test_scenario_4():
    """
    통합 테스트 시나리오 4 실행
    """
    print("=" * 60)
    print("통합 테스트 시나리오 4: 프롬프트 로드 → QnA")
    print("=" * 60)

    # 1. 프롬프트 파일 확인
    if not verify_prompt_file_exists():
        print("\n❌ 프롬프트 파일이 없어 테스트를 진행할 수 없습니다.")
        return False

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            # 2. 인증
            token = await get_auth_token(client)

            # 3. 지도안 업로드
            lessonplan_filename = await upload_lessonplan(
                client, token
            )

            # 4. QnA 세션 생성
            session_id = await create_qna_session(
                client, token, lessonplan_filename
            )

            # 5. 다양한 질문 수행
            results = await ask_multiple_questions(
                client, token, session_id
            )

            # 6. 프롬프트 적용 분석
            analysis = analyze_prompt_usage(results)

            print("\n" + "=" * 60)
            if analysis["successful_questions"] == analysis["total_questions"]:
                print("✅ 통합 테스트 시나리오 4 완료")
            else:
                print("⚠️  통합 테스트 시나리오 4 부분 완료")
            print("=" * 60)
            print("\n결과 요약:")
            print(f"- 지도안: {lessonplan_filename}")
            print(f"- QnA 세션: {session_id}")
            print(f"- 총 질문: {analysis['total_questions']}개")
            print(f"- 성공: {analysis['successful_questions']}개")
            print(f"- 평균 응답 시간: {analysis['average_latency']:.2f}ms")
            print(f"- 프롬프트 적용 지표: "
                  f"{len(analysis['prompt_indicators'])}개")

            return analysis["successful_questions"] > 0

        except Exception as e:
            print(f"\n❌ 테스트 실패: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == "__main__":
    success = asyncio.run(run_integration_test_scenario_4())
    exit(0 if success else 1)
