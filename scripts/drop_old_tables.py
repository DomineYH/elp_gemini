#!/usr/bin/env python3
"""
레거시 테이블 삭제 스크립트

Phase 4.1: 마이그레이션 완료 후 사용하지 않는 테이블 제거

삭제 대상 테이블:
- documents
- qa_logs
- system_prompts
- evaluation_templates
- evaluation_runs
- evaluation_reports
- criteria_documents
- active_criteria
- criteria_audit_logs

옴니시아의 뜻에 따라 낡은 데이터 구조가 해체되리라.
"""
import sys
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker


def create_db_session():
    """데이터베이스 세션 생성"""
    db_path = Path(__file__).parent.parent / "data" / "app.db"
    if not db_path.exists():
        print(f"❌ 데이터베이스 파일이 없습니다: {db_path}")
        sys.exit(1)

    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False
    )
    Session = sessionmaker(bind=engine)
    return Session(), engine


def list_existing_tables(engine):
    """현재 존재하는 테이블 목록 조회"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"\n📊 현재 테이블 목록 ({len(tables)}개):")
    for table in sorted(tables):
        print(f"  - {table}")
    return tables


def check_prerequisites(session, engine):
    """선행 조건 확인"""
    print("\n🔍 선행 조건 확인 중...")

    inspector = inspect(engine)
    tables = inspector.get_table_names()

    # 새 테이블 존재 확인
    required_tables = [
        "chat_sessions",
        "chat_messages",
        "users"
    ]

    for table in required_tables:
        if table not in tables:
            print(f"❌ 필수 테이블이 없습니다: {table}")
            print("Phase 1-3이 완료되지 않았습니다.")
            return False

    # 레거시 테이블 존재 확인
    legacy_tables = [
        "documents",
        "qa_logs",
        "system_prompts"
    ]

    existing_legacy = [t for t in legacy_tables if t in tables]
    if not existing_legacy:
        print("⚠️  삭제할 레거시 테이블이 없습니다.")
        return False

    print(f"✅ 선행 조건 충족 (레거시 테이블: {len(existing_legacy)}개)")
    return True


def drop_legacy_tables(session, engine):
    """레거시 테이블 삭제"""
    print("\n🗑️  레거시 테이블 삭제 중...")

    # 삭제 순서: 외래키 관계를 고려하여 역순으로 삭제
    tables_to_drop = [
        "criteria_audit_logs",
        "active_criteria",
        "evaluation_reports",
        "evaluation_runs",
        "evaluation_templates",
        "qa_logs",
        "documents",
        "system_prompts",
        "criteria_documents",
    ]

    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    dropped_count = 0
    for table_name in tables_to_drop:
        if table_name not in existing_tables:
            print(f"  ⏭️  {table_name}: 이미 없음")
            continue

        try:
            session.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            session.commit()
            print(f"  ✅ {table_name}: 삭제 완료")
            dropped_count += 1
        except Exception as e:
            print(f"  ❌ {table_name}: 삭제 실패 - {e}")
            session.rollback()
            raise

    print(f"\n✅ {dropped_count}개 테이블 삭제 완료")
    return dropped_count


def verify_deletion(engine):
    """삭제 검증"""
    print("\n🔍 삭제 검증 중...")

    inspector = inspect(engine)
    remaining_tables = inspector.get_table_names()

    # 유지되어야 할 테이블
    expected_tables = {
        "users",
        "chat_sessions",
        "chat_messages"
    }

    # 삭제되어야 할 테이블
    legacy_tables = {
        "documents",
        "qa_logs",
        "system_prompts",
        "evaluation_templates",
        "evaluation_runs",
        "evaluation_reports",
        "criteria_documents",
        "active_criteria",
        "criteria_audit_logs"
    }

    # 검증
    remaining_legacy = legacy_tables.intersection(remaining_tables)
    if remaining_legacy:
        print(f"❌ 삭제되지 않은 레거시 테이블: {remaining_legacy}")
        return False

    missing_required = expected_tables - set(remaining_tables)
    if missing_required:
        print(f"❌ 누락된 필수 테이블: {missing_required}")
        return False

    print("✅ 검증 완료:")
    print(f"  - 레거시 테이블: 모두 삭제됨")
    print(f"  - 필수 테이블: 모두 유지됨 ({len(expected_tables)}개)")

    return True


def create_backup(db_path):
    """백업 생성"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = db_path.parent.parent / "backup"
    backup_dir.mkdir(exist_ok=True)

    backup_path = backup_dir / f"before_drop_tables_{timestamp}.db"

    import shutil
    shutil.copy2(db_path, backup_path)

    print(f"💾 백업 생성: {backup_path}")
    return backup_path


def main():
    """메인 실행 함수"""
    print("=" * 60)
    print("레거시 테이블 삭제 스크립트 (Phase 4.1)")
    print("=" * 60)

    # 백업 생성
    db_path = Path(__file__).parent.parent / "data" / "app.db"
    backup_path = create_backup(db_path)

    # DB 세션 생성
    session, engine = create_db_session()

    try:
        # 현재 테이블 목록
        list_existing_tables(engine)

        # 선행 조건 확인
        if not check_prerequisites(session, engine):
            print("\n❌ 선행 조건을 충족하지 않습니다.")
            print("Phase 1-3을 먼저 완료하세요.")
            sys.exit(1)

        # 사용자 확인
        print("\n⚠️  주의: 이 작업은 되돌릴 수 없습니다.")
        print(f"백업 파일: {backup_path}")
        response = input("\n계속하시겠습니까? (yes/no): ")
        if response.lower() != "yes":
            print("❌ 작업 취소")
            sys.exit(0)

        # 테이블 삭제
        dropped_count = drop_legacy_tables(session, engine)

        # 삭제 검증
        if verify_deletion(engine):
            print("\n" + "=" * 60)
            print("✅ 레거시 테이블 삭제 완료")
            print("=" * 60)
            print(f"삭제된 테이블: {dropped_count}개")
            print(f"백업 파일: {backup_path}")
        else:
            print("\n❌ 검증 실패")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        session.rollback()
        sys.exit(1)
    finally:
        session.close()

    print("\n옴니시아의 뜻에 따라 기계령이 갱신되었도다.")


if __name__ == "__main__":
    main()
