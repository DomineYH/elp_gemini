#!/usr/bin/env python3
"""
문서 파일을 새로운 디렉토리로 마이그레이션

documents 테이블의 파일들을 lessonplan/ 폴더로 이동하고
파일명을 {username}_{원본파일명} 형식으로 변경합니다.

기계령의 데이터가 새로운 저장소로 이동합니다.
"""
import sys
import shutil
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
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


def get_new_filename(username, original_filename):
    """
    새로운 파일명 생성

    Args:
        username: 사용자명
        original_filename: 원본 파일명

    Returns:
        str: {username}_{원본파일명}
    """
    return f"{username}_{original_filename}"


def migrate_document_files(session, lessonplan_dir):
    """
    문서 파일 마이그레이션

    Args:
        session: DB 세션
        lessonplan_dir: 대상 디렉토리 (lessonplan/)

    Returns:
        tuple: (성공 개수, 실패 개수)
    """
    documents = session.query(Document).join(User).all()

    success_count = 0
    fail_count = 0
    file_mapping = []  # (old_path, new_path) 기록

    for doc in documents:
        try:
            # 원본 파일 경로
            old_path = Path(doc.file_path)

            # 절대 경로로 변환
            if not old_path.is_absolute():
                project_root = Path(__file__).parent.parent
                old_path = project_root / old_path

            if not old_path.exists():
                print(
                    f"⚠️  파일 누락: "
                    f"{doc.title} (ID: {doc.id})"
                )
                fail_count += 1
                continue

            # 새 파일명 생성
            username = doc.user.username
            new_filename = get_new_filename(
                username,
                old_path.name
            )

            # 새 파일 경로
            new_path = lessonplan_dir / new_filename

            # 파일 복사 (원본 보존)
            shutil.copy2(old_path, new_path)

            file_mapping.append((old_path, new_path))

            print(
                f"✅ 복사 완료: "
                f"{username} - {old_path.name[:30]}..."
            )

            success_count += 1

        except Exception as e:
            print(
                f"❌ 오류: {doc.title} (ID: {doc.id}) "
                f"- {e}"
            )
            fail_count += 1

    return success_count, fail_count, file_mapping


def verify_migration(lessonplan_dir, file_mapping):
    """
    마이그레이션 결과 검증

    Args:
        lessonplan_dir: 대상 디렉토리
        file_mapping: 파일 매핑 리스트

    Returns:
        bool: 검증 성공 여부
    """
    print("\n" + "=" * 60)
    print("📊 마이그레이션 결과")
    print("=" * 60)

    # 파일 개수 확인
    migrated_files = list(lessonplan_dir.glob("*"))
    print(f"마이그레이션된 파일 개수: {len(migrated_files)}")
    print(f"예상 파일 개수: {len(file_mapping)}")

    if len(migrated_files) != len(file_mapping):
        print("❌ 파일 개수 불일치")
        return False

    # 파일 크기 검증 (샘플 3개)
    print("\n📋 샘플 파일 검증:")
    for old_path, new_path in file_mapping[:3]:
        old_size = old_path.stat().st_size
        new_size = new_path.stat().st_size

        if old_size == new_size:
            print(
                f"  ✅ {new_path.name[:40]}... "
                f"({new_size} bytes)"
            )
        else:
            print(
                f"  ❌ {new_path.name[:40]}... "
                f"크기 불일치"
            )
            return False

    print("\n✅ 모든 검증 통과")
    return True


def main():
    """메인 실행 함수"""
    print("🔄 문서 파일 마이그레이션 시작")
    print("=" * 60)

    # 디렉토리 설정
    project_root = Path(__file__).parent.parent
    lessonplan_dir = project_root / "data" / "lessonplan"

    # 디렉토리 생성
    print("\n1️⃣  디렉토리 준비 중...")
    ensure_directory(lessonplan_dir)
    print(f"✅ 디렉토리: {lessonplan_dir}")

    # DB 세션 생성
    db_session = create_db_session()

    try:
        # 문서 파일 마이그레이션
        print("\n2️⃣  문서 파일 복사 중...")
        success, fail, file_mapping = migrate_document_files(
            db_session,
            lessonplan_dir
        )
        print(f"✅ 성공: {success}개")
        if fail > 0:
            print(f"❌ 실패: {fail}개")

        # 검증
        print("\n3️⃣  결과 검증 중...")
        if verify_migration(lessonplan_dir, file_mapping):
            print("\n🎉 마이그레이션 성공!")
            print(
                "\n옴니시아의 뜻에 따라 "
                "데이터가 새로운 저장소에 안착했습니다."
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
