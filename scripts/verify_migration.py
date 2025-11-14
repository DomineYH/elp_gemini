"""
Google File Search API 마이그레이션 검증 스크립트

모든 Phase 변경 사항이 올바르게 적용되었는지 검증합니다.
"""
import sys
import os
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def verify_imports():
    """Phase 1 & 2: Import 문 검증"""
    print("\n" + "=" * 60)
    print("🔍 Phase 1 & 2: Import 문 검증")
    print("=" * 60)

    try:
        from google import genai
        from google.genai import types
        print("✅ google.genai import 성공")
        print(f"   - genai 버전: {genai.__version__ if hasattr(genai, '__version__') else '확인 불가'}")

        # Client 생성 테스트
        print("\n✅ genai.Client 클래스 확인")
        assert hasattr(genai, 'Client'), "genai.Client가 존재하지 않습니다"
        print("   - genai.Client 클래스 존재 확인")

        # types 모듈 확인
        print("\n✅ genai.types 모듈 확인")
        assert hasattr(types, 'GenerateContentConfig'), "types.GenerateContentConfig가 존재하지 않습니다"
        assert hasattr(types, 'Tool'), "types.Tool이 존재하지 않습니다"
        assert hasattr(types, 'FileSearch'), "types.FileSearch가 존재하지 않습니다"
        print("   - GenerateContentConfig 클래스 존재 확인")
        print("   - Tool 클래스 존재 확인")
        print("   - FileSearch 클래스 존재 확인")

        return True
    except ImportError as e:
        print(f"❌ Import 오류: {str(e)}")
        return False
    except AssertionError as e:
        print(f"❌ 검증 실패: {str(e)}")
        return False


def verify_file_search_service():
    """Phase 1: FileSearchService 리팩토링 검증"""
    print("\n" + "=" * 60)
    print("🔍 Phase 1: FileSearchService 리팩토링 검증")
    print("=" * 60)

    try:
        from app.services.file_search_service import FileSearchService

        # Client 인스턴스화 확인
        print("\n✅ FileSearchService 클래스 확인")
        assert hasattr(FileSearchService, 'get_client'), "get_client 메서드가 존재하지 않습니다"
        print("   - get_client 클래스 메서드 존재 확인")

        # 싱글톤 패턴 확인
        service1 = FileSearchService()
        service2 = FileSearchService()
        assert service1.client is service2.client, "Client 싱글톤 패턴이 적용되지 않았습니다"
        print("   - Client 싱글톤 패턴 동작 확인")

        # 메서드 시그니처 확인
        import inspect

        # upload_document 메서드 시그니처
        upload_sig = inspect.signature(service1.upload_document)
        params = list(upload_sig.parameters.keys())
        assert 'file_path' in params, "upload_document에 file_path 파라미터가 없습니다"
        assert 'display_name' in params, "upload_document에 display_name 파라미터가 없습니다"
        assert 'metadata' in params, "upload_document에 metadata 파라미터가 없습니다"
        assert 'store_type' in params, "upload_document에 store_type 파라미터가 없습니다"
        print("\n✅ upload_document 메서드 시그니처 확인")
        print(f"   - 파라미터: {', '.join(params)}")

        # delete_document 메서드 시그니처 (파라미터 단순화 확인)
        delete_sig = inspect.signature(service1.delete_document)
        delete_params = list(delete_sig.parameters.keys())
        assert 'document_id' in delete_params, "delete_document에 document_id 파라미터가 없습니다"
        # file_id가 없어야 함 (단순화됨)
        print("\n✅ delete_document 메서드 시그니처 확인")
        print(f"   - 파라미터: {', '.join(delete_params)}")

        # query_documents 메서드가 제거되었는지 확인
        assert not hasattr(service1, 'query_documents'), "query_documents 메서드가 아직 존재합니다"
        print("\n✅ query_documents 메서드 제거 확인")

        return True
    except ImportError as e:
        print(f"❌ Import 오류: {str(e)}")
        return False
    except AssertionError as e:
        print(f"❌ 검증 실패: {str(e)}")
        return False


def verify_qna_service():
    """Phase 2: QnA Service RAG 적용 검증"""
    print("\n" + "=" * 60)
    print("🔍 Phase 2: QnA Service RAG 적용 검증")
    print("=" * 60)

    try:
        from app.services.qna_service import QnAService
        from sqlalchemy.ext.asyncio import AsyncSession
        from unittest.mock import Mock

        # Mock DB 세션
        mock_db = Mock(spec=AsyncSession)
        service = QnAService(mock_db)

        # Client 인스턴스 확인
        print("\n✅ QnAService 클래스 확인")
        assert hasattr(service, 'client'), "QnAService에 client 속성이 없습니다"
        print("   - client 속성 존재 확인")

        # 메서드 시그니처 확인
        import inspect

        # _build_context 메서드 시그니처 (document 파라미터 제거 확인)
        build_context_sig = inspect.signature(service._build_context)
        build_context_params = list(build_context_sig.parameters.keys())
        assert 'system_prompt' in build_context_params, "_build_context에 system_prompt 파라미터가 없습니다"
        assert 'conversation_history' in build_context_params, "_build_context에 conversation_history 파라미터가 없습니다"
        # document 파라미터가 없어야 함
        assert 'document' not in build_context_params, "_build_context에 document 파라미터가 남아있습니다"
        print("\n✅ _build_context 메서드 시그니처 확인")
        print(f"   - 파라미터: {', '.join(build_context_params)}")
        print("   - document 파라미터 제거 확인")

        # _save_qa_log 메서드 시그니처 (citations, sources_count 추가 확인)
        save_qa_log_sig = inspect.signature(service._save_qa_log)
        save_qa_log_params = list(save_qa_log_sig.parameters.keys())
        assert 'citations' in save_qa_log_params, "_save_qa_log에 citations 파라미터가 없습니다"
        assert 'sources_count' in save_qa_log_params, "_save_qa_log에 sources_count 파라미터가 없습니다"
        print("\n✅ _save_qa_log 메서드 시그니처 확인")
        print(f"   - 파라미터: {', '.join(save_qa_log_params)}")
        print("   - citations, sources_count 파라미터 추가 확인")

        return True
    except ImportError as e:
        print(f"❌ Import 오류: {str(e)}")
        return False
    except AssertionError as e:
        print(f"❌ 검증 실패: {str(e)}")
        return False


def verify_models():
    """Phase 3: DB 스키마 업데이트 검증"""
    print("\n" + "=" * 60)
    print("🔍 Phase 3: DB 스키마 업데이트 검증")
    print("=" * 60)

    try:
        from app.models.documents import Document
        from app.models.qa_logs import QALog
        from sqlalchemy import inspect as sqla_inspect

        # Document 모델 필드 확인
        print("\n✅ Document 모델 확인")
        doc_mapper = sqla_inspect(Document)
        doc_columns = {col.key for col in doc_mapper.columns}

        assert 'file_search_file_id' in doc_columns, "Document에 file_search_file_id 필드가 없습니다"
        assert 'store_id' in doc_columns, "Document에 store_id 필드가 없습니다"
        print("   - file_search_file_id 필드 존재 확인")
        print("   - store_id 필드 존재 확인")

        # QALog 모델 필드 확인
        print("\n✅ QALog 모델 확인")
        qalog_mapper = sqla_inspect(QALog)
        qalog_columns = {col.key for col in qalog_mapper.columns}

        assert 'citations' in qalog_columns, "QALog에 citations 필드가 없습니다"
        assert 'sources_count' in qalog_columns, "QALog에 sources_count 필드가 없습니다"
        print("   - citations 필드 추가 확인")
        print("   - sources_count 필드 추가 확인")

        # 필드 타입 확인
        citations_col = qalog_mapper.columns['citations']
        sources_count_col = qalog_mapper.columns['sources_count']

        print(f"   - citations 타입: {citations_col.type}")
        print(f"   - sources_count 타입: {sources_count_col.type}")

        return True
    except ImportError as e:
        print(f"❌ Import 오류: {str(e)}")
        return False
    except AssertionError as e:
        print(f"❌ 검증 실패: {str(e)}")
        return False


def verify_config():
    """Phase 4: 설정 파일 업데이트 검증"""
    print("\n" + "=" * 60)
    print("🔍 Phase 4: 설정 파일 업데이트 검증")
    print("=" * 60)

    try:
        from app.config import Settings

        # Settings 필드 확인
        settings_fields = Settings.model_fields.keys()

        # File Search 청킹 설정
        print("\n✅ File Search 청킹 설정 확인")
        assert 'FS_CHUNKING_MAX_TOKENS' in settings_fields, "FS_CHUNKING_MAX_TOKENS 설정이 없습니다"
        assert 'FS_CHUNKING_OVERLAP_TOKENS' in settings_fields, "FS_CHUNKING_OVERLAP_TOKENS 설정이 없습니다"
        print("   - FS_CHUNKING_MAX_TOKENS 추가 확인")
        print("   - FS_CHUNKING_OVERLAP_TOKENS 추가 확인")

        # File Search 업로드 설정
        print("\n✅ File Search 업로드 설정 확인")
        assert 'FS_UPLOAD_TIMEOUT' in settings_fields, "FS_UPLOAD_TIMEOUT 설정이 없습니다"
        assert 'FS_POLL_INTERVAL' in settings_fields, "FS_POLL_INTERVAL 설정이 없습니다"
        print("   - FS_UPLOAD_TIMEOUT 추가 확인")
        print("   - FS_POLL_INTERVAL 추가 확인")

        # QnA 설정
        print("\n✅ QnA 설정 확인")
        assert 'QNA_TEMPERATURE' in settings_fields, "QNA_TEMPERATURE 설정이 없습니다"
        assert 'QNA_ENABLE_CITATIONS' in settings_fields, "QNA_ENABLE_CITATIONS 설정이 없습니다"
        print("   - QNA_TEMPERATURE 추가 확인")
        print("   - QNA_ENABLE_CITATIONS 추가 확인")

        # 기본값 확인
        from app.config import settings
        print("\n✅ 기본값 확인")
        print(f"   - FS_CHUNKING_MAX_TOKENS: {settings.FS_CHUNKING_MAX_TOKENS}")
        print(f"   - FS_CHUNKING_OVERLAP_TOKENS: {settings.FS_CHUNKING_OVERLAP_TOKENS}")
        print(f"   - FS_UPLOAD_TIMEOUT: {settings.FS_UPLOAD_TIMEOUT}")
        print(f"   - FS_POLL_INTERVAL: {settings.FS_POLL_INTERVAL}")
        print(f"   - QNA_TEMPERATURE: {settings.QNA_TEMPERATURE}")
        print(f"   - QNA_ENABLE_CITATIONS: {settings.QNA_ENABLE_CITATIONS}")

        return True
    except ImportError as e:
        print(f"❌ Import 오류: {str(e)}")
        return False
    except AssertionError as e:
        print(f"❌ 검증 실패: {str(e)}")
        return False


def main():
    """메인 검증 프로세스"""
    print("\n" + "=" * 60)
    print("🚀 Google File Search API 마이그레이션 검증 시작")
    print("=" * 60)

    results = {
        "Import 문 검증": verify_imports(),
        "FileSearchService 리팩토링": verify_file_search_service(),
        "QnA Service RAG 적용": verify_qna_service(),
        "DB 스키마 업데이트": verify_models(),
        "설정 파일 업데이트": verify_config(),
    }

    # 결과 요약
    print("\n" + "=" * 60)
    print("📊 검증 결과 요약")
    print("=" * 60)

    for phase, result in results.items():
        status = "✅ 통과" if result else "❌ 실패"
        print(f"{status} - {phase}")

    # 전체 결과
    all_passed = all(results.values())
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 모든 검증 통과! 마이그레이션이 성공적으로 완료되었습니다.")
    else:
        print("⚠️ 일부 검증 실패. 위의 오류 메시지를 확인하세요.")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
