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

_MULTI_SPACE = re.compile(r"(?<=\S)[ \t]{2,}")
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

    # 키캡 시퀀스의 결합 문자만 제거하고 숫자는 보존 ('1️⃣' → '1')
    text = _KEYCAP_DIGIT.sub(r"\1", text)
    # 그 외 이모지·픽토그램·VS·ZWJ 제거
    text = _EMOJI_PATTERN.sub("", text)
    # 잔여 공백 정리
    text = _MULTI_SPACE.sub(" ", text)
    text = _TRAILING_SPACE_BEFORE_NEWLINE.sub("\n", text)
    # 줄 끝 공백 제거 (개행 없는 마지막 줄 포함)
    text = text.rstrip(" \t")
    return text
