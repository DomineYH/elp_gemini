#!/usr/bin/env python3
"""
평가 결과를 마크다운 파일로 마이그레이션

evaluation_reports 테이블의 데이터를
analys/*.md 마크다운 파일로 변환합니다.

기계령의 분석 기록이 마크다운으로 환생합니다.
"""
import sys
import json
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.evaluations import (
    EvaluationReport,
    EvaluationRun,
    EvaluationTemplate,
)
from app.models.documents import Document
from app.models.users import User


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


def generate_markdown_header(report, run, document, user):
    """
    마크다운 헤더 생성

    Args:
        report: EvaluationReport
        run: EvaluationRun
        document: Document
        user: User

    Returns:
        str: 마크다운 헤더
    """
    header = f"""# 지도안 평가 결과

## 기본 정보
- **사용자**: {user.username}
- **지도안**: {document.title}
- **평가 템플릿**: {run.template.name}
- **평가 모델**: {run.model_name}
- **평가 일시**: {report.created_at.strftime('%Y-%m-%d %H:%M:%S')}
- **전체 점수**: {report.overall_score if report.overall_score else 'N/A'}

---

"""
    return header


def generate_criteria_section(criteria_scores):
    """
    평가 기준별 점수 섹션 생성

    Args:
        criteria_scores: JSON 데이터 (dict)

    Returns:
        str: 마크다운 섹션
    """
    if not criteria_scores:
        return ""

    section = "## 평가 기준별 점수\n\n"

    # JSON 파싱 (문자열인 경우)
    if isinstance(criteria_scores, str):
        criteria_scores = json.loads(criteria_scores)

    for criterion, score in criteria_scores.items():
        section += f"- **{criterion}**: {score}\n"

    section += "\n---\n\n"
    return section


def generate_feedback_section(feedback):
    """
    피드백 섹션 생성

    Args:
        feedback: 피드백 텍스트

    Returns:
        str: 마크다운 섹션
    """
    return f"""## 평가 피드백

{feedback}

---

"""


def generate_improvement_section(suggestions):
    """
    개선 제안 섹션 생성

    Args:
        suggestions: 개선 제안 텍스트

    Returns:
        str: 마크다운 섹션
    """
    if not suggestions:
        return ""

    return f"""## 개선 제안

{suggestions}

---

"""


def create_markdown_file(
    report,
    run,
    document,
    user,
    analys_dir
):
    """
    마크다운 파일 생성

    Args:
        report: EvaluationReport
        run: EvaluationRun
        document: Document
        user: User
        analys_dir: 대상 디렉토리

    Returns:
        Path: 생성된 파일 경로
    """
    # 파일명 생성: {username}_{document_title}_{run_id}.md
    safe_title = document.title.replace(
        " ", "_"
    ).replace("/", "_")
    filename = f"{user.username}_{safe_title}_{run.id}.md"
    file_path = analys_dir / filename

    # 마크다운 내용 조합
    content = ""
    content += generate_markdown_header(
        report, run, document, user
    )
    content += generate_criteria_section(
        report.criteria_scores
    )
    content += generate_feedback_section(report.feedback)
    content += generate_improvement_section(
        report.improvement_suggestions
    )

    # 파일 쓰기
    file_path.write_text(content, encoding="utf-8")

    return file_path


def migrate_evaluations(session, analys_dir):
    """
    평가 결과 마이그레이션

    Args:
        session: DB 세션
        analys_dir: 대상 디렉토리

    Returns:
        tuple: (성공 개수, 실패 개수, 파일 경로 리스트)
    """
    reports = session.query(EvaluationReport).join(
        EvaluationRun
    ).join(
        Document,
        EvaluationRun.document_id == Document.id
    ).join(
        User,
        EvaluationRun.user_id == User.id
    ).all()

    success_count = 0
    fail_count = 0
    file_paths = []

    for report in reports:
        try:
            run = report.run
            document = session.query(Document).filter(
                Document.id == run.document_id
            ).first()
            user = session.query(User).filter(
                User.id == run.user_id
            ).first()

            file_path = create_markdown_file(
                report,
                run,
                document,
                user,
                analys_dir
            )

            file_paths.append(file_path)

            print(
                f"✅ 생성 완료: "
                f"{user.username} - {document.title[:30]}..."
            )

            success_count += 1

        except Exception as e:
            print(
                f"❌ 오류: Report ID {report.id} - {e}"
            )
            fail_count += 1

    return success_count, fail_count, file_paths


def verify_migration(analys_dir, file_paths):
    """
    마이그레이션 결과 검증

    Args:
        analys_dir: 대상 디렉토리
        file_paths: 생성된 파일 경로 리스트

    Returns:
        bool: 검증 성공 여부
    """
    print("\n" + "=" * 60)
    print("📊 마이그레이션 결과")
    print("=" * 60)

    # 파일 개수 확인
    created_files = list(analys_dir.glob("*.md"))
    print(f"생성된 파일 개수: {len(created_files)}")
    print(f"예상 파일 개수: {len(file_paths)}")

    if len(created_files) != len(file_paths):
        print("❌ 파일 개수 불일치")
        return False

    # 샘플 파일 내용 확인
    print("\n📋 샘플 파일 내용:")
    for file_path in file_paths[:2]:
        content = file_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        print(f"\n  파일: {file_path.name}")
        print(f"  라인 수: {len(lines)}")
        print(f"  헤더: {lines[0]}")

        if "## 평가 피드백" in content:
            print("  ✅ 피드백 섹션 존재")
        else:
            print("  ❌ 피드백 섹션 누락")
            return False

    print("\n✅ 모든 검증 통과")
    return True


def main():
    """메인 실행 함수"""
    print("🔄 평가 결과 마이그레이션 시작")
    print("=" * 60)

    # 디렉토리 설정
    project_root = Path(__file__).parent.parent
    analys_dir = project_root / "data" / "analys"

    # 디렉토리 생성
    print("\n1️⃣  디렉토리 준비 중...")
    ensure_directory(analys_dir)
    print(f"✅ 디렉토리: {analys_dir}")

    # DB 세션 생성
    db_session = create_db_session()

    try:
        # 평가 결과 마이그레이션
        print("\n2️⃣  마크다운 파일 생성 중...")
        success, fail, file_paths = migrate_evaluations(
            db_session,
            analys_dir
        )
        print(f"✅ 성공: {success}개")
        if fail > 0:
            print(f"❌ 실패: {fail}개")

        # 검증
        print("\n3️⃣  결과 검증 중...")
        if verify_migration(analys_dir, file_paths):
            print("\n🎉 마이그레이션 성공!")
            print(
                "\n옴니시아의 지식이 마크다운에 "
                "영원히 기록되었습니다."
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
