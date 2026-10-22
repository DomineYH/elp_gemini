"""
보고서 텍스트 살균 유틸리티

분석 보고서에서 이모지/픽토그램을 제거한다. LLM이 마크다운 헤더에 자체적으로
이모지를 추가하더라도 저장 전에 일관된 텍스트 전용 형식으로 정규화한다.
"""

import re
from typing import Optional

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f680-\U0001f6ff"  # transport & map symbols
    "\U0001f700-\U0001f77f"  # alchemical
    "\U0001f780-\U0001f7ff"  # geometric shapes extended
    "\U0001f800-\U0001f8ff"  # supplemental arrows-c
    "\U0001f900-\U0001f9ff"  # supplemental symbols & pictographs
    "\U0001fa00-\U0001fa6f"  # chess / symbols
    "\U0001fa70-\U0001faff"  # symbols & pictographs extended-a
    "\U00002600-\U000026ff"  # miscellaneous symbols (☀, ⚡)
    "\U00002700-\U000027bf"  # dingbats (✅, ✨, ✍)
    "\U00002300-\U000023ff"  # technical (⏰, ⌛)
    "\U00002b00-\U00002bff"  # arrows / stars
    "\U0001f000-\U0001f02f"  # mahjong
    "\U0001f100-\U0001f1ff"  # enclosed alphanumerics supplement
    "\U0001f200-\U0001f2ff"  # enclosed ideographic supplement
    "\U0000fe00-\U0000fe0f"  # variation selectors (e.g. emoji-style "⚡️"의 FE0F)
    "\U0000200d"  # zero-width joiner
    "\U000020e3"  # combining enclosing keycap (1️⃣ 의 결합 문자)
    "]+",
    flags=re.UNICODE,
)

_MULTI_SPACE = re.compile(r"(?<=\S)[ \t]{2,}")
_TRAILING_SPACE_BEFORE_NEWLINE = re.compile(r"[ \t]+\n")
# 굵은 글씨 영역(`**...**`) 내부의 양 끝 공백만 흡수.
# 이모지 제거로 발생한 잔여 공백(`** word`, `word **`) 을 정리하면서, 외부의
# 리스트 마커/들여쓰기와 굵은 마커 사이 정상 공백(`- **항목**`, `1. **[제안]**`,
# `> - **라벨**`) 은 영향받지 않게 함.
# `(?:(?!\*\*).)+?` 콘텐츠 매칭: 단일 별표(`*` 인라인 이탤릭/리터럴) 는 허용하고
# `**` 시퀀스만 종결자로 인식. `\n` 은 비매칭(`re.DOTALL` 미사용) — 줄바꿈으로
# 굵은 영역이 끝나는 게 자연스러움.
# `re.DOTALL` 로 콘텐츠가 줄바꿈을 포함할 수 있게 함 — 멀티라인 굵은 영역
# (예: '**foo\nbar**') 도 양 끝 공백 정리 대상.
_BOLD_SPAN = re.compile(r"\*\*((?:(?!\*\*).)+?)\*\*", re.DOTALL)
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

    # 키캡 시퀀스의 결합 문자만 제거하고 숫자는 보존 ('1️⃣' → '1')
    text = _KEYCAP_DIGIT.sub(r"\1", text)
    # 그 외 이모지·픽토그램·VS·ZWJ 제거
    text = _EMOJI_PATTERN.sub("", text)
    # 잔여 공백 정리
    text = _MULTI_SPACE.sub(" ", text)
    text = _TRAILING_SPACE_BEFORE_NEWLINE.sub("\n", text)

    # 굵은 글씨 영역 내부 양 끝 공백 흡수 (`** word **` → `**word**`).
    # 영역 외부의 리스트/들여쓰기 공백은 무영향.
    def _strip_inner(match: "re.Match[str]") -> str:
        content = match.group(1).strip()
        return f"**{content}**" if content else match.group(0)

    text = _BOLD_SPAN.sub(_strip_inner, text)

    # 줄 끝 공백 제거 (개행 없는 마지막 줄 포함)
    text = text.rstrip(" \t")
    return text
