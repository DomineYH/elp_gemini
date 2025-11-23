"""
통합 테스트 전체 실행 스크립트

모든 통합 테스트 시나리오를 순차적으로 실행하고
결과를 리포트로 생성합니다.
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path


# 테스트 시나리오 임포트
sys.path.insert(0, str(Path(__file__).parent))

from test_integration_scenario_1 import (
    run_integration_test_scenario_1
)
from test_integration_scenario_2 import (
    run_integration_test_scenario_2
)
from test_integration_scenario_3 import (
    run_integration_test_scenario_3
)
from test_integration_scenario_4 import (
    run_integration_test_scenario_4
)


async def run_all_integration_tests():
    """
    모든 통합 테스트 실행
    """
    print("\n" + "=" * 70)
    print("         QnA 챗봇 애플리케이션 통합 테스트 실행")
    print("=" * 70)
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    results = []

    # 시나리오 1: 지도안 업로드 → QnA → 분석 → 결과 저장
    print("\n\n")
    try:
        success = await run_integration_test_scenario_1()
        results.append({
            "scenario": "시나리오 1",
            "description": "지도안 업로드 → QnA → 분석 → 결과 저장",
            "success": success
        })
    except Exception as e:
        print(f"\n❌ 시나리오 1 실행 중 예외 발생: {e}")
        results.append({
            "scenario": "시나리오 1",
            "description": "지도안 업로드 → QnA → 분석 → 결과 저장",
            "success": False
        })

    # 시나리오 2: 평가기준 업로드 → 분석 → Store 삭제
    print("\n\n")
    try:
        success = await run_integration_test_scenario_2()
        results.append({
            "scenario": "시나리오 2",
            "description": "평가기준 업로드 → 분석 → Store 삭제",
            "success": success
        })
    except Exception as e:
        print(f"\n❌ 시나리오 2 실행 중 예외 발생: {e}")
        results.append({
            "scenario": "시나리오 2",
            "description": "평가기준 업로드 → 분석 → Store 삭제",
            "success": False
        })

    # 시나리오 3: 세션 종료 → 임시 지도안 삭제
    print("\n\n")
    try:
        success = await run_integration_test_scenario_3()
        results.append({
            "scenario": "시나리오 3",
            "description": "세션 종료 → 임시 지도안 삭제",
            "success": success
        })
    except Exception as e:
        print(f"\n❌ 시나리오 3 실행 중 예외 발생: {e}")
        results.append({
            "scenario": "시나리오 3",
            "description": "세션 종료 → 임시 지도안 삭제",
            "success": False
        })

    # 시나리오 4: 프롬프트 로드 → QnA
    print("\n\n")
    try:
        success = await run_integration_test_scenario_4()
        results.append({
            "scenario": "시나리오 4",
            "description": "프롬프트 로드 → QnA",
            "success": success
        })
    except Exception as e:
        print(f"\n❌ 시나리오 4 실행 중 예외 발생: {e}")
        results.append({
            "scenario": "시나리오 4",
            "description": "프롬프트 로드 → QnA",
            "success": False
        })

    # 최종 결과 출력
    print("\n\n" + "=" * 70)
    print("                   통합 테스트 최종 결과")
    print("=" * 70)

    success_count = sum(1 for r in results if r["success"])
    total_count = len(results)

    for i, result in enumerate(results, 1):
        status = "✅ 성공" if result["success"] else "❌ 실패"
        print(f"\n{i}. {result['scenario']}: {status}")
        print(f"   {result['description']}")

    print("\n" + "=" * 70)
    print(f"총 {total_count}개 시나리오 중 {success_count}개 성공")
    print(f"성공률: {(success_count / total_count * 100):.1f}%")
    print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 리포트 파일 생성
    await generate_test_report(results)

    # 모든 테스트 성공 시 True 반환
    return success_count == total_count


async def generate_test_report(results: list):
    """
    테스트 결과 리포트 생성
    """
    report_dir = Path("tests/reports")
    report_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = report_dir / f"integration_test_report_{timestamp}.md"

    success_count = sum(1 for r in results if r["success"])
    total_count = len(results)

    report_content = f"""# 통합 테스트 결과 리포트

## 테스트 정보
- **실행 시간**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **총 시나리오**: {total_count}개
- **성공**: {success_count}개
- **실패**: {total_count - success_count}개
- **성공률**: {(success_count / total_count * 100):.1f}%

---

## 시나리오별 결과

"""

    for i, result in enumerate(results, 1):
        status_emoji = "✅" if result["success"] else "❌"
        status_text = "성공" if result["success"] else "실패"

        report_content += f"""### {i}. {result['scenario']}: {status_emoji} {status_text}
- **설명**: {result['description']}
- **결과**: {status_text}

"""

    report_content += """---

## 결론

"""

    if success_count == total_count:
        report_content += """✅ **모든 통합 테스트가 성공적으로 완료되었습니다.**

Phase 4의 통합 테스트 단계를 통과했으며,
다음 단계(성능 테스트, 문서화, 배포)로 진행할 수 있습니다.
"""
    elif success_count > 0:
        report_content += f"""⚠️  **일부 통합 테스트가 실패했습니다.**

{total_count - success_count}개의 시나리오에서 문제가 발생했습니다.
실패한 시나리오를 확인하고 수정이 필요합니다.
"""
    else:
        report_content += """❌ **모든 통합 테스트가 실패했습니다.**

시스템 전체에 문제가 있을 가능성이 높습니다.
서버 실행 상태, 환경 설정, 데이터베이스 연결 등을 확인하세요.
"""

    report_content += f"""
---

**작성자**: 통합 테스트 시스템
**생성일**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    # 파일 저장
    report_file.write_text(report_content, encoding='utf-8')

    print(f"\n📄 테스트 리포트 생성: {report_file}")


if __name__ == "__main__":
    all_success = asyncio.run(run_all_integration_tests())
    exit(0 if all_success else 1)
