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
        """보고서 템플릿에서 사용된 모든 이모지/픽토그램/결합 문자를 제거한다.
        키캡 시퀀스(1️⃣)의 결합 문자(️⃣) 는 제거되고 숫자(1) 는 보존된다."""
        text = "📑 1️⃣ 📊 💡 🔎 ✅ 🔧 🚀 📝 ✨ ⚡️ 📚 🔍 📌 📏 📂 🚨 ✍️ ❌"
        result = strip_emojis(text)
        assert "📑" not in result
        assert "📊" not in result
        assert "✅" not in result
        assert "🚨" not in result
        # 키캡 결합 문자는 제거됨
        assert "️⃣" not in result
        assert "⃣" not in result
        # 키캡 숫자(1) 외의 텍스트 토큰은 모두 제거되어야 함
        assert result.replace("1", "").strip() == ""

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
        """키캡 시퀀스(1️⃣, 2️⃣ 등)에서 결합 문자만 제거하고 숫자는 보존한다.
        '## 1️⃣ 교육과정' → '## 1 교육과정' (숫자 1 보존)."""
        text = "## 1️⃣ 교육과정"
        result = strip_emojis(text)
        # 키캡 숫자(1) 보존 + 헤더 마커 보존
        assert "## 1 교육과정" in result
        # 결합 문자는 제거
        assert "⃣" not in result  # COMBINING ENCLOSING KEYCAP
        assert "️⃣" not in result  # variation selector + keycap

    def test_preserves_leading_indentation(self):
        """줄 첫머리 들여쓰기를 보존한다 (nested 마크다운 목록 보호)."""
        text = "1. **제안**\n   - 세부 항목\n   - 또 다른 항목"
        result = strip_emojis(text)
        # 들여쓰기 3칸이 그대로 유지되어야 함
        assert "   - 세부 항목" in result
        assert "   - 또 다른 항목" in result

    def test_preserves_indentation_with_emoji_removal(self):
        """들여쓰기 + 본문에 이모지가 섞여도, 들여쓰기는 보존하고 본문 이모지만 제거한다."""
        text = "1. **제안**\n   - 🚀 빠른 실행\n   - ✨ 결과 공유"
        result = strip_emojis(text)
        # 들여쓰기 3칸 보존
        assert "\n   - 빠른 실행" in result
        assert "\n   - 결과 공유" in result
        # 이모지 제거
        assert "🚀" not in result
        assert "✨" not in result

    def test_preserves_bold_marker_after_emoji_at_start(self):
        """이모지가 굵은 글씨 마커 시작 직후에 있으면, 제거 후 잔여 공백을 흡수해 ** 형식이 유지된다."""
        text = "**💡 분석 내용**"
        result = strip_emojis(text)
        # CommonMark 에서 ** + 공백은 유효한 strong-emphasis opener 가 아니므로,
        # 잔여 공백을 흡수해 **content** 형식으로 유지해야 함
        assert result == "**분석 내용**"

    def test_preserves_bold_marker_after_emoji_at_end(self):
        """이모지가 굵은 글씨 마커 종료 직전에 있으면, 제거 후 잔여 공백을 흡수해 ** 형식이 유지된다."""
        text = "**강점 ✅**"
        result = strip_emojis(text)
        assert result == "**강점**"

    def test_preserves_multiple_bold_labels_with_emojis(self):
        """여러 굵은 글씨 라벨에 이모지가 섞여 있어도 각 라벨이 올바르게 보존된다."""
        text = "**💡 분석 내용**\n**✅ 강점**\n**🔧 개선점**"
        result = strip_emojis(text)
        assert "**분석 내용**" in result
        assert "**강점**" in result
        assert "**개선점**" in result
        # 잘못된 형식(** + 공백) 부재
        assert "** " not in result

    def test_does_not_collapse_internal_spaces_in_bold(self):
        """굵은 글씨 마커 내부의 일반 공백(이모지 인접 아님) 은 보존한다."""
        text = "**foo bar baz**"
        result = strip_emojis(text)
        # 내부 공백은 그대로
        assert result == "**foo bar baz**"

    def test_preserves_bracketed_bold_after_emoji_at_start(self):
        """대괄호로 시작하는 굵은 헤딩(`**[제안]**`)에서 이모지 제거 후 ** 형식 유지."""
        text = "**🚀 [제안 1 제목]**"
        result = strip_emojis(text)
        assert result == "**[제안 1 제목]**"

    def test_preserves_bracketed_bold_after_emoji_at_end(self):
        """대괄호로 끝나는 굵은 헤딩에서 이모지 제거 후 ** 형식 유지."""
        text = "**[제안 1 제목] 🚀**"
        result = strip_emojis(text)
        assert result == "**[제안 1 제목]**"

    def test_preserves_parenthesized_bold_after_emoji(self):
        """괄호로 시작하는 굵은 헤딩에서 이모지 제거 후 ** 형식 유지."""
        text = "**🔧 (개선 사항)**"
        result = strip_emojis(text)
        assert result == "**(개선 사항)**"

    def test_does_not_collapse_blockquote_bold_marker(self):
        """블록인용(`>`) 과 굵은 마커(`**`) 사이 단일 공백은 보존되어 마크다운이 깨지지 않음."""
        text = "> **분석 내용**"
        result = strip_emojis(text)
        # `> **분석**` 형식은 단일 공백 그대로 유지되어야 함 (>** 로 압축되면 안 됨)
        assert result == "> **분석 내용**"

    def test_collapses_double_padding_in_blockquote_after_emoji_removal(self):
        """블록인용 안의 굵은 헤딩에서도 이모지 제거 후 ** 인접 공백은 흡수된다."""
        text = "> **🚀 분석**"
        result = strip_emojis(text)
        # `> ** 분석**` → `> **분석**`
        assert result == "> **분석**"

    def test_does_not_collapse_space_between_dash_and_bold(self):
        """리스트 마커('- ') 와 굵은 글씨 시작('**') 사이의 정상 공백은 보존."""
        text = "- **항목**"
        result = strip_emojis(text)
        assert result == "- **항목**"

    def test_does_not_collapse_space_between_numbered_list_and_bold(self):
        """번호 매김 리스트('1. ') 와 굵은 글씨 시작('**') 사이 공백 보존."""
        text = "1. **[비계 설정의 구체화]**"
        result = strip_emojis(text)
        assert result == "1. **[비계 설정의 구체화]**"

    def test_does_not_collapse_space_in_blockquote_list_with_bold(self):
        """블록인용 안의 리스트 마커와 굵은 글씨 사이 공백 보존."""
        text = "> - **분석 일시**: 2024-05-23 15:30"
        result = strip_emojis(text)
        assert result == "> - **분석 일시**: 2024-05-23 15:30"

    def test_does_not_collapse_space_around_bold_in_text(self):
        """일반 본문에서 굵은 글씨 앞뒤의 단일 공백 보존."""
        text = "이것은 **중요한** 메시지입니다"
        result = strip_emojis(text)
        assert result == "이것은 **중요한** 메시지입니다"

    def test_normalizes_bold_padding_after_emoji_at_both_ends(self):
        """굵은 글씨 양 끝에 이모지가 있을 때 제거 후 ** 형식 유지."""
        text = "**🚀 word ✨**"
        result = strip_emojis(text)
        assert result == "**word**"

    def test_normalizes_bold_with_nested_italics_after_emoji_removal(self):
        """굵은 글씨 콘텐츠 안에 단일 별표(이탤릭 마커)가 있어도 잔여 공백 정리됨."""
        text = "**🚀 foo *bar* baz**"
        result = strip_emojis(text)
        # 이모지 제거 후 잔여 공백이 흡수되어 ** 형식 유지
        assert result == "**foo *bar* baz**"

    def test_normalizes_bold_with_single_asterisk_content(self):
        """굵은 글씨 콘텐츠 안에 단일 별표(예: A*) 가 있어도 잔여 공백 정리됨."""
        text = "**A* search ✅**"
        result = strip_emojis(text)
        assert result == "**A* search**"

    def test_preserves_bold_with_nested_italics_unchanged(self):
        """이모지가 없는 굵은 글씨 + 중첩 이탤릭은 변동 없음."""
        text = "**foo *bar* baz**"
        result = strip_emojis(text)
        assert result == "**foo *bar* baz**"

    def test_handles_two_adjacent_bold_spans_with_text_between(self):
        """인접한 두 굵은 글씨 사이의 텍스트 보존."""
        text = "**foo**bar**baz**"
        result = strip_emojis(text)
        assert result == "**foo**bar**baz**"

    def test_handles_two_adjacent_bold_spans_with_space_between(self):
        """인접한 두 굵은 글씨 사이의 단일 공백 보존."""
        text = "**foo** **bar**"
        result = strip_emojis(text)
        assert result == "**foo** **bar**"
