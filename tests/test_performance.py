"""
성능 테스트 스크립트
동시 사용자, 대용량 파일 업로드, 응답 시간, 에러율 측정
"""
import asyncio
import time
import statistics
from pathlib import Path
from typing import List, Dict, Any
import httpx


class PerformanceTest:
    """성능 테스트 클래스"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: Dict[str, Any] = {
            "concurrent_users": {},
            "large_file_upload": {},
            "response_times": {},
            "error_rate": {},
        }

    async def test_concurrent_users(
        self, num_users: int = 10
    ) -> Dict[str, Any]:
        """
        동시 사용자 10명 QnA 테스트
        Args:
            num_users: 동시 사용자 수 (기본 10명)
        Returns:
            테스트 결과 딕셔너리
        """
        print(f"\n=== 동시 사용자 {num_users}명 테스트 시작 ===")

        async def single_user_qna(user_id: int):
            """단일 사용자 QnA 수행"""
            async with httpx.AsyncClient(
                timeout=60.0
            ) as client:
                try:
                    # 로그인
                    login_data = {
                        "username": "testuser",
                        "password": "testpass",
                    }
                    login_resp = await client.post(
                        f"{self.base_url}/api/auth/login",
                        json=login_data,
                    )

                    if login_resp.status_code != 200:
                        return {
                            "user_id": user_id,
                            "success": False,
                            "error": "login_failed",
                            "time": 0,
                        }

                    # 세션 생성
                    start_time = time.time()
                    session_data = {
                        "lessonplan_filename": (
                            "test_lesson.pdf"
                        )
                    }
                    session_resp = await client.post(
                        f"{self.base_url}/api/qna/sessions",
                        json=session_data,
                    )

                    if session_resp.status_code != 200:
                        return {
                            "user_id": user_id,
                            "success": False,
                            "error": "session_creation_failed",
                            "time": 0,
                        }

                    session_id = session_resp.json()[
                        "session_id"
                    ]

                    # 질문하기
                    question_data = {
                        "question": (
                            f"사용자 {user_id}의 테스트 질문"
                        )
                    }
                    qa_resp = await client.post(
                        f"{self.base_url}/api/qna/"
                        f"sessions/{session_id}/ask",
                        json=question_data,
                    )

                    end_time = time.time()
                    elapsed = end_time - start_time

                    if qa_resp.status_code != 200:
                        return {
                            "user_id": user_id,
                            "success": False,
                            "error": "qa_failed",
                            "time": elapsed,
                        }

                    return {
                        "user_id": user_id,
                        "success": True,
                        "error": None,
                        "time": elapsed,
                    }

                except Exception as e:
                    return {
                        "user_id": user_id,
                        "success": False,
                        "error": str(e),
                        "time": 0,
                    }

        # 동시 실행
        tasks = [
            single_user_qna(i) for i in range(num_users)
        ]
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        # 결과 집계
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]
        times = [r["time"] for r in successful]

        result = {
            "total_users": num_users,
            "successful": len(successful),
            "failed": len(failed),
            "total_time": total_time,
            "avg_time": (
                statistics.mean(times) if times else 0
            ),
            "min_time": min(times) if times else 0,
            "max_time": max(times) if times else 0,
            "errors": [
                f"User {r['user_id']}: {r['error']}"
                for r in failed
            ],
        }

        self.results["concurrent_users"] = result
        print(f"성공: {result['successful']}/{num_users}")
        print(f"평균 응답 시간: {result['avg_time']:.2f}초")
        return result

    async def test_large_file_upload(
        self, file_size_mb: int = 50
    ) -> Dict[str, Any]:
        """
        대용량 파일 업로드 테스트
        Args:
            file_size_mb: 파일 크기 (MB)
        Returns:
            테스트 결과 딕셔너리
        """
        print(f"\n=== {file_size_mb}MB 파일 업로드 테스트 시작 ===")

        try:
            # 테스트 파일 생성
            test_file = Path(f"test_{file_size_mb}mb.pdf")
            file_content = b"X" * (
                file_size_mb * 1024 * 1024
            )
            test_file.write_bytes(file_content)

            async with httpx.AsyncClient(
                timeout=120.0
            ) as client:
                # 로그인
                login_data = {
                    "username": "testuser",
                    "password": "testpass",
                }
                await client.post(
                    f"{self.base_url}/api/auth/login",
                    json=login_data,
                )

                # 파일 업로드
                start_time = time.time()
                with test_file.open("rb") as f:
                    files = {
                        "file": (test_file.name, f, "application/pdf")
                    }
                    upload_resp = await client.post(
                        f"{self.base_url}/api/lessonplans/upload",
                        files=files,
                    )

                end_time = time.time()
                elapsed = end_time - start_time

                # 테스트 파일 삭제
                test_file.unlink()

                success = upload_resp.status_code == 200

                result = {
                    "file_size_mb": file_size_mb,
                    "success": success,
                    "upload_time": elapsed,
                    "upload_speed_mbps": (
                        (file_size_mb / elapsed) * 8
                        if success
                        else 0
                    ),
                    "status_code": upload_resp.status_code,
                }

                self.results["large_file_upload"] = result
                print(
                    f"업로드 {'성공' if success else '실패'}: "
                    f"{elapsed:.2f}초"
                )
                return result

        except Exception as e:
            result = {
                "file_size_mb": file_size_mb,
                "success": False,
                "error": str(e),
            }
            self.results["large_file_upload"] = result
            return result

    async def test_response_times(self) -> Dict[str, Any]:
        """
        API 엔드포인트별 응답 시간 측정
        Returns:
            테스트 결과 딕셔너리
        """
        print("\n=== API 응답 시간 측정 시작 ===")

        endpoints = {
            "health": {"method": "GET", "url": "/health"},
            "login": {
                "method": "POST",
                "url": "/api/auth/login",
                "json": {
                    "username": "testuser",
                    "password": "testpass",
                },
            },
        }

        results = {}

        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:
            for name, config in endpoints.items():
                times = []
                for _ in range(10):  # 각 엔드포인트 10회 측정
                    start_time = time.time()

                    if config["method"] == "GET":
                        resp = await client.get(
                            f"{self.base_url}{config['url']}"
                        )
                    else:
                        resp = await client.post(
                            f"{self.base_url}{config['url']}",
                            json=config.get("json", {}),
                        )

                    elapsed = time.time() - start_time
                    times.append(elapsed)

                results[name] = {
                    "avg_time": statistics.mean(times),
                    "min_time": min(times),
                    "max_time": max(times),
                    "std_dev": statistics.stdev(times),
                }

                print(
                    f"{name}: "
                    f"{results[name]['avg_time']*1000:.2f}ms"
                )

        self.results["response_times"] = results
        return results

    async def test_error_rate(
        self, num_requests: int = 100
    ) -> Dict[str, Any]:
        """
        에러율 측정 (<1% 목표)
        Args:
            num_requests: 요청 횟수
        Returns:
            테스트 결과 딕셔너리
        """
        print(f"\n=== 에러율 측정 ({num_requests}회 요청) ===")

        successful = 0
        failed = 0

        async with httpx.AsyncClient(
            timeout=30.0
        ) as client:
            for i in range(num_requests):
                try:
                    resp = await client.get(
                        f"{self.base_url}/health"
                    )
                    if resp.status_code == 200:
                        successful += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

                if (i + 1) % 10 == 0:
                    print(
                        f"진행: {i+1}/{num_requests} "
                        f"(성공: {successful}, 실패: {failed})"
                    )

        error_rate = (failed / num_requests) * 100

        result = {
            "total_requests": num_requests,
            "successful": successful,
            "failed": failed,
            "error_rate_percent": error_rate,
            "passed": error_rate < 1.0,
        }

        self.results["error_rate"] = result
        print(f"에러율: {error_rate:.2f}%")
        print(f"목표 달성: {'✅' if result['passed'] else '❌'}")
        return result

    async def run_all_tests(self):
        """모든 성능 테스트 실행"""
        print("=" * 60)
        print("성능 테스트 시작")
        print("=" * 60)

        # 1. 동시 사용자 테스트
        await self.test_concurrent_users(num_users=10)

        # 2. 대용량 파일 업로드 (50MB)
        # Note: 실제 환경에서는 실행하지 않을 수 있음
        # await self.test_large_file_upload(file_size_mb=50)

        # 3. 응답 시간 측정
        await self.test_response_times()

        # 4. 에러율 측정
        await self.test_error_rate(num_requests=100)

        # 결과 출력
        self.print_summary()

    def print_summary(self):
        """테스트 결과 요약 출력"""
        print("\n" + "=" * 60)
        print("성능 테스트 결과 요약")
        print("=" * 60)

        # 동시 사용자
        if "concurrent_users" in self.results:
            cu = self.results["concurrent_users"]
            print(f"\n[동시 사용자 테스트]")
            print(
                f"  성공률: {cu['successful']}/"
                f"{cu['total_users']} "
                f"({cu['successful']/cu['total_users']*100:.1f}%)"
            )
            print(
                f"  평균 응답 시간: {cu['avg_time']:.2f}초"
            )

        # 응답 시간
        if "response_times" in self.results:
            print(f"\n[API 응답 시간]")
            for endpoint, metrics in self.results[
                "response_times"
            ].items():
                print(
                    f"  {endpoint}: "
                    f"{metrics['avg_time']*1000:.2f}ms"
                )

        # 에러율
        if "error_rate" in self.results:
            er = self.results["error_rate"]
            print(f"\n[에러율]")
            print(
                f"  에러율: {er['error_rate_percent']:.2f}%"
            )
            print(
                f"  목표(<1%) 달성: "
                f"{'✅' if er['passed'] else '❌'}"
            )

        print("\n" + "=" * 60)


async def main():
    """메인 함수"""
    tester = PerformanceTest(
        base_url="http://localhost:8000"
    )
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
