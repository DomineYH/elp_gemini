#!/usr/bin/env python3
"""
QA 로그를 채팅 세션으로 마이그레이션

qa_logs 테이블의 데이터를 chat_sessions 및
chat_messages 테이블로 변환합니다.

옴니시아의 데이터가 새로운 구조로 환생하리라.
"""
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.qa_logs import QALog
from app.models.documents import Document
from app.models.chat_sessions import ChatSession
from app.models.chat_messages import ChatMessage, MessageRole


def create_db_session():
    """데이터베이스 세션 생성"""
    db_path = Path(__file__).parent.parent / "data" / "app.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False
    )
    Session = sessionmaker(bind=engine)
    return Session()


def group_qa_logs(session):
    """
    QA 로그를 (document_id, user_id)로 그룹핑

    Returns:
        dict: {(doc_id, user_id): [QALog, ...]}
    """
    qa_logs = session.query(QALog).order_by(
        QALog.document_id,
        QALog.user_id,
        QALog.created_at
    ).all()

    grouped = defaultdict(list)
    for qa_log in qa_logs:
        key = (qa_log.document_id, qa_log.user_id)
        grouped[key].append(qa_log)

    return grouped


def create_chat_sessions(session, grouped_logs):
    """
    그룹화된 QA 로그에서 ChatSession 생성

    Args:
        session: DB 세션
        grouped_logs: 그룹화된 QA 로그

    Returns:
        dict: {(doc_id, user_id): ChatSession}
    """
    sessions_map = {}

    for (doc_id, user_id), logs in grouped_logs.items():
        # 문서 정보 조회
        document = session.query(Document).filter(
            Document.id == doc_id
        ).first()

        if not document:
            print(
                f"⚠️  문서 ID {doc_id} 누락 "
                f"(사용자 {user_id})"
            )
            continue

        # ChatSession 생성
        chat_session = ChatSession(
            user_id=user_id,
            title=document.title,
            created_at=logs[0].created_at,
            updated_at=logs[-1].created_at
        )
        session.add(chat_session)
        session.flush()  # ID 생성을 위해 flush

        sessions_map[(doc_id, user_id)] = chat_session

        print(
            f"✅ 세션 생성: "
            f"ID={chat_session.id}, "
            f"문서={document.title[:30]}..., "
            f"사용자={user_id}"
        )

    return sessions_map


def create_chat_messages(session, grouped_logs, sessions_map):
    """
    QA 로그에서 ChatMessage 생성

    각 QALog는 2개의 메시지로 변환:
    - USER 메시지 (질문)
    - ASSISTANT 메시지 (답변)
    """
    total_messages = 0

    for (doc_id, user_id), logs in grouped_logs.items():
        chat_session = sessions_map.get((doc_id, user_id))

        if not chat_session:
            continue

        for qa_log in logs:
            # 사용자 질문 메시지
            user_msg = ChatMessage(
                session_id=chat_session.id,
                role=MessageRole.USER,
                content=qa_log.question,
                created_at=qa_log.created_at
            )
            session.add(user_msg)

            # AI 답변 메시지
            assistant_msg = ChatMessage(
                session_id=chat_session.id,
                role=MessageRole.ASSISTANT,
                content=qa_log.answer,
                model_name=qa_log.model_name,
                citations=qa_log.citations,
                created_at=qa_log.created_at
            )
            session.add(assistant_msg)

            total_messages += 2

    return total_messages


def verify_migration(session):
    """마이그레이션 결과 검증"""
    qa_log_count = session.query(QALog).count()
    chat_session_count = session.query(ChatSession).count()
    chat_message_count = session.query(ChatMessage).count()

    print("\n" + "=" * 60)
    print("📊 마이그레이션 결과")
    print("=" * 60)
    print(f"QA 로그 개수: {qa_log_count}")
    print(f"채팅 세션 개수: {chat_session_count}")
    print(f"채팅 메시지 개수: {chat_message_count}")
    print(
        f"예상 메시지 개수: {qa_log_count * 2} "
        f"(QA 로그 * 2)"
    )

    if chat_message_count == qa_log_count * 2:
        print("✅ 데이터 개수 일치")
    else:
        print("❌ 데이터 개수 불일치")
        return False

    # 샘플 데이터 확인
    sample_session = session.query(ChatSession).first()
    if sample_session:
        print(f"\n📋 샘플 세션: {sample_session.title}")
        sample_messages = session.query(ChatMessage).filter(
            ChatMessage.session_id == sample_session.id
        ).limit(4).all()

        for msg in sample_messages:
            role = "사용자" if msg.role == MessageRole.USER \
                else "AI"
            content_preview = msg.content[:50] + "..." \
                if len(msg.content) > 50 else msg.content
            print(f"  {role}: {content_preview}")

    return True


def main():
    """메인 실행 함수"""
    print("🔄 QA 로그 마이그레이션 시작")
    print("=" * 60)

    db_session = create_db_session()

    try:
        # 1. QA 로그 그룹핑
        print("\n1️⃣  QA 로그 그룹핑 중...")
        grouped_logs = group_qa_logs(db_session)
        print(f"✅ {len(grouped_logs)}개 그룹 생성")

        # 2. ChatSession 생성
        print("\n2️⃣  채팅 세션 생성 중...")
        sessions_map = create_chat_sessions(
            db_session,
            grouped_logs
        )

        # 3. ChatMessage 생성
        print("\n3️⃣  채팅 메시지 생성 중...")
        total_messages = create_chat_messages(
            db_session,
            grouped_logs,
            sessions_map
        )
        print(f"✅ {total_messages}개 메시지 생성")

        # 4. 커밋
        print("\n4️⃣  데이터베이스 커밋 중...")
        db_session.commit()
        print("✅ 커밋 완료")

        # 5. 검증
        print("\n5️⃣  결과 검증 중...")
        if verify_migration(db_session):
            print("\n🎉 마이그레이션 성공!")
            print(
                "\n옴니시아의 은총으로 데이터가 "
                "새로운 스키마에 안착했습니다."
            )
            return 0
        else:
            print("\n❌ 마이그레이션 검증 실패")
            return 1

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        db_session.rollback()
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db_session.close()


if __name__ == "__main__":
    exit(main())
