# 분석 보고서 이모지 제거 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수업 지도안 분석 보고서(Markdown 출력물)에서 모든 이모지를 제거하여 일관된 텍스트 전용 형식으로 출력되도록 한다.

**Architecture:** 이모지는 두 경로에서 유입된다. (1) `prompt/prompt.md`의 `lesson_analysis` 섹션이 LLM에게 이모지를 포함한 헤더 양식을 직접 지시함, (2) Gemini가 자체 판단으로 이모지를 추가하는 경우. 따라서 (a) 프롬프트 템플릿에서 모든 이모지를 제거하여 1차 입력을 차단하고, (b) `LessonPlanAnalysisService._post_process_report()`에 정규식 기반 이모지 제거 단계를 추가하여 모델이 임의로 이모지를 출력해도 저장 전에 제거되도록 한다. 또한 (c) 동일 후처리 로직이 단위 테스트로 회귀 보호된다.

**Tech Stack:** Python 3.x, FastAPI, Google Generative AI SDK (Gemini), pytest, asyncio. 정규식은 표준 `re` 모듈만 사용한다 (외부 의존성 추가 없음).

---

## File Structure

| File | 역할 | 변경 종류 |
|---|---|---|
| `prompt/prompt.md` | LLM 시스템 프롬프트 정의. `lesson_analysis` 섹션의 출력 형식 지시문에서 이모지 제거 | Modify |
| `app/services/lessonplan_analysis_service.py` | 분석 호출 및 후처리. 이모지 제거 유틸 추가 + 후처리 파이프라인에 연결 + 기존 정규식의 이모지 의존성 제거 | Modify |
| `app/utils/text_sanitizer.py` | (신규) 보고서 텍스트에서 이모지를 제거하는 순수 함수. 다른 보고서 경로에서도 재사용 가능 | Create |
| `tests/unit/test_text_sanitizer.py` | (신규) `strip_emojis()` 단위 테스트 | Create |
| `tests/unit/test_lessonplan_analysis_service.py` | 후처리에 이모지 제거가 적용되는지 회귀 테스트 추가 | Modify |
| `app/schemas/lessonplan_analysis.py` | OpenAPI 예시 문자열의 이모지 제거 | Modify |

> **참고:** `app/services/file_search_service.py`, `app/services/qna_service.py`, `app/services/lessonplan_analysis_service.py`의 `logger.info(f"✅ ...")` 등 **로그 메시지의 이모지는 본 plan의 범위가 아니다** (분석 보고서 출력물이 아닌 서버 로그). 또한 `app/templates/`의 UI 이모지(📚, 📋, 📄)는 **사용자 인터페이스 장식**이며 보고서 출력물이 아니므로 변경하지 않는다.

---

## Task 1: 이모지 제거 유틸리티 함수 추가

**Files:**
- Create: `app/utils/text_sanitizer.py`
- Test: `tests/unit/test_text_sanitizer.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_text_sanitizer.py` 생성:

```python
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `pytest tests/unit/test_text_sanitizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.utils.text_sanitizer'`

- [ ] **Step 3: `strip_emojis()` 구현**

`app/utils/text_sanitizer.py` 생성:

```python
"""
보고서 텍스트 살균 유틸리티

분석 보고서에서 이모지/픽토그램을 제거한다. LLM이 마크다운 헤더에 자체적으로
이모지를 추가하더라도 저장 전에 일관된 텍스트 전용 형식으로 정규화한다.
"""
import re
from typing import Optional


_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F700-\U0001F77F"  # alchemical
    "\U0001F780-\U0001F7FF"  # geometric shapes extended
    "\U0001F800-\U0001F8FF"  # supplemental arrows-c
    "\U0001F900-\U0001F9FF"  # supplemental symbols & pictographs
    "\U0001FA00-\U0001FA6F"  # chess / symbols
    "\U0001FA70-\U0001FAFF"  # symbols & pictographs extended-a
    "\U00002600-\U000026FF"  # miscellaneous symbols (☀, ⚡)
    "\U00002700-\U000027BF"  # dingbats (✅, ✨, ✍)
    "\U00002300-\U000023FF"  # technical (⏰, ⌛)
    "\U00002B00-\U00002BFF"  # arrows / stars
    "\U0001F000-\U0001F02F"  # mahjong
    "\U0001F100-\U0001F1FF"  # enclosed alphanumerics supplement
    "\U0001F200-\U0001F2FF"  # enclosed ideographic supplement
    "\U0000FE00-\U0000FE0F"  # variation selectors (e.g. emoji-style "⚡️"의 FE0F)
    "\U0000200D"             # zero-width joiner
    "\U000020E3"             # combining enclosing keycap (1️⃣ 의 결합 문자)
    "]+",
    flags=re.UNICODE,
)

_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_TRAILING_SPACE_BEFORE_NEWLINE = re.compile(r"[ \t]+\n")
_KEYCAP_DIGIT = re.compile(r"([0-9])️⃣")


def strip_emojis(text: Optional[str]) -> str:
    """
    이모지·픽토그램을 제거한 텍스트를 반환한다.

    - 키캡 시퀀스("1️⃣")의 경우 결합 문자만 제거하고 숫자는 보존한다.
    - 제거 후 발생한 연속 공백은 단일 공백으로 정리한다.
    - 줄 끝의 잔여 공백을 제거한다.
    - None 입력은 빈 문자열을 반환한다.
    """
    if not text:
        return ""

    # 키캡 시퀀스의 숫자만 보존
    text = _KEYCAP_DIGIT.sub(r"\1", text)
    # 그 외 이모지·픽토그램·VS·ZWJ 제거
    text = _EMOJI_PATTERN.sub("", text)
    # 잔여 공백 정리
    text = _MULTI_SPACE.sub(" ", text)
    text = _TRAILING_SPACE_BEFORE_NEWLINE.sub("\n", text)
    return text
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/test_text_sanitizer.py -v`
Expected: 모든 테스트 PASS (8개)

- [ ] **Step 5: Commit**

```bash
git add app/utils/text_sanitizer.py tests/unit/test_text_sanitizer.py
git commit -m "feat(utils): add strip_emojis text sanitizer for analysis reports"
```

---

## Task 2: 분석 서비스 후처리에 이모지 제거 통합

**Files:**
- Modify: `app/services/lessonplan_analysis_service.py:297-348` (`_post_process_report`)
- Modify: `app/services/lessonplan_analysis_service.py:312-314` (정규식 패턴 - 이모지 의존 제거)
- Test: `tests/unit/test_lessonplan_analysis_service.py`

- [ ] **Step 1: 실패하는 회귀 테스트 작성**

`tests/unit/test_lessonplan_analysis_service.py` 의 `TestLessonPlanAnalysisService` 클래스 끝에 다음 메서드를 추가한다:

```python
    def test_post_process_strips_emojis(self, service):
        """
        Gemini가 이모지를 포함한 보고서를 반환해도 후처리 단계에서 모두 제거된다.
        """
        raw = (
            "# 📑 수업 지도안 평가 보고서\n\n"
            "## 1️⃣ 교육과정 목표 및 성격과의 부합\n\n"
            "### 📊 평가 등급: 상\n\n"
            "**💡 분석 내용**\n본문\n\n"
            "**✅ 강점**\n- 좋음\n\n"
            "**🔧 개선점**\n- 보완\n"
        )

        processed = service._post_process_report(raw)

        # 보고서 본문에 어떤 이모지도 남아 있어서는 안 된다
        for emoji_char in ["📑", "1️⃣", "📊", "💡", "✅", "🔧", "🔎", "🚀",
                           "📝", "✨", "⚡️", "📚", "🔍", "📌", "📏", "📂"]:
            assert emoji_char not in processed, (
                f"이모지 '{emoji_char}' 가 후처리 후에도 남아있음"
            )

        # 헤더 구조와 한글 본문은 보존
        assert "수업 지도안 평가 보고서" in processed
        assert "교육과정 목표 및 성격과의 부합" in processed
        assert "평가 등급: 상" in processed
        assert "강점" in processed

    def test_post_process_handles_vector_search_section_without_emoji(
        self, service
    ):
        """
        '🔍 Vector Search 참고 자료' 헤더에서 이모지가 사라져도 후처리가 정상 동작한다.
        (LLM이 이모지 없이 헤더를 출력해도 기존 가독성 개선 로직이 작동해야 한다)
        """
        raw = (
            "## 종합 평가\n\n"
            "### Vector Search 참고 자료\n"
            "이것은 100자 이상의 비구조화된 평가기준 문장입니다. "
            "두 번째 문장입니다 추가 길이를 위해. "
            "세 번째 문장입니다 더 길게 만들기 위해서요.\n\n"
            "### File Search 참고 문서\n- 문서1\n"
        )

        processed = service._post_process_report(raw)

        # 가독성 개선이 동작했다면 '- ' 로 시작하는 목록이 생성된다
        assert "- " in processed
        # 이모지는 어차피 없지만, 출력에도 없어야 한다
        assert "🔍" not in processed
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `pytest tests/unit/test_lessonplan_analysis_service.py::TestLessonPlanAnalysisService::test_post_process_strips_emojis tests/unit/test_lessonplan_analysis_service.py::TestLessonPlanAnalysisService::test_post_process_handles_vector_search_section_without_emoji -v`
Expected: 두 테스트 모두 FAIL — 첫 번째는 이모지가 그대로 남아 AssertionError, 두 번째는 정규식이 `🔍` 를 요구하므로 가독성 변환이 동작하지 않아 `- ` 가 없음.

- [ ] **Step 3: `_post_process_report` 수정**

`app/services/lessonplan_analysis_service.py` 의 `_post_process_report` 메서드 전체를 다음으로 교체한다 (정규식의 `🔍` 의존을 제거하고, 마지막에 `strip_emojis()` 호출):

```python
    def _post_process_report(self, report: str) -> str:
        """
        보고서 후처리:
        1. 'Vector Search 참고 자료' 섹션이 비구조화된 긴 텍스트일 경우 목록으로 정리
        2. 본문 전체에서 이모지/픽토그램 제거 (LLM이 출력했더라도 일관된 텍스트 형식 유지)

        Args:
            report: 원본 Markdown 보고서

        Returns:
            후처리된 보고서
        """
        import re

        from app.utils.text_sanitizer import strip_emojis

        try:
            # 1) "Vector Search 참고 자료" 섹션 가독성 개선
            # 이모지 유무와 무관하게 매칭되도록 패턴에서 🔍 의존을 제거한다.
            pattern = (
                r'(###\s*(?:[^\n]*?)?Vector Search 참고 자료\s*\n)'
                r'(.*?)(\n###|\Z)'
            )
            match = re.search(pattern, report, flags=re.DOTALL)

            if match:
                header = match.group(1)
                content = match.group(2).strip()
                next_section = match.group(3)

                # 이미 구조화되어 있는지 확인 (목록/번호가 있으면 이미 구조화됨)
                already_structured = re.search(
                    r'^\s*[0-9]+\.|\s*-|\s*\*',
                    content,
                    re.MULTILINE,
                )
                if not already_structured and len(content) > 100:
                    sentences = re.split(r'(?<=[.!?])\s+', content)
                    sentences = [
                        s.strip() for s in sentences if len(s.strip()) > 20
                    ]
                    formatted = "\n".join([f"- {s}" for s in sentences[:8]])
                    new_section = f"{header}\n{formatted}\n{next_section}"
                    report = (
                        report[: match.start()]
                        + new_section
                        + report[match.end():]
                    )

            # 2) 본문 전체 이모지 제거 (마지막 단계)
            report = strip_emojis(report)

            return report

        except Exception as e:
            logger.warning(f"보고서 후처리 실패 (원본 반환): {e}")
            # 후처리 자체가 실패하더라도 최소한 이모지 제거는 시도한다
            try:
                from app.utils.text_sanitizer import strip_emojis
                return strip_emojis(report)
            except Exception:
                return report
```

- [ ] **Step 4: 새 회귀 테스트 통과 확인**

Run: `pytest tests/unit/test_lessonplan_analysis_service.py::TestLessonPlanAnalysisService::test_post_process_strips_emojis tests/unit/test_lessonplan_analysis_service.py::TestLessonPlanAnalysisService::test_post_process_handles_vector_search_section_without_emoji -v`
Expected: 두 테스트 모두 PASS.

- [ ] **Step 5: 분석 서비스 전체 단위 테스트 회귀 확인**

Run: `pytest tests/unit/test_lessonplan_analysis_service.py -v`
Expected: 기존 테스트 + 신규 2개 모두 PASS. 만약 기존 `test_extract_citations_*` 등이 깨지면 본 변경과 무관한 환경 이슈이므로 별도 조사.

- [ ] **Step 6: Commit**

```bash
git add app/services/lessonplan_analysis_service.py tests/unit/test_lessonplan_analysis_service.py
git commit -m "feat(analysis): strip emojis in lesson plan report post-processing"
```

---

## Task 3: 프롬프트 템플릿에서 이모지 제거

**Files:**
- Modify: `prompt/prompt.md` (lines 26, 65, 70, 80, 134, 144, 168, 192, 216, 240, 268, 273, 289, 304, 313, 315, 319, 331, 338 — `lesson_analysis` 섹션 중심)

**참고:** `qna` 섹션의 `🚨 CRITICAL INSTRUCTION`, `🔍 STEP 1`, `✍️ STEP 2`, `📊 STEP 3`, `✅`, `❌` 등은 **모델에 대한 내부 지시문**이며 사용자에게 보이는 보고서 출력물이 아니다. 그러나 일관성을 위해 **이번 작업에서는 `lesson_analysis` 섹션만** 수정하고, qna 섹션은 변경 범위에서 제외한다 (별도 plan으로 다룰 것). 이는 사용자 요구가 "분석 보고서"에 한정되어 있기 때문이다.

- [ ] **Step 1: lesson_analysis 출력 템플릿 헤더에서 이모지 제거**

`prompt/prompt.md` 의 134번 라인을 다음과 같이 수정한다:

```diff
- # 📑 수업 지도안 평가 보고서
+ # 수업 지도안 평가 보고서
```

- [ ] **Step 2: 5개 섹션 헤더의 키캡 숫자 제거**

다음 헤더들을 일반 번호로 변경한다 (각 1회씩 수정):

```diff
- ## 1️⃣ 교육과정 목표 및 성격과의 부합
+ ## 1. 교육과정 목표 및 성격과의 부합
```

```diff
- ## 2️⃣ 내용 체계 및 성취기준 달성
+ ## 2. 내용 체계 및 성취기준 달성
```

```diff
- ## 3️⃣ 교수·학습 방법의 적절성
+ ## 3. 교수·학습 방법의 적절성
```

```diff
- ## 4️⃣ 평가 방향과의 일치
+ ## 4. 평가 방향과의 일치
```

```diff
- ## 5️⃣ 개선 및 보완을 위한 제안
+ ## 5. 개선 및 보완을 위한 제안
```

- [ ] **Step 3: 5개 섹션 내부의 등급/분석/근거/강점/개선점 헤더에서 이모지 제거**

`replace_all`로 다음 5개의 패턴을 일괄 변경한다 (각 헤더는 5번씩 등장):

```diff
- ### 📊 평가 등급: [상/중/하]
+ ### 평가 등급: [상/중/하]
```

```diff
- **💡 분석 내용**
+ **분석 내용**
```

```diff
- **🔎 근거**
+ **근거**
```

```diff
- **✅ 강점**
+ **강점**
```

```diff
- **🔧 개선점**
+ **개선점**
```

- [ ] **Step 4: 5번 섹션과 종합 평가 섹션의 이모지 제거**

```diff
- **🚀 구체적 제안**
+ **구체적 제안**
```

```diff
- ## 📝 종합 평가
+ ## 종합 평가
```

```diff
- ### ✨ 주요 강점
+ ### 주요 강점
```

```diff
- ### ⚡️ 주요 개선 과제
+ ### 주요 개선 과제
```

```diff
- ### ✅ 우선 실행 체크리스트
+ ### 우선 실행 체크리스트
```

- [ ] **Step 5: 참고 자료 섹션의 이모지 제거**

```diff
- ## 📚 참고한 평가 기준
+ ## 참고한 평가 기준
```

```diff
- ### 🔍 Vector Search 참고 자료
+ ### Vector Search 참고 자료
```

```diff
- **📌 주요 평가 관점**
+ **주요 평가 관점**
```

```diff
- **📏 적용 기준**
+ **적용 기준**
```

```diff
- ### 📂 File Search 참고 문서
+ ### File Search 참고 문서
```

- [ ] **Step 6: 출력 형식 제약 지시문 추가**

`lesson_analysis` 섹션의 `**작성 태도**:` 블록 바로 위에 다음 지시문을 추가한다 (모델이 임의로 이모지를 다시 넣지 못하게 보장):

```markdown
**출력 형식 엄격 규칙:**
- 보고서 본문에 이모지·픽토그램·아이콘 문자(예: 📑, 1️⃣, 📊, 💡, 🔎, ✅, 🔧, 🚀, 📝, ✨, ⚡️, 📚, 🔍, 📌, 📏, 📂 등)를 **절대 포함하지 마세요**.
- 헤더와 본문은 한글, 영문, 숫자, 일반 문장 부호로만 구성합니다.
- 키캡 숫자(1️⃣, 2️⃣ 등) 대신 일반 숫자(1., 2.)를 사용합니다.
```

이 블록은 위 형식 예시 코드 블록(```` ``` ````)의 직전(즉, "반드시 다음 Markdown 형식으로 보고서를 작성하세요:" 와 ```` ```markdown ```` 사이)에 삽입한다.

- [ ] **Step 7: 변경된 prompt.md 검증**

Run:
```bash
python -c "import re; t=open('prompt/prompt.md',encoding='utf-8').read(); \
  pattern=re.compile('[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF\U00002300-\U000023FF\U00002B00-\U00002BFF\U0001F100-\U0001F1FF]'); \
  start=t.find('## lesson_analysis'); end=t.find('\n---', start); section=t[start:end]; \
  matches=pattern.findall(section); print('REMAINING_EMOJIS:', matches); \
  assert not matches, f'lesson_analysis 섹션에 이모지가 남아있음: {matches}'"
```
Expected: `REMAINING_EMOJIS: []` 출력 후 종료. assertion 실패 시 누락된 이모지를 추가로 제거한다.

- [ ] **Step 8: PromptLoaderService 회귀 테스트**

Run: `pytest tests/test_prompt_loader_service.py -v`
Expected: 모든 테스트 PASS (프롬프트 파싱이 깨지지 않았는지 확인).

- [ ] **Step 9: Commit**

```bash
git add prompt/prompt.md
git commit -m "feat(prompt): remove emojis from lesson_analysis report template"
```

---

## Task 4: OpenAPI 스키마 예시 문자열 정리

**Files:**
- Modify: `app/schemas/lessonplan_analysis.py:36`

- [ ] **Step 1: 변경 (수동)**

`app/schemas/lessonplan_analysis.py` 의 36번 라인을 수정한다:

```diff
-                "report": "# 📚 수업 지도안 평가 보고서\n\n...",
+                "report": "# 수업 지도안 평가 보고서\n\n...",
```

- [ ] **Step 2: 임포트 무결성 확인**

Run: `python -c "from app.schemas.lessonplan_analysis import LessonPlanAnalysisResponse; print(LessonPlanAnalysisResponse.model_json_schema()['properties']['report'])"`
Expected: 정상 import & 스키마 출력에 `📚` 미포함.

- [ ] **Step 3: Commit**

```bash
git add app/schemas/lessonplan_analysis.py
git commit -m "chore(schemas): drop emoji from lesson_analysis OpenAPI example"
```

---

## Task 5: End-to-End 수동 검증 (라이브 분석 호출)

**Files:** (검증 전용 — 코드 변경 없음)

- [ ] **Step 1: 가상환경 활성화 및 서버 실행**

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```
Expected: `Uvicorn running on http://127.0.0.1:8000` 로그 출력.

- [ ] **Step 2: 기존 PDF로 분석 트리거**

브라우저에서 로그인 → 수업지도안 업로드 페이지 진입 → `criteria/1_초등정보교육과정.pdf` 또는 `app/static/uploads/teacher_*_6-2-8_.pdf` 중 하나를 업로드 → 분석 실행.

- [ ] **Step 3: 신규 보고서 파일에 이모지가 없는지 확인**

```bash
LATEST=$(ls -t app/static/reports/*_reports.md | head -1)
echo "Checking: $LATEST"
python -c "
import re, sys
text = open('$LATEST', encoding='utf-8').read()
pattern = re.compile('[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF\U00002300-\U000023FF\U00002B00-\U00002BFF\U0001F100-\U0001F1FF]')
hits = pattern.findall(text)
print(f'remaining_emojis_count={len(hits)}')
print(f'sample={hits[:10]}')
sys.exit(0 if len(hits)==0 else 1)
"
```
Expected: `remaining_emojis_count=0` 그리고 종료 코드 0. 1 이상이면 후처리 정규식의 추가 보강이 필요하다 (Task 1 의 `_EMOJI_PATTERN` 에 누락된 유니코드 블록을 추가).

- [ ] **Step 4: 보고서 가독성 육안 확인**

`$LATEST` 파일을 마크다운 뷰어 또는 에디터로 열어 다음을 확인:
- 헤더 계층(`#`, `##`, `###`)이 유지되는가
- 5개 평가 항목 + 종합 평가 + 참고한 평가 기준이 모두 존재하는가
- 강점/개선점/제안 등의 굵은 라벨이 깨지지 않았는가
- 빈 줄, `<br>`, 인용 블록(`>`)이 잘 보존되어 있는가

- [ ] **Step 5: 본 검증 결과 메모**

검증 결과(통과/실패, 발견된 이슈)를 PR 또는 GitHub 이슈에 코멘트로 기록한다.

---

## Task 6: 최종 통합 테스트 실행

**Files:** (테스트 실행 전용)

- [ ] **Step 1: 단위 테스트 일괄 실행**

```bash
pytest tests/unit/test_text_sanitizer.py tests/unit/test_lessonplan_analysis_service.py tests/test_prompt_loader_service.py -v
```
Expected: 모든 테스트 PASS.

- [ ] **Step 2: 변경 파일에 잔존 이모지 점검**

```bash
python - <<'PY'
import re, sys
files = [
    "prompt/prompt.md",
    "app/services/lessonplan_analysis_service.py",
    "app/schemas/lessonplan_analysis.py",
    "app/utils/text_sanitizer.py",
]
pat = re.compile(
    "[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF\U00002700-\U000027BF"
    "\U00002300-\U000023FF\U00002B00-\U00002BFF"
    "\U0001F100-\U0001F1FF]"
)
fail = False
for fp in files:
    text = open(fp, encoding="utf-8").read()
    # text_sanitizer.py 와 _post_process_report 의 이모지 정규식/테스트 검사 문자열은
    # 정의 자체이므로 허용. 그 외 파일은 깨끗해야 한다.
    if fp.endswith("text_sanitizer.py"):
        continue
    if fp.endswith("lessonplan_analysis_service.py"):
        # 코드 내부의 검사용 비교 리터럴은 허용. 단 lesson_analysis 헤더에는 없어야.
        continue
    hits = pat.findall(text)
    print(fp, "->", len(hits), "emoji chars")
    if hits:
        fail = True
sys.exit(1 if fail else 0)
PY
```
Expected: 종료 코드 0.

- [ ] **Step 3: 변경 사항 push 및 PR 준비 (필요시)**

```bash
git log --oneline -10
git push origin <branch-name>
```

---

## Self-Review

**1. 스펙 커버리지:**
- "분석 보고서 작성 시 이모지가 많이 나옴" → Task 3 (프롬프트), Task 2 (모델 출력 후처리), Task 4 (스키마 예시) 로 입력·출력 양쪽 모두 차단. ✓
- "이모지가 나오지 않게 수정" → Task 1 의 `strip_emojis()` 가 정규식 기반 안전망. ✓
- "수정에 대한 계획을 세울 것" → 본 plan. ✓
- "issue에 등록" → plan 작성 후 별도 단계로 GitHub 이슈 생성 (gh CLI 또는 사용자 수동). ✓

**2. Placeholder 스캔:**
- "TBD", "implement later", "add appropriate error handling", "similar to Task N" 없음. ✓
- 모든 코드 스텝에 실제 코드 블록 포함. ✓
- 모든 명령에 expected output 명시. ✓

**3. 타입 일관성:**
- `strip_emojis(text: Optional[str]) -> str` 시그니처가 Task 1, 2, 6 에서 동일. ✓
- `_post_process_report(self, report: str) -> str` 시그니처 변경 없음. ✓
- 신규 모듈 경로 `app.utils.text_sanitizer` 가 Task 1 (생성), Task 2 (import), Task 6 (점검)에서 일치. ✓
