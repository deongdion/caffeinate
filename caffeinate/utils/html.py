"""카페 본문 HTML -> 텍스트"""
import html
import re

_RE_TAG = re.compile(r"<[^>]+>")
_RE_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)


def html_to_text(content_html: str) -> str:
    """본문 HTML -> 대략적인 텍스트 (미리보기/출력용)"""
    s = _RE_BR.sub("\n", content_html or "")
    s = re.sub(r"</(p|div|li|h\d)>", "\n", s, flags=re.IGNORECASE)
    s = html.unescape(_RE_TAG.sub("", s)).replace("\u200b", "").replace("\xa0", " ")
    lines = [line.strip() for line in s.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
