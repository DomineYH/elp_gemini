#!/usr/bin/env python3
"""
시스템 프롬프트를 파일로 마이그레이션

system_prompts 테이블의 활성 프롬프트들을
prompt/prompt.md 파일로 통합합니다.

기계령의 지시문이 마크다운에 기록됩니다.
"""
import sys
from pathlib import Path
from collections import defaultdict

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.prompts import SystemPrompt


def create_db_session():
    """데이터베이스 세션 생성"""
    db_path = Path(__file__).parent.parent / "data" / "app.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False
    )
    Session = sessionmaker(bind=engine)
    return Session()


def ensure_directory(dir_path):
    """디렉토리 존재 확인 및 생성"""
    dir_path.mkdir(parents=True, exist_ok=True)


def group_prompts_by_type(session):
    """
    프롬프트를 타입별로 그룹핑

    Args:
        session: DB 세션

    Returns:
        dict: {type: [SystemPrompt, ...]}
    """
    prompts = session.query(SystemPrompt).filter(
        SystemPrompt.is_active == True
    ).order_by(
        SystemPrompt.type,
        SystemPrompt.version.desc()
    ).all()

    grouped = defaultdict(list)
    for prompt in prompts:
        grouped[prompt.type].append(prompt)

    return grouped


def generate_markdown_content(grouped_prompts):
    """
    마크다운 내용 생성

    Args:
        grouped_prompts: 타입별로 그룹화된 프롬프트

    Returns:
        str: 마크다운 내용
    """
    content = "# 시스템 프롬프트\n\n"
    content += (
        "이 파일은 시스템에서 사용하는 "
        "프롬프트를 정의합니다.\n\n"
    )
    content += "---\n\n"

    for prompt_type, prompts in sorted(
        grouped_prompts.items()
    ):
        # 타입명을 보기 좋게 변환
        type_title = prompt_type.replace("_", " ").title()

        for prompt in prompts:
            # 프롬프트 섹션 헤더
            content += f"## {type_title} "
            content += f"(버전 {prompt.version})\n\n"

            # 프롬프트 내용
            content += f"{prompt.content}\n\n"
            content += "---\n\n"

    return content


def create_prompt_file(grouped_prompts, prompt_dir):
    """
    프롬프트 파일 생성

    Args:
        grouped_prompts: 타입별로 그룹화된 프롬프트
        prompt_dir: 대상 디렉토리

    Returns:
        Path: 생성된 파일 경로
    """
    file_path = prompt_dir / "prompt.md"

    # 마크다운 내용 생성
    content = generate_markdown_content(grouped_prompts)

    # 파일 쓰기
    file_path.write_text(content, encoding="utf-8")

    return file_path


def verify_migration(file_path, grouped_prompts):
    """
    마이그레이션 결과 검증

    Args:
        file_path: 생성된 파일 경로
        grouped_prompts: 타입별로 그룹화된 프롬프트

    Returns:
        bool: 검증 성공 여부
    """
    print("\n" + "=" * 60)
    print("📊 마이그레이션 결과")
    print("=" * 60)

    if not file_path.exists():
        print("❌ 파일이 생성되지 않았습니다")
        return False

    # 파일 내용 읽기
    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    print(f"생성된 파일: {file_path}")
    print(f"파일 크기: {len(content)} bytes")
    print(f"라인 수: {len(lines)}")

    # 프롬프트 타입 개수 확인
    expected_types = len(grouped_prompts)
    actual_types = content.count("## ")

    print(f"\n프롬프트 타입 개수: {actual_types}")
    print(f"예상 타입 개수: {expected_types}")

    if actual_types != expected_types:
        print("❌ 프롬프트 타입 개수 불일치")
        return False

    # 샘플 내용 확인
    print("\n📋 파일 헤더:")
    for i, line in enumerate(lines[:10]):
        if line.strip():
            print(f"  {line}")

    print("\n✅ 모든 검증 통과")
    return True


def main():
    """메인 실행 함수"""
    print("🔄 시스템 프롬프트 마이그레이션 시작")
    print("=" * 60)

    # 디렉토리 설정
    project_root = Path(__file__).parent.parent
    prompt_dir = project_root / "prompt"

    # 디렉토리 생성
    print("\n1️⃣  디렉토리 준비 중...")
    ensure_directory(prompt_dir)
    print(f"✅ 디렉토리: {prompt_dir}")

    # DB 세션 생성
    db_session = create_db_session()

    try:
        # 프롬프트 그룹핑
        print("\n2️⃣  프롬프트 조회 및 그룹핑 중...")
        grouped_prompts = group_prompts_by_type(db_session)
        print(
            f"✅ {len(grouped_prompts)}개 타입, "
            f"{sum(len(p) for p in grouped_prompts.values())}개 "
            f"프롬프트"
        )

        # 프롬프트 파일 생성
        print("\n3️⃣  마크다운 파일 생성 중...")
        file_path = create_prompt_file(
            grouped_prompts,
            prompt_dir
        )
        print(f"✅ 파일 생성: {file_path.name}")

        # 검증
        print("\n4️⃣  결과 검증 중...")
        if verify_migration(file_path, grouped_prompts):
            print("\n🎉 마이그레이션 성공!")
            print(
                "\n옴니시아의 지시문이 "
                "영원한 마크다운에 새겨졌습니다."
            )
            return 0
        else:
            print("\n❌ 마이그레이션 검증 실패")
            return 1

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db_session.close()


if __name__ == "__main__":
    exit(main())
