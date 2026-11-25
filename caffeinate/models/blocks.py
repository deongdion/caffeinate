"""글쓰기 블록 - SmartEditor ONE contentJson 을 dataclass 로 [실측 2026-11-24: 에디터 1.78.1 스키마 + 글 저장/렌더]

    from caffeinate import Document, Text, Span, TextStyle, Heading, Quote, Divider, Code, Table, Image, Sticker

    doc = Document([
        Heading("오늘의 기록"),
        Text(["첫 문단", [Span("굵게", bold=True), " 그리고 ", Span("링크", link="https://naver.com")]]),
        Image("a.png"),                      # 글쓰기 때 자동 업로드
        Quote("인용문", source="출처", layout=QuotationLayout.LINE),
        Divider(LineLayout.LINE2),
        Table([["이름", "값"], ["a", "1"]]),
        Code("print('hi')"),
    ])
    await cafe.articles.write(cafe_id, menu_id, "제목", doc)

모든 블록은 to_dict() / from_dict() 로 contentJson 과 오간다. 모르는 키는 `extra` 에 담겨 그대로 다시 나가고,
extra 는 기본값을 덮어쓴다 (완전 커스텀). 모르는 @ctype 은 `RawBlock` 으로 그대로 보존된다.

서버 동작 [실측 2026-11-24, 글 수정으로 확인]
- 모르는 @ctype, id 없는 컴포넌트, 외부 주소 이미지(internalResource false) -> 500 (99999)
- 없는 스티커 -> 500 (31021 만료 또는 유효하지 않은 스티커)
- layout 은 검사 안 함 (없는 값도 저장, se-l-{값}) / 목록 밖 글자 크기·색은 조용히 버림
- javascript: 링크는 href="" 로 비움 / 텍스트의 HTML 은 이스케이프 / 문단 120개 x 1000자도 저장
그래서 로컬에서 막는 것: 빈 문서, 업로드 안 된 이미지, 글자 크기·색 형식, http(s) 아닌 링크, 빈 표, 스티커 번호.
"""
import copy
import json
import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Self, TypeAlias

from ..enums.editor import (
    Align,
    CodeLayout,
    FontFamily,
    FontSize,
    ImageGroupLayout,
    LineLayout,
    LinkCardLayout,
    QuotationLayout,
    StickerFormat,
)
from ..utils.editor import SE_VERSION, se_id, ulid
from ..utils.parsing import as_dict, as_int, as_list
from .photo import UploadedImage

logger = logging.getLogger(__name__)
CTYPE: str = "@ctype"
JSONDict: TypeAlias = dict[str, Any]
STICKER_DOMAIN = "https://storep-phinf.pstatic.net"
# 카페 기본 스티커 묶음 {packCode: (움직이는지, 개수)} - 모두 185x160, 주소 = original_{seq}.gif|png
# [실측 2026-11-24 cafe.editor.sticker_packs/stickers 16묶음 전부]. 로그인 없이 Sticker 를 만들 때 쓴다.
STICKER_PACKS: dict[str, tuple[bool, int]] = {
    "motion3d_02": (True, 24), "cafe_001": (True, 24), "cafe_002": (True, 24), "cafe_003": (True, 24),
    "cafe20_002": (False, 28), "cafe20_001": (False, 28), "motion2d_01": (False, 24), "cafe_004": (False, 28),
    "cafe_005": (False, 26), "cafe_012": (False, 24), "cafe_006": (False, 34), "cafe_007": (False, 20),
    "cafe_008": (False, 24), "cafe_009": (False, 40), "cafe_010": (False, 40), "cafe_011": (False, 40),
}
_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$|^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*[\d.]+\s*)?\)$")
_FONT_SIZES = frozenset(f.value for f in FontSize)
_FONT_FAMILIES = frozenset(f.value for f in FontFamily)


def _check_line_height(v: float | None) -> None:
    # 에디터 메뉴는 1.5~2.1 이지만 서버는 아무 양수나 line-height 로 넣는다 [실측 2026-11-24: 0.5, 1.75, 3]
    if v is not None and (isinstance(v, bool) or not isinstance(v, int | float) or v <= 0):
        raise ValueError(f"줄 간격은 양수여야 합니다 (1.6 = 160%): {v!r}")


def _s(v: Any) -> str:
    return str(v.value if isinstance(v, Enum) else v)


def font_size_of(v: Any) -> FontSize:
    """"fs15" / "FS15" / FontSize -> FontSize (목록 밖이면 ValueError - 렌더·저장 전에 알린다)"""
    s = str(getattr(v, "value", v)).strip().lower()
    if s not in _FONT_SIZES:
        raise ValueError(f"글자 크기는 {sorted(_FONT_SIZES)} 중 하나입니다: {v!r}")
    return FontSize(s)


def _check_color(name: str, value: str | None) -> None:
    # 형식이 틀리면 서버가 조용히 버린다 ("color:;") [실측 2026-11-24] -> 로컬에서 알린다
    if value is not None and not _COLOR_RE.match(value):
        raise ValueError(f"{name} 는 #rrggbb 또는 rgb(r, g, b) 형식이어야 합니다: {value!r}")


def _check_link(url: str | None) -> None:
    # javascript: 등은 서버가 href="" 로 비운다 [실측 2026-11-24]
    if url is not None and not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError(f"링크는 http(s) 주소만 됩니다: {url!r}")


def _split(d: JSONDict, known: Sequence[str]) -> JSONDict:
    """known/@ctype 밖의 키 -> extra"""
    return {k: v for k, v in d.items() if k not in known and k != CTYPE}


# ---------------------------------------------------------------- 텍스트


@dataclass(slots=True, kw_only=True)
class TextStyle:
    """글자 서식 (nodeStyle) [실측 2026-11-24 전부 렌더 확인]"""

    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False                       # strikeThrough
    color: str | None = None                   # fontColor "#ff0000"
    background: str | None = None              # backgroundColor
    size: FontSize | str | None = None         # fontSizeCode
    font: FontFamily | str | None = None       # fontFamily (보기 화면 se-ff-<값>)
    extra: JSONDict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _check_color("color", self.color)
        _check_color("background", self.background)
        if self.size is not None and _s(self.size) not in _FONT_SIZES:
            raise ValueError(f"글자 크기는 {sorted(_FONT_SIZES)} 중 하나입니다: {self.size!r}")
        if self.font is not None and _s(self.font) not in _FONT_FAMILIES:
            raise ValueError(f"서체는 {sorted(_FONT_FAMILIES)} 중 하나입니다 (목록 밖은 extra 로): {self.font!r}")

    def is_empty(self) -> bool:
        return not (self.bold or self.italic or self.underline or self.strike or self.color or self.background
                    or self.size or self.font or self.extra)

    def to_dict(self) -> JSONDict:
        d: JSONDict = {}
        for key, on in (("bold", self.bold), ("italic", self.italic), ("underline", self.underline),
                        ("strikeThrough", self.strike)):
            if on:
                d[key] = True
        if self.color:
            d["fontColor"] = self.color
        if self.background:
            d["backgroundColor"] = self.background
        if self.size:
            d["fontSizeCode"] = _s(self.size)
        if self.font:
            d["fontFamily"] = _s(self.font)
        d.update(self.extra)
        d[CTYPE] = "nodeStyle"
        return d

    @classmethod
    def from_dict(cls, d: Any) -> Self:
        # 서버 값은 검사하지 않고 받는다: 형식 밖 값(transparent, #rrggbbaa, 목록 밖 크기·서체)은 extra 로 그대로 보존
        d = as_dict(d)
        known: dict[str, Any] = {}
        odd: JSONDict = {}
        for key, ok in (("fontColor", lambda v: isinstance(v, str) and bool(_COLOR_RE.match(v))),
                        ("backgroundColor", lambda v: isinstance(v, str) and bool(_COLOR_RE.match(v))),
                        ("fontSizeCode", lambda v: isinstance(v, str) and v in _FONT_SIZES),
                        ("fontFamily", lambda v: isinstance(v, str) and v in _FONT_FAMILIES)):
            v = d.get(key)
            if v in (None, ""):
                continue
            if ok(v):
                known[key] = v
            else:
                odd[key] = v
        size, font = known.get("fontSizeCode"), known.get("fontFamily")
        return cls(
            bold=bool(d.get("bold")), italic=bool(d.get("italic")), underline=bool(d.get("underline")),
            strike=bool(d.get("strikeThrough")), color=known.get("fontColor"),
            background=known.get("backgroundColor"),
            size=FontSize(size) if size else None,
            font=FontFamily(font) if font else None,
            extra=_split(d, ("bold", "italic", "underline", "strikeThrough", "fontColor", "backgroundColor",
                             "fontSizeCode", "fontFamily")) | odd,
        )


@dataclass(slots=True)
class Span:
    """글자 조각 (textNode). 서식은 style= 또는 bold=/color= 같은 단축 인자로

        Span("굵게", bold=True), Span("빨강", color="#ff0000", size=FontSize.FS24), Span("링크", link="https://...")
        Span("명조", font=FontFamily.NANUM_MYEONGJO)
    """

    text: str
    style: TextStyle | None = None
    link: str | None = None                    # urlLink (http/https)
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    color: str | None = None
    background: str | None = None
    size: FontSize | str | None = None
    font: FontFamily | str | None = None
    id: str = field(default_factory=se_id, kw_only=True)
    extra: JSONDict = field(default_factory=dict, kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError(f"Span.text 는 str 이어야 합니다: {type(self.text).__name__}")
        _check_link(self.link)
        if (self.bold or self.italic or self.underline or self.strike or self.color or self.background or self.size
                or self.font):
            b = self.style or TextStyle()
            self.style = TextStyle(
                bold=self.bold or b.bold, italic=self.italic or b.italic, underline=self.underline or b.underline,
                strike=self.strike or b.strike, color=self.color or b.color,
                background=self.background or b.background, size=self.size or b.size, font=self.font or b.font,
                extra=dict(b.extra),
            )
            self.bold = self.italic = self.underline = self.strike = False
            self.color = self.background = self.size = self.font = None

    def to_dict(self) -> JSONDict:
        d: JSONDict = {"id": self.id, "value": self.text}
        if self.style and not self.style.is_empty():
            d["style"] = self.style.to_dict()
        if self.link:
            d["link"] = {"url": self.link, CTYPE: "urlLink"}
        d.update(self.extra)
        d[CTYPE] = "textNode"
        return d

    @classmethod
    def from_dict(cls, d: Any) -> Self:
        d = as_dict(d)
        style = TextStyle.from_dict(d["style"]) if isinstance(d.get("style"), dict) else None
        link = as_dict(d.get("link")).get("url") or None
        extra = _split(d, ("id", "value", "style", "link"))
        if link and not re.match(r"^https?://", link, re.IGNORECASE):
            extra["link"], link = d["link"], None  # 받은 그대로 보존 (검사 없이)
        return cls(str(d.get("value") or ""), style=style, link=link, id=str(d.get("id") or se_id()), extra=extra)


@dataclass(slots=True)
class Paragraph:
    """문단 (paragraph) - 글자 조각 목록 + 정렬 + 줄 간격 (1.6 = 160%)"""

    spans: list[Span] = field(default_factory=list)
    align: Align | str | None = None
    line_height: float | None = None           # paragraphStyle.lineHeight [실측 200% -> 2]
    id: str = field(default_factory=se_id, kw_only=True)
    extra: JSONDict = field(default_factory=dict, kw_only=True)

    def __post_init__(self) -> None:
        _check_line_height(self.line_height)
        self.spans = [s if isinstance(s, Span) else Span(str(s)) for s in self.spans]
        if not self.spans:
            self.spans = [Span("")]  # 빈 줄 = 값이 "" 인 textNode 하나 [실측 2026-11-13]

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    def to_dict(self) -> JSONDict:
        d: JSONDict = {"id": self.id, "nodes": [s.to_dict() for s in self.spans]}
        style: JSONDict = {}
        if self.align:
            style["align"] = _s(self.align)
        if self.line_height is not None:
            style["lineHeight"] = self.line_height
        if style:
            d["style"] = style | {CTYPE: "paragraphStyle"}
        d.update(self.extra)
        d[CTYPE] = "paragraph"
        return d

    @classmethod
    def from_dict(cls, d: Any) -> Self:
        d = as_dict(d)
        style = as_dict(d.get("style"))
        extra = _split(d, ("id", "nodes", "style"))
        lh = style.get("lineHeight")
        if set(style) - {"align", "lineHeight", CTYPE} or (lh is not None and (
                isinstance(lh, bool) or not isinstance(lh, int | float) or lh <= 0)):
            extra["style"], style = style, {}  # 모르는 키나 이상한 값이 있으면 원본 그대로 보존
        align = style.get("align")
        lh = style.get("lineHeight")
        return cls([Span.from_dict(n) for n in as_list(d.get("nodes"))],
                   _enum_or_str(Align, align) if align else None, lh,
                   id=str(d.get("id") or se_id()), extra=extra)


@dataclass(slots=True, kw_only=True)
class ParagraphDefaults:
    """여러 문단에 한꺼번에 주는 기본 서식 (Text/Heading/Quote 의 defaults=, Document 의 defaults=)

    문단·글자에 직접 준 값이 이긴다 (글자 > 블록 > 문서). 직렬화 때만 채우고 객체는 바꾸지 않는다.
        Document([...], defaults=ParagraphDefaults(style=TextStyle(font=FontFamily.NANUM_SQUARE), line_height=1.8))
    """

    style: TextStyle | None = None
    align: Align | str | None = None
    line_height: float | None = None

    def __post_init__(self) -> None:
        _check_line_height(self.line_height)

    def is_empty(self) -> bool:
        return (self.style is None or self.style.is_empty()) and not self.align and self.line_height is None

    def apply(self, paragraphs: list[JSONDict]) -> list[JSONDict]:
        """문단 dict 목록에 없는 키만 채운다 (in-place, 같은 목록 반환)"""
        node: JSONDict = {}
        if self.style is not None and not self.style.is_empty():
            node = {k: v for k, v in self.style.to_dict().items() if k != CTYPE}
        para: JSONDict = {}
        if self.align:
            para["align"] = _s(self.align)
        if self.line_height is not None:
            para["lineHeight"] = self.line_height
        for p in paragraphs:
            if para:
                st = as_dict(p.get("style"))
                p["style"] = para | {k: v for k, v in st.items() if k != CTYPE} | {CTYPE: "paragraphStyle"}
            if node:
                for n in as_list(p.get("nodes")):
                    if isinstance(n, dict):
                        st = as_dict(n.get("style"))
                        n["style"] = node | {k: v for k, v in st.items() if k != CTYPE} | {CTYPE: "nodeStyle"}
        return paragraphs

    def to_dict(self) -> JSONDict:
        d: JSONDict = {}
        if self.style is not None and not self.style.is_empty():
            d["style"] = self.style.to_dict()
        if self.align:
            d["align"] = _s(self.align)
        if self.line_height is not None:
            d["lineHeight"] = self.line_height
        return d

    @classmethod
    def from_dict(cls, d: Any) -> Self:
        d = as_dict(d)
        align = d.get("align")
        return cls(style=TextStyle.from_dict(d["style"]) if isinstance(d.get("style"), dict) else None,
                   align=_enum_or_str(Align, align) if align else None, line_height=d.get("lineHeight"))


def _paras(ps: Sequence[Paragraph], defaults: "ParagraphDefaults | None") -> list[JSONDict]:
    out = [p.to_dict() for p in ps]
    return defaults.apply(out) if defaults is not None and not defaults.is_empty() else out


TextLike: TypeAlias = "str | Span | Paragraph | Sequence[str | Span | Paragraph | Sequence[str | Span]]"


def paragraphs(value: Any) -> list[Paragraph]:
    """텍스트 입력 -> 문단 목록

    - "a\\nb"                 : 줄마다 문단 (CRLF/CR 도 줄바꿈, 빈 줄은 빈 문단)
    - Span / Paragraph        : 문단 1개
    - [항목, ...]             : 항목마다 문단. 항목이 str 이면 그 안의 줄바꿈도 나눔, list/tuple 이면 한 문단의 조각들
    """
    if value is None:
        return []
    if isinstance(value, Paragraph):
        return [value]
    if isinstance(value, Span):
        return [Paragraph([value])]
    if isinstance(value, str):
        return [Paragraph([Span(line)]) for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out: list[Paragraph] = []
    for item in value:
        if isinstance(item, list | tuple):
            out.append(Paragraph([s if isinstance(s, Span) else Span(str(s)) for s in item]))
        else:
            out.extend(paragraphs(item))
    return out


# ---------------------------------------------------------------- 블록 기반


@dataclass(slots=True, kw_only=True)
class Block:
    """블록 공통: id (자동), extra (기본값 덮어쓰기/추가 키). 하위 클래스는 ctype 으로 등록된다"""

    CTYPE: ClassVar[str] = ""
    _REGISTRY: ClassVar[dict[str, type["Block"]]] = {}

    id: str = field(default_factory=se_id, compare=False)  # 같은 내용이면 같은 블록 (id 는 비교하지 않음)
    extra: JSONDict = field(default_factory=dict)
    hint: str | None = field(default=None, compare=False)  # AI 채우기 지시 (스키마 description, contentJson 에는 안 나감)

    def __init_subclass__(cls, **kw: Any) -> None:
        # slots dataclass 는 클래스를 새로 만들어 두 번 불린다 -> 마지막(슬롯) 클래스가 등록된다.
        # 인자 없는 super() 는 슬롯 dataclass 에서 깨지므로 쓰지 않는다.
        if cls.__dict__.get("CTYPE"):
            Block._REGISTRY[cls.CTYPE] = cls

    def _body(self) -> JSONDict:
        raise NotImplementedError

    def to_dict(self) -> JSONDict:
        d: JSONDict = {"id": self.id, **self._body()}
        d.update(self.extra)
        d[CTYPE] = self.CTYPE
        return d

    @classmethod
    def from_dict(cls, d: Any) -> "Block":
        """contentJson 컴포넌트 dict -> 알맞은 블록 (모르는 @ctype 은 RawBlock)"""
        d = as_dict(d)
        target = Block._REGISTRY.get(str(d.get(CTYPE) or ""), RawBlock)
        if cls is not Block and not issubclass(target, cls):
            raise ValueError(f"{cls.__name__} 가 아닌 컴포넌트입니다: @ctype={d.get(CTYPE)!r}")
        try:
            return target._parse(d)
        except (ValueError, TypeError) as e:
            if cls is not Block or target is RawBlock or not d.get(CTYPE):
                raise
            # 서버 문서의 컴포넌트 하나가 형식 밖이어도 문서 전체를 못 읽지 않게 dict 그대로 보존한다
            logger.warning("%s 컴포넌트를 해석하지 못해 RawBlock 으로 보존합니다: %s", d.get(CTYPE), e)
            return RawBlock._parse(d)

    @classmethod
    def _parse(cls, d: JSONDict) -> "Block":
        raise NotImplementedError

    def texts(self) -> Iterator[str]:
        """문서 메타(dio) 계산용 본문 줄"""
        return iter(())

    def images(self) -> Iterator["Image"]:
        return iter(())

    def media(self) -> Iterator[Any]:
        """대표(represent) 후보 - 사진, 동영상 (문서 순서)"""
        return self.images()


@dataclass(slots=True)
class RawBlock(Block):
    """아무 컴포넌트나 dict 그대로 (모르는 @ctype 보존, 직접 만든 컴포넌트). id 가 없으면 채운다 (없으면 500 [실측])"""

    data: JSONDict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.data.get(CTYPE):
            raise ValueError("RawBlock 의 data 에는 @ctype 이 있어야 합니다")
        if self.data.get("id"):
            self.id = str(self.data["id"])

    def to_dict(self) -> JSONDict:
        d = {"id": self.id, **self.data, **self.extra}
        d[CTYPE] = d.pop(CTYPE)  # @ctype 을 끝으로 (에디터 직렬화 순서)
        return d

    @classmethod
    def _parse(cls, d: JSONDict) -> "RawBlock":
        return cls(data=dict(d))


@dataclass(slots=True)
class Text(Block):
    """본문 (text). content: 문자열(줄바꿈=문단) / Span / Paragraph / 목록 (`paragraphs()` 참고)"""

    CTYPE: ClassVar[str] = "text"
    content: Any = ""
    layout: str = "default"
    defaults: ParagraphDefaults | None = field(default=None, kw_only=True)   # 이 블록 모든 문단의 기본 서식

    def __post_init__(self) -> None:
        self.content = paragraphs(self.content)

    @property
    def paragraphs(self) -> list[Paragraph]:
        return list(self.content)

    def _body(self) -> JSONDict:
        return {"layout": _s(self.layout), "value": _paras(self.content, self.defaults)}

    @classmethod
    def _parse(cls, d: JSONDict) -> "Text":
        return cls([Paragraph.from_dict(p) for p in as_list(d.get("value"))], str(d.get("layout") or "default"),
                   id=str(d.get("id") or se_id()), extra=_split(d, ("id", "layout", "value")))

    def texts(self) -> Iterator[str]:
        return (p.text for p in self.content)


@dataclass(slots=True)
class Heading(Block):
    """소제목 (sectionTitle) [실측 2026-11-24]"""

    CTYPE: ClassVar[str] = "sectionTitle"
    content: Any = ""
    layout: str = "default"
    defaults: ParagraphDefaults | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        self.content = paragraphs(self.content)

    def _body(self) -> JSONDict:
        return {"layout": _s(self.layout), "title": _paras(self.content, self.defaults)}

    @classmethod
    def _parse(cls, d: JSONDict) -> "Heading":
        return cls([Paragraph.from_dict(p) for p in as_list(d.get("title"))], str(d.get("layout") or "default"),
                   id=str(d.get("id") or se_id()), extra=_split(d, ("id", "layout", "title")))


@dataclass(slots=True)
class Quote(Block):
    """인용 (quotation) - 본문 + 출처(선택) [실측 2026-11-24 6가지 모양]"""

    CTYPE: ClassVar[str] = "quotation"
    content: Any = ""
    source: Any = None
    layout: QuotationLayout | str = QuotationLayout.DEFAULT
    defaults: ParagraphDefaults | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        self.content = paragraphs(self.content)
        self.source = paragraphs(self.source) if self.source is not None else None

    def _body(self) -> JSONDict:
        d: JSONDict = {"layout": _s(self.layout), "value": _paras(self.content, self.defaults)}
        if self.source:
            d["source"] = _paras(self.source, self.defaults)
        return d

    @classmethod
    def _parse(cls, d: JSONDict) -> "Quote":
        src = d.get("source")
        return cls([Paragraph.from_dict(p) for p in as_list(d.get("value"))],
                   [Paragraph.from_dict(p) for p in as_list(src)] if src else None,
                   _enum_or_str(QuotationLayout, d.get("layout")),
                   id=str(d.get("id") or se_id()), extra=_split(d, ("id", "layout", "value", "source")))


@dataclass(slots=True)
class Divider(Block):
    """구분선 (horizontalLine) [실측 2026-11-24 8가지 모양]"""

    CTYPE: ClassVar[str] = "horizontalLine"
    layout: LineLayout | str = LineLayout.DEFAULT

    def _body(self) -> JSONDict:
        return {"layout": _s(self.layout)}

    @classmethod
    def _parse(cls, d: JSONDict) -> "Divider":
        return cls(_enum_or_str(LineLayout, d.get("layout")), id=str(d.get("id") or se_id()),
                   extra=_split(d, ("id", "layout")))


@dataclass(slots=True)
class Code(Block):
    """코드 (code) - codeContents 는 문자열 하나 [번들 스키마, 실측 2026-11-24: value:[문단] 은 500]

    에디터 화면은 5000자(codeTextMaxLength)까지지만 서버는 5001자도 저장한다 [실측 2026-11-24] -> 로컬 제한 없음.
    """

    CTYPE: ClassVar[str] = "code"
    code: str = ""
    layout: CodeLayout | str = CodeLayout.DEFAULT
    font_size: FontSize | str | None = None   # fontSizeCode (번들은 필수로 적지만 없어도 저장됨 [실측])

    def __post_init__(self) -> None:
        if not isinstance(self.code, str):
            raise TypeError("Code.code 는 str 이어야 합니다")
        if self.font_size is not None:
            self.font_size = font_size_of(self.font_size)

    def _body(self) -> JSONDict:
        d: JSONDict = {"layout": _s(self.layout)}
        if self.font_size:
            d["fontSizeCode"] = _s(self.font_size)
        d["codeContents"] = self.code
        return d

    @classmethod
    def _parse(cls, d: JSONDict) -> "Code":
        fs = d.get("fontSizeCode")
        return cls(str(d.get("codeContents") or ""), _enum_or_str(CodeLayout, d.get("layout")),
                   _enum_or_str(FontSize, fs) if fs else None,
                   id=str(d.get("id") or se_id()), extra=_split(d, ("id", "layout", "fontSizeCode", "codeContents")))


# ---------------------------------------------------------------- 표


@dataclass(slots=True)
class Cell:
    """표 칸 (tableCell). width 를 비우면 표가 칸 수로 나눠 채운다 [스키마: width, height 필수]"""

    content: Any = ""
    col_span: int = 1
    row_span: int = 1
    width: float | None = None
    height: int = 43                            # 에디터 기본 [번들]
    background: str | None = None
    align: Align | str | None = None            # textAlign
    id: str = field(default_factory=se_id, kw_only=True)
    extra: JSONDict = field(default_factory=dict, kw_only=True)

    def __post_init__(self) -> None:
        self.content = paragraphs(self.content)
        if self.col_span < 1 or self.row_span < 1:
            raise ValueError("col_span/row_span 은 1 이상이어야 합니다")
        _check_color("background", self.background)

    def to_dict(self, default_width: float = 50.0) -> JSONDict:
        d: JSONDict = {"id": self.id, "value": [p.to_dict() for p in self.content], "colSpan": self.col_span,
                       "rowSpan": self.row_span, "width": self.width if self.width is not None else default_width,
                       "height": self.height}
        if self.background:
            d["backgroundColor"] = self.background
        if self.align:
            d["textAlign"] = _s(self.align)
        d.update(self.extra)
        d[CTYPE] = "tableCell"
        return d

    @classmethod
    def from_dict(cls, d: Any) -> Self:
        d = as_dict(d)
        align = d.get("textAlign")
        return cls([Paragraph.from_dict(p) for p in as_list(d.get("value"))], as_int(d.get("colSpan"), 1),
                   as_int(d.get("rowSpan"), 1), d.get("width"), as_int(d.get("height"), 43),
                   d.get("backgroundColor") or None, _enum_or_str(Align, align) if align else None,
                   id=str(d.get("id") or se_id()),
                   extra=_split(d, ("id", "value", "colSpan", "rowSpan", "width", "height", "backgroundColor",
                                    "textAlign")))


@dataclass(slots=True)
class TableRow:
    cells: list[Cell] = field(default_factory=list)
    id: str = field(default_factory=se_id, kw_only=True)
    extra: JSONDict = field(default_factory=dict, kw_only=True)

    def __post_init__(self) -> None:
        self.cells = [c if isinstance(c, Cell) else Cell(c) for c in self.cells]

    @property
    def span(self) -> int:
        return sum(c.col_span for c in self.cells)


@dataclass(slots=True)
class Table(Block):
    """표 (table) - rows: [[칸, ...], ...]. 칸은 Cell 또는 텍스트 [실측 2026-11-24: 표 width 빠지면 500]

    줄마다 칸 수가 달라도 서버는 저장한다 [실측]. column_count 를 비우면 가장 긴 줄의 칸(colSpan 합) 수.
    """

    CTYPE: ClassVar[str] = "table"
    rows: list[Any] = field(default_factory=list)
    width: float = 100
    layout: str = "default"
    column_count: int | None = None
    align: Align | str | None = None
    border_style: str | None = None            # borderStyleName (에디터 기본 thinLine)

    def __post_init__(self) -> None:
        self.rows = [r if isinstance(r, TableRow) else TableRow(list(r)) for r in self.rows]
        if not self.rows or not any(r.cells for r in self.rows):
            raise ValueError("표에는 칸이 하나 이상 있어야 합니다")

    @property
    def columns(self) -> int:
        return self.column_count or max(r.span for r in self.rows)

    def _body(self) -> JSONDict:
        default_w = round(100 / self.columns, 8)
        d: JSONDict = {"layout": _s(self.layout), "width": self.width, "columnCount": self.columns, "rows": [
            {"id": r.id, "cells": [c.to_dict(default_w * c.col_span) for c in r.cells], **r.extra, CTYPE: "tableRow"}
            for r in self.rows
        ]}
        if self.align:
            d["align"] = _s(self.align)
        if self.border_style:
            d["borderStyleName"] = self.border_style
        return d

    @classmethod
    def _parse(cls, d: JSONDict) -> "Table":
        rows = [TableRow([Cell.from_dict(c) for c in as_list(as_dict(r).get("cells"))],
                         id=str(as_dict(r).get("id") or se_id()), extra=_split(as_dict(r), ("id", "cells")))
                for r in as_list(d.get("rows"))]
        align = d.get("align")
        return cls(rows, d.get("width", 100), str(d.get("layout") or "default"), as_int(d.get("columnCount")) or None,
                   _enum_or_str(Align, align) if align else None, d.get("borderStyleName"),
                   id=str(d.get("id") or se_id()),
                   extra=_split(d, ("id", "layout", "width", "columnCount", "rows", "align", "borderStyleName")))

    def texts(self) -> Iterator[str]:
        return (p.text for r in self.rows for c in r.cells for p in c.content)


# ---------------------------------------------------------------- 이미지


@dataclass(slots=True)
class Image(Block):
    """사진 (image). source 가 UploadedImage 가 아니면 글쓰기 때 자동 업로드된다

    represent 를 비우면 문서의 첫 사진이 대표 사진. 외부 주소 이미지는 서버가 500 [실측 2026-11-24] -> 올려서 쓴다.
    """

    CTYPE: ClassVar[str] = "image"
    source: Any = None
    represent: bool | None = None
    link: str | None = None                    # 사진 클릭 시 이동 주소
    layout: str = "default"
    caption: Any = None                        # 사진 설명 (텍스트 입력, [실측 2026-11-24] 문단 배열로 저장·렌더)

    def __post_init__(self) -> None:
        self.caption = paragraphs(self.caption) if self.caption is not None else None
        if self.source is None:
            raise ValueError("Image 에는 source(UploadedImage / bytes / 파일 경로 / (bytes, 이름))가 필요합니다")
        _check_link(self.link)

    @property
    def uploaded(self) -> UploadedImage | None:
        return self.source if isinstance(self.source, UploadedImage) else None

    def _body(self) -> JSONDict:
        img = self.uploaded
        if img is None:
            raise ValueError("업로드 안 된 Image 입니다 - articles.write 에 넘기면 자동으로 올립니다 (직접: cafe.photos.upload 결과 UploadedImage 를 Image 에)")
        # [실측 2026-11-12] path 는 업로드 응답 <url>. 키 순서는 브라우저 캡처 그대로
        d: JSONDict = {
            "layout": _s(self.layout), "src": img.src, "internalResource": True, "represent": bool(self.represent),
            "path": img.url, "domain": img.domain, "fileSize": img.file_size, "width": img.width,
            "widthPercentage": 0, "height": img.height, "originalWidth": img.width, "originalHeight": img.height,
            "fileName": img.file_name,
            "caption": [p.to_dict() for p in self.caption] if self.caption else None, "format": "normal", "displayFormat": "normal",
            "imageLoaded": True, "contentMode": "normal", "origin": {"srcFrom": "local", CTYPE: "imageOrigin"},
            "ai": False,
        }
        if self.link:
            d["link"] = self.link
        return d

    @classmethod
    def _parse(cls, d: JSONDict) -> "Image":
        path = str(d.get("path") or "")
        img = UploadedImage(url=path, path=path.rsplit("/", 1)[0], domain=str(d.get("domain") or ""),
                            file_name=str(d.get("fileName") or ""), width=as_int(d.get("width")),
                            height=as_int(d.get("height")), file_size=as_int(d.get("fileSize")))
        known = ("id", "layout", "src", "internalResource", "represent", "path", "domain", "fileSize", "width",
                 "height", "fileName", "link", "caption")
        extra = _split(d, known)
        if d.get("src") and d.get("src") != img.src:
            extra["src"] = d["src"]
        cap = d.get("caption")
        if cap is not None and not isinstance(cap, list):
            extra["caption"], cap = cap, None  # 문단 배열이 아니면 받은 그대로 보존
        return cls(img, bool(d.get("represent")), d.get("link") or None, str(d.get("layout") or "default"),
                   [Paragraph.from_dict(p) for p in cap] if cap else None,
                   id=str(d.get("id") or se_id()), extra=extra)

    def images(self) -> Iterator["Image"]:
        yield self


def _as_images(items: Sequence[Any]) -> list[Image]:
    return [i if isinstance(i, Image) else Image(i) for i in items]


@dataclass(slots=True)
class ImageGroup(Block):
    """사진 묶음 (imageGroup) - slide / collage [실측 2026-11-24]. 안쪽 사진도 layout 이 있어야 저장된다"""

    CTYPE: ClassVar[str] = "imageGroup"
    items: list[Any] = field(default_factory=list)
    layout: ImageGroupLayout | str = ImageGroupLayout.SLIDE
    content_mode: str = "normal"

    def __post_init__(self) -> None:
        self.items = _as_images(self.items)
        if len(self.items) < 2:
            raise ValueError("사진 묶음에는 사진이 2장 이상 있어야 합니다")

    def _body(self) -> JSONDict:
        return {"layout": _s(self.layout), "contentMode": self.content_mode,
                "images": [i.to_dict() for i in self.items]}

    @classmethod
    def _parse(cls, d: JSONDict) -> "ImageGroup":
        return cls([Image._parse(as_dict(i)) for i in as_list(d.get("images"))],
                   _enum_or_str(ImageGroupLayout, d.get("layout"), ImageGroupLayout.SLIDE), str(d.get("contentMode") or "normal"),
                   id=str(d.get("id") or se_id()), extra=_split(d, ("id", "layout", "contentMode", "images")))

    def images(self) -> Iterator[Image]:
        return iter(self.items)


@dataclass(slots=True)
class ImageStrip(Block):
    """가로 나란히 사진 (imageStrip) [실측 2026-11-24]"""

    CTYPE: ClassVar[str] = "imageStrip"
    items: list[Any] = field(default_factory=list)
    layout: str = "default"
    content_mode: str = "normal"

    def __post_init__(self) -> None:
        self.items = _as_images(self.items)
        if len(self.items) < 2:
            raise ValueError("나란히 사진에는 사진이 2장 이상 있어야 합니다")

    def _body(self) -> JSONDict:
        return {"layout": _s(self.layout), "contentMode": self.content_mode,
                "images": [i.to_dict() for i in self.items]}

    @classmethod
    def _parse(cls, d: JSONDict) -> "ImageStrip":
        return cls([Image._parse(as_dict(i)) for i in as_list(d.get("images"))], str(d.get("layout") or "default"),
                   str(d.get("contentMode") or "normal"),
                   id=str(d.get("id") or se_id()), extra=_split(d, ("id", "layout", "contentMode", "images")))

    def images(self) -> Iterator[Image]:
        return iter(self.items)


# ---------------------------------------------------------------- 스티커 / 링크 미리보기


@dataclass(slots=True, frozen=True, kw_only=True)
class Thumbnail:
    src: str
    width: int = 0
    height: int = 0

    def to_dict(self) -> JSONDict:
        return {"src": self.src, "width": self.width, "height": self.height, CTYPE: "thumbnail"}

    @classmethod
    def from_dict(cls, d: Any) -> "Thumbnail | None":
        d = as_dict(d)
        if not d.get("src") and not d.get("url"):
            return None
        return cls(src=str(d.get("src") or d.get("url")), width=as_int(d.get("width")), height=as_int(d.get("height")))


@dataclass(slots=True, frozen=True, kw_only=True)
class StickerPack:
    """스티커 묶음 (platform.editor /stickers 목록 항목) [실측 2026-11-24: 기본 묶음 16개, cafe_001 등]"""

    pack_code: str
    animated: bool = False
    free: bool = True
    count: int = 0                 # stickerCount
    order: int = 0                 # packOrder
    type: str = ""                 # stickerType (common ...)
    raw: JSONDict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Any) -> "StickerPack":
        d = as_dict(d)
        return cls(pack_code=str(d.get("packCode") or ""), animated=bool(d.get("isAnimated")),
                   free=bool(d.get("isFree", True)), count=as_int(d.get("stickerCount")),
                   order=as_int(d.get("packOrder")), type=str(d.get("stickerType") or ""), raw=d)


@dataclass(slots=True)
class Sticker(Block):
    """스티커 - 글(sticker 컴포넌트)과 댓글(stickerId) 양쪽에 쓴다

        packs = await cafe.editor.sticker_packs(cafe_id, menu_id)
        st = (await cafe.editor.stickers(cafe_id, menu_id, "cafe_001"))[0]
        Document([st])                           # 글
        await cafe.comments.add(ref, "", sticker_id=st)   # 댓글 ("cafe_001-1-185-160")

    로그인 없이 Sticker("cafe_001", 3) 처럼 만들어도 된다 - 카페 기본 묶음(STICKER_PACKS)은 움직임 여부·개수를 안다.
    없는 스티커는 서버가 500 (31021) [실측 2026-11-24].
    """

    CTYPE: ClassVar[str] = "sticker"
    pack_code: str = ""
    seq: int = 0
    width: int = 185
    height: int = 160
    url: str | None = None                      # 원본 이미지 (비우면 storep-phinf 규칙으로)
    animated: bool | None = None                # None = STICKER_PACKS 로 정함 (모르는 묶음은 정지)
    layout: str = "default"

    def __post_init__(self) -> None:
        if not self.pack_code or self.seq < 1:
            raise ValueError("Sticker 에는 pack_code 와 1 이상의 seq 가 필요합니다")
        known = STICKER_PACKS.get(self.pack_code)
        if self.animated is None:
            # 움직이는 묶음을 png/normal 로 보내면 저장은 되지만 "존재하지 않는 스티커" 로 보인다 [실측 2026-11-24]
            self.animated = known[0] if known else False
        if known and self.url is None and self.seq > known[1]:
            raise ValueError(f"{self.pack_code} 묶음 스티커는 1~{known[1]} 번입니다: {self.seq}")

    @property
    def code(self) -> str:
        """stickerCode ("cafe_001-1")"""
        return f"{self.pack_code}-{self.seq}"

    @property
    def comment_id(self) -> str:
        """댓글 stickerId "{stickerCode}-{w}-{h}" """
        return f"{self.code}-{self.width}-{self.height}"

    @property
    def image_url(self) -> str:
        ext = "gif" if self.animated else "png"
        return self.url or f"{STICKER_DOMAIN}/{self.pack_code}/original_{self.seq}.{ext}"

    def _body(self) -> JSONDict:
        return {"layout": _s(self.layout), "packCode": self.pack_code, "seq": self.seq,
                "thumbnail": Thumbnail(src=self.image_url, width=self.width, height=self.height).to_dict(),
                "format": _s(StickerFormat.ANIMATED if self.animated else StickerFormat.NORMAL)}

    @classmethod
    def _parse(cls, d: JSONDict) -> "Sticker":
        th = Thumbnail.from_dict(d.get("thumbnail"))
        fmt = d.get("format")
        odd = {} if fmt in (None, StickerFormat.ANIMATED, StickerFormat.NORMAL) else {"format": fmt}  # 모르는 값 보존
        return cls(str(d.get("packCode") or ""), as_int(d.get("seq")), th.width if th else 185,
                   th.height if th else 160, th.src if th else None, fmt == StickerFormat.ANIMATED,
                   str(d.get("layout") or "default"), id=str(d.get("id") or se_id()),
                   extra=_split(d, ("id", "layout", "packCode", "seq", "thumbnail", "format")) | odd)

    @classmethod
    def from_api(cls, item: Any, *, pack_code: str = "", animated: bool | None = None) -> Self:
        """에디터 스티커 목록 항목 (platform.editor /stickers/{pack}) -> Sticker [실측 2026-11-24]"""
        d = as_dict(item)
        code = str(d.get("stickerCode") or "")
        pack = pack_code or code.rsplit("-", 1)[0]
        url = str(d.get("originalUrl") or "") or None
        return cls(pack, as_int(d.get("seq")), as_int(d.get("imageWidth"), 185), as_int(d.get("imageHeight"), 160),
                   url, animated if animated is not None else bool(url and url.endswith(".gif")))

    @classmethod
    def parse(cls, comment_id: str) -> Self:
        """댓글 stickerId "cafe_001-1-185-160" -> Sticker"""
        m = re.fullmatch(r"(.+)-(\d+)-(\d+)-(\d+)", comment_id.strip())
        if not m:
            raise ValueError(f"스티커 id 형식은 'pack-seq-w-h' 입니다: {comment_id!r}")
        return cls(m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)))


@dataclass(slots=True)
class LinkCard(Block):
    """링크 미리보기 (oglink). 보통 `await cafe.editor.link_card(cafe, menu, url)` 로 만든다

    서버 서명(oglinkSign)이 없어도 저장은 된다 [실측 2026-11-24] - 직접 채워도 된다.
    """

    CTYPE: ClassVar[str] = "oglink"
    url: str = ""
    title: str = ""
    domain: str = ""
    description: str = ""
    thumbnail: Thumbnail | None = None
    sign: str | None = None
    video: bool = False
    layout: LinkCardLayout | str = LinkCardLayout.LARGE_IMAGE

    def __post_init__(self) -> None:
        _check_link(self.url)
        if not self.domain:
            self.domain = re.sub(r"^https?://([^/?#]+).*$", r"\1", self.url)
        if not self.title:
            self.title = self.url

    def _body(self) -> JSONDict:
        d: JSONDict = {"layout": _s(self.layout), "title": self.title, "domain": self.domain, "link": self.url}
        if self.thumbnail:
            d["thumbnail"] = self.thumbnail.to_dict()
        d["description"] = self.description
        d["video"] = self.video
        if self.sign:
            d["oglinkSign"] = self.sign
        return d

    @classmethod
    def _parse(cls, d: JSONDict) -> "LinkCard":
        return cls(str(d.get("link") or ""), str(d.get("title") or ""), str(d.get("domain") or ""),
                   str(d.get("description") or ""), Thumbnail.from_dict(d.get("thumbnail")),
                   d.get("oglinkSign") or None, bool(d.get("video")), _enum_or_str(LinkCardLayout, d.get("layout"), LinkCardLayout.LARGE_IMAGE),
                   id=str(d.get("id") or se_id()),
                   extra=_split(d, ("id", "layout", "title", "domain", "link", "thumbnail", "description", "video",
                                    "oglinkSign")))

    @classmethod
    def from_api(cls, data: Any, *, layout: LinkCardLayout | str = LinkCardLayout.LARGE_IMAGE) -> Self:
        """platform.editor /oglink?url= 응답 -> LinkCard [실측 2026-11-24]"""
        d = as_dict(data)
        og = as_dict(d.get("oglink"))
        sm = as_dict(og.get("summary"))
        if not sm:
            raise ValueError(f"링크 미리보기를 만들 수 없는 주소입니다: {str(d)[:200]}")
        return cls(str(og.get("url") or sm.get("url") or ""), str(sm.get("title") or ""),
                   str(sm.get("domain") or ""), str(sm.get("description") or ""),
                   Thumbnail.from_dict(sm.get("image")), d.get("oglinkSign") or None, sm.get("type") == "video",
                   layout)


def _enum_or_str(enum: type[Enum], value: Any, default: Any = None) -> Any:
    """값 -> enum (모르는 값은 문자열 그대로). 값이 없으면 default (생성자 기본값과 맞춘다), 그것도 없으면 첫 멤버"""
    if value is None:
        return default if default is not None else next(iter(enum.__members__.values()))  # type: ignore[call-overload]
    try:
        return enum(value)
    except ValueError:
        return str(value)


# ---------------------------------------------------------------- 문서


_PARAGRAPH_KEYS = {"text": ("value",), "sectionTitle": ("title",), "quotation": ("value", "source")}


@dataclass(slots=True)
class Document:
    """글 본문 전체 (SmartEditor document). blocks 에 str 을 넣으면 Text 블록이 된다"""

    blocks: list[Any] = field(default_factory=list)
    id: str = field(default_factory=ulid, kw_only=True)
    version: str = field(default=SE_VERSION, kw_only=True)
    theme: str = field(default="default", kw_only=True)
    language: str = field(default="ko-KR", kw_only=True)
    defaults: ParagraphDefaults | None = field(default=None, kw_only=True)   # 글 전체 글자·문단 기본 서식
    extra: JSONDict = field(default_factory=dict, kw_only=True)

    def __post_init__(self) -> None:
        if isinstance(self.blocks, Block | str):
            self.blocks = [self.blocks]
        self.blocks = [Text(b) if isinstance(b, str) else b for b in self.blocks]
        for b in self.blocks:
            if not isinstance(b, Block):
                raise TypeError(f"Document 에는 Block 또는 str 만 넣을 수 있습니다: {type(b).__name__}")

    def images(self) -> list[Image]:
        return [i for b in self.blocks for i in b.images()]

    def pending_images(self) -> list[Image]:
        """아직 업로드 안 된 사진들"""
        return [i for i in self.images() if i.uploaded is None]

    def _dio(self) -> list[JSONDict]:
        """문서 메타 (di.dio) [실측 2026-11-13: 비면 500 / 항목은 텍스트 1 + 사진 1 까지]

        텍스트 항목 st = 빈 줄을 뺀 본문 줄을 "\\n" 으로 이은 UTF-8 바이트 길이.
        텍스트·사진이 다 없으면 (구분선만 등) st=0 텍스트 항목을 넣는다 [실측 2026-11-24 저장 확인].
        """
        lines = [t for b in self.blocks for t in b.texts()]
        has_text = any(isinstance(b, Text) for b in self.blocks)
        has_image = bool(self.images())
        dio: list[JSONDict] = []
        if has_text or not has_image:
            st = len("\n".join(ln for ln in lines if ln.strip()).encode("utf-8"))
            dio.append({"dis": "N", "dia": {"t": 0, "p": 0, "st": st, "sk": 1}})
        if has_image:
            dio.append({"dis": "N", "dia": {"t": 0, "p": 0, "st": 0, "sk": 0}})
        return dio

    def to_dict(self) -> JSONDict:
        if not self.blocks:
            raise ValueError("빈 문서입니다 (블록이 하나 이상 있어야 합니다)")
        media = [m for b in self.blocks for m in b.media()]
        auto = media[0] if media and not any(m.represent for m in media) else None
        before = auto.represent if auto is not None else None
        if auto is not None:
            auto.represent = True  # 첫 사진/동영상이 대표 (직렬화하는 동안만 - 사용자 객체는 그대로 둔다)
        try:
            components = [b.to_dict() for b in self.blocks]
        finally:
            if auto is not None:
                auto.represent = before
        if self.defaults is not None and not self.defaults.is_empty():
            for c in components:   # 본문·소제목·인용구 문단 (블록·문단에 직접 준 값이 이긴다)
                for key in _PARAGRAPH_KEYS.get(c.get(CTYPE), ()):
                    if isinstance(c.get(key), list):
                        c[key] = copy.deepcopy(c[key])   # extra 로 받은 사용자 리스트를 바꾸지 않게
                        self.defaults.apply(c[key])
        doc: JSONDict = {"version": self.version, "theme": self.theme, "language": self.language, "id": self.id,
                         "di": {"dif": False, "dio": self._dio()}, "components": components}
        doc.update(self.extra)
        return {"document": doc}

    def to_json(self) -> str:
        """contentJson 문자열 (프론트와 같은 compact JSON)"""
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Any) -> Self:
        d = as_dict(data)
        doc = as_dict(d.get("document")) or d
        return cls([Block.from_dict(c) for c in as_list(doc.get("components"))],
                   id=str(doc.get("id") or ulid()), version=str(doc.get("version") or SE_VERSION),
                   theme=str(doc.get("theme") or "default"), language=str(doc.get("language") or "ko-KR"),
                   extra=_split(doc, ("version", "theme", "language", "id", "di", "components")))

    @classmethod
    def from_json(cls, text: str) -> Self:
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_text(cls, text: str, images: Sequence[Any] | None = None) -> Self:
        """본문 문자열 + 사진 (사진은 본문 뒤로) - articles.write(body=str) 와 같은 결과"""
        blocks: list[Any] = [Text(text)] if text else []
        blocks += [Image(i) for i in images or []]
        if not blocks:
            raise ValueError("본문 텍스트나 이미지 중 하나는 있어야 합니다")
        return cls(blocks)

    @property
    def text(self) -> str:
        """본문 글자만 (블록 사이 줄바꿈)"""
        return "\n".join(t for b in self.blocks for t in b.texts())

    # ------------------------------------------------ spec / 스키마 / AI 채우기 (models/spec.py)

    def to_spec(self, *, ids: bool = False) -> JSONDict:
        """단순 JSON {"blocks": [{"type": "text", "content": ...}, ...]} (사람·AI 용, extra 는 빠짐)"""
        from .spec import document_to_spec

        return document_to_spec(self, ids=ids)

    @classmethod
    def from_spec(cls, data: Any) -> "Document":
        """단순 JSON -> Document ({"blocks": [...]} 또는 [...])"""
        from .spec import document_from_spec

        return document_from_spec(data)

    @staticmethod
    def json_schema() -> JSONDict:
        """자유 작성용 JSON Schema (AI 가 문서를 통째로 만들 때) -> Document.from_spec 으로 받는다"""
        from .spec import document_schema

        return document_schema()

    def fill_schema(self, *, rich: bool = False) -> JSONDict:
        """이 문서를 템플릿으로 고정한 JSON Schema - 채울 칸(글·소제목·인용·코드·표·hint 있는 사진 캡션)만"""
        from .spec import fill_schema

        return fill_schema(self, rich=rich)

    def fill(self, data: Any, *, strict: bool = True) -> "Document":
        """fill_schema 형식으로 채운 JSON -> 같은 구조(id·모양·사진·스티커 유지)에 내용만 바뀐 새 Document"""
        from .spec import fill

        return fill(self, data, strict=strict)
