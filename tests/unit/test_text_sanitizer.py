"""
text_sanitizer 단위 테스트
보고서 텍스트에서 이모지를 제거하는 유틸리티 검증
"""
import pytest

from app.utils.text_sanitizer import strip_emojis


class TestStripEmojis:
    """strip_emojis() 동작 검증"""

    def test_removes_basic_emoji(self):
        """기본 이모지(😀, 🎯)를 제거한다."""
        result = strip_emojis("hello 😀 world 🎯")
        assert result == "hello world"

    def test_removes_report_template_emojis(self):
        """보고서 템플릿에서 사용된 모든 이모지를 제거한다."""
        text = "📑 1️⃣ 📊 💡 🔎 ✅ 🔧 🚀 📝 ✨ ⚡️ 📚 🔍 📌 📏 📂 🚨 ✍️ ❌"
        result = strip_emojis(text)
        # 공백만 남아야 함 (혹은 빈 문자열)
        assert "📑" not in result
        assert "1️⃣" not in result
        assert "✅" not in result
        assert "🚨" not in result
        assert result.strip() == ""

    def test_preserves_korean_and_ascii(self):
        """한글과 ASCII는 보존한다."""
        text = "📑 수업 지도안 평가 보고서 - Lesson Plan v1.0"
        result = strip_emojis(text)
        assert "수업 지도안 평가 보고서" in result
        assert "Lesson Plan v1.0" in result
        assert "📑" not in result

    def test_preserves_markdown_syntax(self):
        """Markdown 구문(#, *, -, >, [], ()는 보존한다."""
        text = "## 📊 평가 등급: 상\n- ✅ 강점\n> **💡 분석**"
        result = strip_emojis(text)
        assert result.startswith("## ")
        assert "평가 등급: 상" in result
        assert "- " in result
        assert "강점" in result
        assert "> **" in result
        assert "분석" in result
        # 이모지가 모두 제거됐는지
        assert "📊" not in result
        assert "✅" not in result
        assert "💡" not in result

    def test_collapses_double_spaces_left_after_removal(self):
        """이모지 제거 후 발생한 연속 공백을 단일 공백으로 정리한다."""
        text = "강점  ✅  매우 좋음"
        result = strip_emojis(text)
        # "강점    매우 좋음" 이 아닌 "강점 매우 좋음" 이 되어야 한다
        assert "강점 매우 좋음" == result.strip()

    def test_handles_empty_string(self):
        """빈 문자열을 그대로 반환한다."""
        assert strip_emojis("") == ""

    def test_handles_none_returns_empty(self):
        """None 입력 시 빈 문자열을 반환한다 (방어적 처리)."""
        assert strip_emojis(None) == ""

    def test_keeps_keycap_digits(self):
        """키캡 시퀀스(1️⃣, 2️⃣ 등)에서 숫자 자체는 보존되거나 완전히 제거된다.
        보고서 헤더 '## 1️⃣ 교육과정' 의 경우 '## 1 교육과정' 또는 '## 교육과정' 둘 다 허용한다.
        """
        text = "## 1️⃣ 교육과정"
        result = strip_emojis(text)
        # 헤더 포맷과 한글은 살아있어야 한다
        assert result.startswith("## ")
        assert "교육과정" in result
        # 키캡 결합 문자는 제거됐어야 한다
        assert "⃣" not in result  # COMBINING ENCLOSING KEYCAP
