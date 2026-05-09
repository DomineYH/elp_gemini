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
# 굵은 글씨 마커(`**`) 시작 직후의 잔여 공백 제거 — 이모지 제거 후 발생.
# CommonMark 에서 `** word` 는 유효한 strong-emphasis opener 가 아님.
# 매칭 문자: 공백·별표·블록인용 마커(`>`) 외 모든 문자 (대괄호·괄호·한글·숫자 등 포함).
_BOLD_LEFT_PADDING = re.compile(r"\*\* +(?=[^\s*>])")
# 굵은 글씨 마커(`**`) 종료 직전의 잔여 공백 제거 — 이모지 제거 후 발생.
_BOLD_RIGHT_PADDING = re.compile(r"(?<=[^\s*>]) +\*\*")
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
    # 굵은 글씨 마커 인접 공백 흡수 (`** word` → `**word`, `word **` → `word**`)
    text = _BOLD_LEFT_PADDING.sub("**", text)
    text = _BOLD_RIGHT_PADDING.sub("**", text)
    # 줄 끝 공백 제거 (개행 없는 마지막 줄 포함)
    text = text.rstrip(" \t")
    return text
