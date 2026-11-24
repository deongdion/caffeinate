"""블록 <-> 단순 JSON(spec) <-> JSON Schema - AI 가 채우거나 작성하는 용도

contentJson(to_dict)은 서버용 무손실 형식이라 id·@ctype·스타일 노드가 많다. spec 은 사람·AI 가 쓰기 쉬운 형식이다.

    {"blocks": [
        {"type": "heading", "content": "소제목"},
        {"type": "text", "content": "첫 줄\\n둘째 줄"},
        {"type": "text", "content": [{"spans": ["보통 ", {"text": "굵게", "bold": true}], "align": "center"}]},
        {"type": "quote", "content": "인용", "source": "출처", "layout": "quotation_line"},
        {"type": "table", "rows": [["이름", "값"], ["a", "1"]]},
        {"type": "image", "source": "a.png", "caption": "설명"},
        {"type": "sticker", "pack_code": "cafe_001", "seq": 1},
        {"type": "divider"}
    ]}

두 가지 쓰임
1) 자유 작성: `document_schema()` 를 AI 에 주고 받은 JSON 을 `Document.from_spec()` 으로.
2) 템플릿 채우기: 구조(블록 종류·순서·모양·사진·스티커)는 고정하고 내용 칸만 AI 가 채운다.

        tpl = Document([Heading("", hint="글 제목"), Text("", hint="3문단 본문"), Image("a.png"),
                        Table([["", ""], ["", ""]], hint="장단점 표")])
        schema = tpl.fill_schema()      # {"0_heading": {"content": str}, "1_text": {...}, "3_table": {"rows": ...}}
        filled = tpl.fill(ai_json)      # 같은 구조, 같은 id·모양·사진에 내용만 채운 새 Document

   채울 칸이 없는 블록(사진·구분선·스티커·링크 미리보기·Raw)은 스키마에서 빠지고 그대로 남는다.
   hint 는 각 칸의 description 으로 들어간다.

spec 은 extra(커스텀 키)를 담지 않는다 (무손실이 필요하면 to_dict/from_dict). 단 fill() 은 템플릿 블록을 복사해서
내용만 바꾸므로 id·extra·hint·업로드된 사진이 그대로 유지된다.
"""
import copy
from collections.abc import Mapping, Sequence
from typing import Any

from ..enums.editor import (
    Align,
    CodeLayout,
    FontSize,
    ImageGroupLayout,
    LineLayout,
    LinkCardLayout,
    QuotationLayout,
)
from ..utils.parsing import as_dict, as_int
from .blocks import (
    Block,
    Cell,
    Code,
    Divider,
    Document,
    Heading,
    Image,
    ImageGroup,
    ImageStrip,
    LinkCard,
    Paragraph,
    Quote,
    RawBlock,
    Span,
    Sticker,
    Table,
    TableRow,
    Text,
    TextStyle,
    Thumbnail,
)
from .photo import UploadedImage

JSONDict = dict[str, Any]


class SpecError(ValueError, TypeError):
    """spec/채우기 JSON 이 형식에 맞지 않음 (AI 출력 검사용 - ValueError 로도 TypeError 로도 잡힌다)"""

TYPE_OF: dict[type[Block], str] = {
    Text: "text", Heading: "heading", Quote: "quote", Divider: "divider", Code: "code", Table: "table",
    Image: "image", ImageGroup: "image_group", ImageStrip: "image_strip", Sticker: "sticker",
    LinkCard: "link_card", RawBlock: "raw",
}
CLASS_OF: dict[str, type[Block]] = {v: k for k, v in TYPE_OF.items()}


# ---------------------------------------------------------------- 블록 -> spec


def _span_spec(s: Span) -> Any:
    st = s.style
    if (st is None or st.is_empty()) and not s.link:
        return s.text
    d: JSONDict = {"text": s.text}
    if st:
        for k in ("bold", "italic", "underline", "strike"):
            if getattr(st, k):
                d[k] = True
        for k in ("color", "background"):
            if getattr(st, k):
                d[k] = getattr(st, k)
        if st.size:
            d["size"] = str(getattr(st.size, "value", st.size))
    if s.link:
        d["link"] = s.link
    return d


def _para_spec(p: Paragraph) -> Any:
    spans = [_span_spec(s) for s in p.spans]
    if not p.align and len(spans) == 1 and isinstance(spans[0], str):
        return spans[0]
    d: JSONDict = {"spans": spans}
    if p.align:
        d["align"] = str(getattr(p.align, "value", p.align))
    return d


def paragraphs_spec(ps: Sequence[Paragraph]) -> Any:
    """문단 목록 -> 서식 없으면 "줄\\n줄" 문자열, 있으면 배열"""
    items = [_para_spec(p) for p in ps]
    if all(isinstance(i, str) and "\n" not in i for i in items):
        return "\n".join(items)
    return items


def _v(x: Any) -> Any:
    return getattr(x, "value", x)


def _image_spec(i: Image) -> JSONDict:
    d: JSONDict = {"type": "image"}
    up = i.uploaded
    if up is not None:
        d["uploaded"] = {"url": up.url, "path": up.path, "domain": up.domain, "file_name": up.file_name,
                         "width": up.width, "height": up.height, "file_size": up.file_size}
    elif isinstance(i.source, str):
        d["source"] = i.source
    else:
        d["source"] = str(i.source) if hasattr(i.source, "__fspath__") else None  # bytes 는 spec 에 못 담는다
    if i.caption:
        d["caption"] = paragraphs_spec(i.caption)
    if i.link:
        d["link"] = i.link
    if i.represent:
        d["represent"] = True
    return d


def to_spec(block: Block, *, ids: bool = False) -> JSONDict:
    """블록 -> spec dict (ids=True 면 "id" 포함)"""
    t = TYPE_OF.get(type(block))
    if t is None:
        raise SpecError(f"spec 으로 바꿀 수 없는 블록입니다: {type(block).__name__}")
    d: JSONDict = {"type": t}
    if isinstance(block, Text | Heading):
        d["content"] = paragraphs_spec(block.content)
    elif isinstance(block, Quote):
        d["content"] = paragraphs_spec(block.content)
        if block.source:
            d["source"] = paragraphs_spec(block.source)
        d["layout"] = _v(block.layout)
    elif isinstance(block, Divider):
        d["layout"] = _v(block.layout)
    elif isinstance(block, Code):
        d["code"] = block.code
        d["layout"] = _v(block.layout)
        if block.font_size:
            d["font_size"] = _v(block.font_size)
    elif isinstance(block, Table):
        d["rows"] = [[_cell_spec(c) for c in r.cells] for r in block.rows]
    elif isinstance(block, Image):
        d = _image_spec(block)
    elif isinstance(block, ImageGroup | ImageStrip):
        d["images"] = [_image_spec(i) for i in block.items]
        if isinstance(block, ImageGroup):
            d["layout"] = _v(block.layout)
    elif isinstance(block, Sticker):
        d.update(pack_code=block.pack_code, seq=block.seq, width=block.width, height=block.height,
                 animated=block.animated)
        if block.url:
            d["url"] = block.url
    elif isinstance(block, LinkCard):
        d.update(url=block.url, title=block.title, description=block.description, layout=_v(block.layout))
        if block.thumbnail:
            d["thumbnail"] = {"src": block.thumbnail.src, "width": block.thumbnail.width,
                              "height": block.thumbnail.height}
        if block.sign:
            d["sign"] = block.sign
    elif isinstance(block, RawBlock):
        d["data"] = block.to_dict()
    if ids:
        d["id"] = block.id
    return d


def _cell_spec(c: Cell) -> Any:
    content = paragraphs_spec(c.content)
    if c.col_span == 1 and c.row_span == 1 and not c.background and not c.align and isinstance(content, str):
        return content
    d: JSONDict = {"content": content}
    if c.col_span != 1:
        d["col_span"] = c.col_span
    if c.row_span != 1:
        d["row_span"] = c.row_span
    if c.background:
        d["background"] = c.background
    if c.align:
        d["align"] = _v(c.align)
    return d


# ---------------------------------------------------------------- spec -> 블록


def _span_from(v: Any) -> Span:
    if isinstance(v, str):
        return Span(v)
    d = as_dict(v)
    if "text" not in d:
        raise SpecError(f"글자 조각에는 text 가 있어야 합니다: {v!r}")
    return Span(str(d["text"]), link=d.get("link") or None,
                style=TextStyle(bold=bool(d.get("bold")), italic=bool(d.get("italic")),
                                underline=bool(d.get("underline")), strike=bool(d.get("strike")),
                                color=d.get("color") or None, background=d.get("background") or None,
                                size=d.get("size") or None))


def paragraphs_from(v: Any) -> list[Paragraph]:
    """spec 문단 (문자열 / [문자열 | {"spans", "align"}]) -> 문단 목록"""
    if v is None:
        return []
    if isinstance(v, str):
        return Text(v).paragraphs
    if not isinstance(v, list):
        raise SpecError(f"문단은 문자열 또는 배열이어야 합니다: {type(v).__name__}")
    out: list[Paragraph] = []
    for item in v:
        if isinstance(item, str):
            out.extend(Text(item).paragraphs)
        else:
            d = as_dict(item)
            spans = d.get("spans")
            if not isinstance(spans, list):
                raise SpecError(f"문단 객체에는 spans 배열이 있어야 합니다: {item!r}")
            out.append(Paragraph([_span_from(s) for s in spans], d.get("align") or None))
    return out


def _image_from(d: JSONDict) -> Image:
    up = as_dict(d.get("uploaded"))
    source: Any = (UploadedImage(url=str(up.get("url") or ""), path=str(up.get("path") or ""),
                                 domain=str(up.get("domain") or ""), file_name=str(up.get("file_name") or ""),
                                 width=as_int(up.get("width")), height=as_int(up.get("height")),
                                 file_size=as_int(up.get("file_size")))
                   if up else d.get("source"))
    cap = d.get("caption")
    return Image(source, represent=bool(d.get("represent")) or None, link=d.get("link") or None,
                 caption=paragraphs_from(cap) if cap else None)


def from_spec(item: Any) -> Block:
    """spec dict -> 블록. 형식·값 오류는 전부 SpecError (블록 검사 ValueError/TypeError 포함)"""
    if not isinstance(item, Mapping):
        raise SpecError(f"블록은 객체여야 합니다: {type(item).__name__}")
    try:
        return _from_spec(dict(item))
    except SpecError:
        raise
    except (ValueError, TypeError) as e:
        raise SpecError(f"{item.get('type')} 블록: {e}") from e


def _from_spec(item: JSONDict) -> Block:
    d = as_dict(item)
    t = d.get("type")
    if t not in CLASS_OF:
        raise SpecError(f"알 수 없는 블록 type 입니다: {t!r} (가능: {sorted(CLASS_OF)})")
    kw: JSONDict = {"id": d["id"]} if d.get("id") else {}
    if t == "text":
        return Text(paragraphs_from(d.get("content", "")), **kw)
    if t == "heading":
        return Heading(paragraphs_from(d.get("content", "")), **kw)
    if t == "quote":
        src = d.get("source")
        return Quote(paragraphs_from(d.get("content", "")), paragraphs_from(src) if src else None,
                     d.get("layout") or QuotationLayout.DEFAULT, **kw)
    if t == "divider":
        return Divider(d.get("layout") or LineLayout.DEFAULT, **kw)
    if t == "code":
        return Code(str(d.get("code") or ""), d.get("layout") or CodeLayout.DEFAULT, d.get("font_size") or None, **kw)
    if t == "table":
        rows = d.get("rows")
        if not isinstance(rows, list):
            raise SpecError("table 에는 rows 배열이 있어야 합니다")
        return Table([TableRow([_cell_from(c) for c in as_list_strict(r, "표 줄")]) for r in rows], **kw)
    if t == "image":
        img = _image_from(d)
        if kw:
            img.id = kw["id"]
        return img
    if t in ("image_group", "image_strip"):
        imgs = [_image_from(as_dict(i)) for i in as_list_strict(d.get("images"), "images")]
        if t == "image_group":
            return ImageGroup(imgs, d.get("layout") or ImageGroupLayout.SLIDE, **kw)
        return ImageStrip(imgs, **kw)
    if t == "sticker":
        return Sticker(str(d.get("pack_code") or ""), as_int(d.get("seq")), as_int(d.get("width"), 185),
                       as_int(d.get("height"), 160), d.get("url") or None, bool(d.get("animated")), **kw)
    if t == "link_card":
        th = as_dict(d.get("thumbnail"))
        return LinkCard(str(d.get("url") or ""), str(d.get("title") or ""), "", str(d.get("description") or ""),
                        Thumbnail(src=str(th["src"]), width=as_int(th.get("width")), height=as_int(th.get("height")))
                        if th.get("src") else None,
                        d.get("sign") or None, layout=d.get("layout") or LinkCardLayout.LARGE_IMAGE, **kw)
    return RawBlock(dict(as_dict(d.get("data"))), **kw)


def as_list_strict(v: Any, what: str) -> list[Any]:
    if not isinstance(v, list):
        raise SpecError(f"{what} 는 배열이어야 합니다: {type(v).__name__}")
    return v


def _cell_from(v: Any) -> Cell:
    if isinstance(v, str):
        return Cell(v)
    d = as_dict(v)
    return Cell(paragraphs_from(d.get("content", "")), as_int(d.get("col_span"), 1), as_int(d.get("row_span"), 1),
                background=d.get("background") or None, align=d.get("align") or None)


def document_to_spec(doc: Document, *, ids: bool = False) -> JSONDict:
    return {"blocks": [to_spec(b, ids=ids) for b in doc.blocks]}


def document_from_spec(data: Any) -> Document:
    """{"blocks": [...]} 또는 [...] -> Document"""
    items = data.get("blocks") if isinstance(data, Mapping) else data
    blocks: list[Block] = []
    for n, i in enumerate(as_list_strict(items, "blocks")):
        try:
            blocks.append(from_spec(i))
        except SpecError as e:
            raise SpecError(f"blocks[{n}]: {e}") from e
    if not blocks:
        raise SpecError("blocks 가 비어 있습니다")
    return Document(blocks)


# ---------------------------------------------------------------- JSON Schema (자유 작성)


def _enum(e: type[Any]) -> JSONDict:
    return {"type": "string", "enum": [m.value for m in e]}


def _defs() -> JSONDict:
    span = {"anyOf": [{"type": "string"}, {
        "type": "object", "required": ["text"], "additionalProperties": False, "properties": {
            "text": {"type": "string"}, "bold": {"type": "boolean"}, "italic": {"type": "boolean"},
            "underline": {"type": "boolean"}, "strike": {"type": "boolean"},
            "color": {"type": "string", "description": "#rrggbb"},
            "background": {"type": "string", "description": "#rrggbb"},
            "size": _enum(FontSize), "link": {"type": "string", "description": "http(s) 주소"}}}]}
    para = {"anyOf": [{"type": "string"}, {
        "type": "object", "required": ["spans"], "additionalProperties": False, "properties": {
            "spans": {"type": "array", "items": {"$ref": "#/$defs/span"}}, "align": _enum(Align)}}]}
    paras = {"description": "문자열(줄바꿈 = 문단) 또는 문단 배열",
             "anyOf": [{"type": "string"}, {"type": "array", "items": {"$ref": "#/$defs/paragraph"}}]}
    cell = {"anyOf": [{"type": "string"}, {
        "type": "object", "required": ["content"], "additionalProperties": False, "properties": {
            "content": {"$ref": "#/$defs/paragraphs"}, "col_span": {"type": "integer", "minimum": 1},
            "row_span": {"type": "integer", "minimum": 1}, "background": {"type": "string"}, "align": _enum(Align)}}]}
    image = _obj("image", {"source": {"type": "string", "description": "사진 파일 경로"},
                           "caption": {"$ref": "#/$defs/paragraphs"}, "link": {"type": "string"},
                           "uploaded": {"type": "object"}, "represent": {"type": "boolean"}}, [])

    blocks = {
        "text": _obj("text", {"content": {"$ref": "#/$defs/paragraphs"}}, ["content"]),
        "heading": _obj("heading", {"content": {"$ref": "#/$defs/paragraphs"}}, ["content"]),
        "quote": _obj("quote", {"content": {"$ref": "#/$defs/paragraphs"}, "source": {"$ref": "#/$defs/paragraphs"},
                                "layout": _enum(QuotationLayout)}, ["content"]),
        "divider": _obj("divider", {"layout": _enum(LineLayout)}, []),
        "code": _obj("code", {"code": {"type": "string"}, "layout": _enum(CodeLayout), "font_size": _enum(FontSize)},
                     ["code"]),
        "table": _obj("table", {"rows": {"type": "array", "minItems": 1,
                                         "items": {"type": "array", "items": {"$ref": "#/$defs/cell"}}}}, ["rows"]),
        "image": image,
        "image_group": _obj("image_group", {"images": {"type": "array", "minItems": 2, "items": image},
                                            "layout": _enum(ImageGroupLayout)}, ["images"]),
        "image_strip": _obj("image_strip", {"images": {"type": "array", "minItems": 2, "items": image}}, ["images"]),
        "sticker": _obj("sticker", {"pack_code": {"type": "string"}, "seq": {"type": "integer", "minimum": 1},
                                    "width": {"type": "integer"}, "height": {"type": "integer"},
                                    "animated": {"type": "boolean"}, "url": {"type": "string"}}, ["pack_code", "seq"]),
        "link_card": _obj("link_card", {"url": {"type": "string"}, "title": {"type": "string"},
                                        "description": {"type": "string"}, "layout": _enum(LinkCardLayout),
                                        "thumbnail": {"type": "object", "properties": {
                                            "src": {"type": "string"}, "width": {"type": "integer"},
                                            "height": {"type": "integer"}}, "required": ["src"]},
                                        "sign": {"type": "string", "description": "서버 서명 (cafe.editor.link_card)"}},
                          ["url"]),
    }
    return {"span": span, "paragraph": para, "paragraphs": paras, "cell": cell,
            **{f"block_{k}": v for k, v in blocks.items()},
            "block": {"anyOf": [{"$ref": f"#/$defs/block_{k}"} for k in blocks]}}


def _obj(t: str, props: JSONDict, required: list[str]) -> JSONDict:
    return {"type": "object", "additionalProperties": False, "required": ["type", *required],
            "properties": {"type": {"const": t}, **props, "id": {"type": "string"}}}


def document_schema() -> JSONDict:
    """자유 작성용 JSON Schema ({"blocks": [블록...]}). raw 블록은 넣지 않는다 (AI 가 만들 대상이 아님)"""
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "caffeinate Document",
            "type": "object", "additionalProperties": False, "required": ["blocks"],
            "properties": {"blocks": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/block"}}},
            "$defs": _defs()}


# ---------------------------------------------------------------- 템플릿 채우기


def _text_field(hint: str | None, rich: bool) -> JSONDict:
    f: JSONDict = ({"$ref": "#/$defs/paragraphs"} if rich else
                   {"type": "string", "description": "줄바꿈은 문단 구분"})
    if hint:
        f = {**f, "description": hint} if not rich else {"allOf": [f], "description": hint}
    return f


def _fill_fields(b: Block, rich: bool) -> JSONDict | None:
    """블록의 채울 칸 -> properties (없으면 None)"""
    h = b.hint
    if isinstance(b, Text | Heading):
        return {"content": _text_field(h, rich)}
    if isinstance(b, Quote):
        props = {"content": _text_field(h, rich)}
        if b.source is not None:
            props["source"] = _text_field("출처", rich)
        return props
    if isinstance(b, Code):
        return {"code": {"type": "string", **({"description": h} if h else {})}}
    if isinstance(b, Table):
        cols = [len(r.cells) for r in b.rows]
        rows = [{"type": "array", "minItems": n, "maxItems": n, "items": {"type": "string"}} for n in cols]
        same = len(set(cols)) == 1
        return {"rows": {"type": "array", "minItems": len(rows), "maxItems": len(rows),
                         "items": rows[0] if same else {"type": "array", "items": {"type": "string"}},
                         "description": (h + " - " if h else "") + f"{len(rows)}줄 x 칸 수 {cols} (줄마다 칸 수 고정)"}}
    if isinstance(b, Image) and h:
        return {"caption": {"type": "string", "description": h}}
    return None


def fill_keys(doc: Document) -> list[tuple[str, int]]:
    """채울 블록 키 ("{순번}_{type}") 와 블록 위치"""
    return [(f"{i}_{TYPE_OF.get(type(b), 'raw')}", i) for i, b in enumerate(doc.blocks)
            if _fill_fields(b, False) is not None]


def fill_schema(doc: Document, *, rich: bool = False) -> JSONDict:
    """템플릿 고정 JSON Schema - 채울 칸만, 키는 "{순번}_{type}" (모든 칸 필수, 추가 키 금지)

    rich=True 면 글 칸에 서식 있는 문단 배열도 허용한다 (기본은 문자열).
    """
    props: JSONDict = {}
    for key, i in fill_keys(doc):
        b = doc.blocks[i]
        fields = _fill_fields(b, rich) or {}
        props[key] = {"type": "object", "additionalProperties": False, "required": list(fields),
                      "properties": fields, **({"description": b.hint} if b.hint else {})}
    schema: JSONDict = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "caffeinate Fill",
                        "type": "object", "additionalProperties": False, "required": list(props), "properties": props}
    if rich:
        defs = _defs()
        schema["$defs"] = {k: defs[k] for k in ("span", "paragraph", "paragraphs")}
    return schema


def fill(doc: Document, data: Any, *, strict: bool = True) -> Document:
    """템플릿 + AI 가 채운 JSON -> 같은 구조의 새 Document (원본은 그대로)

    data: fill_schema 형식 {"0_heading": {...}, ...}. strict 면 칸 누락·모르는 키·표 크기 불일치를 ValueError 로.
    """
    d = as_dict(data)
    keys = dict(fill_keys(doc))
    if strict:
        missing = [k for k in keys if k not in d]
        unknown = [k for k in d if k not in keys]
        if missing or unknown:
            raise SpecError(f"채우기 결과가 템플릿과 다릅니다 (빠짐: {missing}, 모름: {unknown})")
    out = Document([copy.deepcopy(b) for b in doc.blocks], version=doc.version, theme=doc.theme,
                   language=doc.language, extra=dict(doc.extra))
    for key, i in keys.items():
        if key not in d:
            continue
        if not isinstance(d[key], Mapping):
            raise SpecError(f"{key}: 객체여야 합니다")
        try:
            _apply(out.blocks[i], dict(d[key]), strict)
        except SpecError as e:
            raise SpecError(f"{key}: {e}") from e
        except (ValueError, TypeError) as e:
            raise SpecError(f"{key}: {e}") from e
    for tb, nb in zip(doc.blocks, out.blocks, strict=True):
        _keep_sources(tb, nb)
    return out


def _keep_sources(tpl: Block, new: Block) -> None:
    """deepcopy 로 복사된 사진 원본(bytes 등)을 템플릿 객체 그대로 공유 (큰 데이터 복사 방지)"""
    for a, b in zip(tpl.images(), new.images(), strict=False):
        b.source = a.source


def _apply(b: Block, item: JSONDict, strict: bool) -> None:
    if isinstance(b, Text | Heading | Quote) and "content" in item:
        b.content = paragraphs_from(item["content"])
    if isinstance(b, Quote) and "source" in item:
        b.source = paragraphs_from(item["source"]) or None
    if isinstance(b, Code) and "code" in item:
        b.code = str(item["code"])
    if isinstance(b, Image) and "caption" in item:
        b.caption = paragraphs_from(item["caption"]) or None
    if isinstance(b, Table) and "rows" in item:
        rows = as_list_strict(item["rows"], "rows")
        if strict and (len(rows) != len(b.rows) or any(
                len(as_list_strict(r, "표 줄")) != len(tr.cells) for r, tr in zip(rows, b.rows, strict=False))):
            raise SpecError(f"표 크기가 템플릿과 다릅니다: {[len(r.cells) for r in b.rows]}")
        for r, tr in zip(rows, b.rows, strict=False):
            for v, cell in zip(r, tr.cells, strict=False):
                cell.content = paragraphs_from(v if not isinstance(v, Mapping) else v.get("content", ""))
