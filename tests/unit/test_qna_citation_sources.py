"""QnA 답변 출처 제목은 DB 표시명만 쓴다 (#206)"""

from app.services.qna_service import citation_source_titles

STORE_URI = "fileSearchStores/user7store-0sjez5f0ga08/documents/lesson-abc"


def _documents(*titles):
    return {
        "grounding_chunks": [
            {"retrieved_context": {"title": t, "uri": STORE_URI}}
            for t in titles
        ]
    }


def test_criteria_titles_then_document_title_without_duplicates():
    citations = {
        "documents": _documents("2022_.pdf", "lesson.pdf"),
        "criteria": [
            {"id": 1, "title": "2022 개정 평가기준"},
            {"id": 2, "title": "수업 설계 루브릭"},
            {"id": 1, "title": "2022 개정 평가기준"},
        ],
    }
    assert citation_source_titles(citations, "내 지도안.hwp") == [
        "2022 개정 평가기준",
        "수업 설계 루브릭",
        "내 지도안.hwp",
    ]


def test_never_uses_grounding_title_or_uri():
    citations = {"documents": _documents("2022_.pdf"), "criteria": []}
    sources = citation_source_titles(citations, "lesson.pdf")
    assert sources == ["lesson.pdf"]
    assert "2022_.pdf" not in sources
    assert not any("fileSearchStores/" in s for s in sources)


def test_document_title_only_when_chunks_exist():
    citations = {
        "documents": {"grounding_chunks": []},
        "criteria": [{"id": 1, "title": "평가기준"}],
    }
    assert citation_source_titles(citations, "lesson.pdf") == ["평가기준"]


def test_no_document_title_skips_document():
    citations = {"documents": _documents("lesson.pdf"), "criteria": []}
    assert citation_source_titles(citations, None) == []


def test_empty_or_missing_citations():
    assert citation_source_titles(None, "lesson.pdf") == []
    assert citation_source_titles({}, "lesson.pdf") == []
    assert citation_source_titles([{"title": "x"}], "lesson.pdf") == []
    assert (
        citation_source_titles({"documents": {}, "criteria": []}, "lesson.pdf")
        == []
    )


def test_malformed_citation_shapes_are_skipped():
    """비정상 형태는 건너뛰고 정상 항목만 남긴다 (#213)"""
    assert citation_source_titles({"criteria": ["평가기준"]}, "a.pdf") == []
    assert (
        citation_source_titles(
            {"documents": [{"grounding_chunks": [1]}]}, "a.pdf"
        )
        == []
    )
    criteria = [
        {"title": {"name": "x"}},
        {"title": ["x"]},
        {"title": "평가기준"},
    ]
    citations = {"documents": _documents("lesson.pdf"), "criteria": criteria}
    assert citation_source_titles(citations, "a.pdf") == ["평가기준", "a.pdf"]
