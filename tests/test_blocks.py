import sys

"""models/blocks.py - 글쓰기 블록 dataclass, to_dict/from_dict, 예외 [실측 2026-11-24 형식 기준]"""
import json
from typing import Any

import pytest

from caffeinate import (
    Align,
    Block,
    Cell,
    Code,
    CodeLayout,
    Divider,
    Document,
    FontFamily,
    FontSize,
    Heading,
    Image,
    ImageGroup,
    ImageGroupLayout,
    ImageStrip,
    LineLayout,
    LinkCard,
    Paragraph,
    ParagraphDefaults,
    QuotationLayout,
    Quote,
    RawBlock,
    Span,
    Sticker,
    Table,
    Text,
    TextStyle,
    UploadedImage,
    paragraphs,
)
from caffeinate.services.articles import document_of
from caffeinate.services.comments import _sticker_id
from caffeinate.utils.editor import build_content_json


def _img(name: str = "a.png") -> UploadedImage:
    return UploadedImage(url=f"/h/{name}", path="/h", domain="https://cafeptthumb-phinf.pstatic.net",
                         file_name=name, file_size=10, width=64, height=48)


def _roundtrip(block: Block) -> None:
    d = block.to_dict()
    again = Block.from_dict(d)
    assert type(again) is type(block)
    assert again.to_dict() == d


# ---------------------------------------------------------------- 텍스트


def test_span_style_shortcuts_and_dict() -> None:
    s = Span("굵게", bold=True, color="#ff0000", size=FontSize.FS24)
    d = s.to_dict()
    assert d["style"] == {"bold": True, "fontColor": "#ff0000", "fontSizeCode": "fs24", "@ctype": "nodeStyle"}
    assert d["@ctype"] == "textNode" and list(d)[-1] == "@ctype"
    assert Span.from_dict(d).style == s.style


def test_span_link_and_plain() -> None:
    d = Span("링크", link="https://naver.com").to_dict()
    assert d["link"] == {"url": "https://naver.com", "@ctype": "urlLink"}
    assert "style" not in Span("plain").to_dict()


@pytest.mark.parametrize("kw", [
    {"color": "red"}, {"color": "#ggg000"}, {"background": "red;x"}, {"size": "fs999"},
])
def test_text_style_rejects_values_server_drops(kw: dict[str, Any]) -> None:
    # 실측: 목록 밖 글자 크기/색은 서버가 조용히 버린다 -> 로컬에서 ValueError
    with pytest.raises(ValueError):
        TextStyle(**kw)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://x", "naver.com"])
def test_span_rejects_non_http_link(url: str) -> None:
    with pytest.raises(ValueError):  # 실측: javascript: 는 서버가 href="" 로 비운다
        Span("x", link=url)


def test_span_rejects_non_str() -> None:
    with pytest.raises(TypeError):
        Span(123)  # type: ignore[arg-type]


def test_colors_accepted() -> None:
    TextStyle(color="#fff", background="rgb(1, 2, 3)")
    TextStyle(color="rgba(1,2,3,0.5)")


def test_paragraphs_input_forms() -> None:
    assert [p.text for p in paragraphs("a\r\nb\rc\n\nd")] == ["a", "b", "c", "", "d"]
    ps = paragraphs(["첫\n둘", [Span("굵", bold=True), "보통"], Paragraph([Span("p")], Align.CENTER)])
    assert [p.text for p in ps] == ["첫", "둘", "굵보통", "p"]
    assert ps[3].to_dict()["style"] == {"align": "center", "@ctype": "paragraphStyle"}
    assert paragraphs(None) == []
    assert Paragraph([]).to_dict()["nodes"][0]["value"] == ""  # 빈 줄 = 빈 textNode


def test_text_block_shape() -> None:
    d = Text("첫 줄\n\n셋째").to_dict()
    assert list(d) == ["id", "layout", "value", "@ctype"]
    assert [p["nodes"][0]["value"] for p in d["value"]] == ["첫 줄", "", "셋째"]


# ---------------------------------------------------------------- 블록별 모양 (실측 형식)


def test_heading_quote_divider_code_shapes() -> None:
    assert Heading("소제목").to_dict()["title"][0]["nodes"][0]["value"] == "소제목"
    q = Quote("인용", source="출처", layout=QuotationLayout.LINE).to_dict()
    assert q["layout"] == "quotation_line" and q["source"][0]["nodes"][0]["value"] == "출처"
    assert "source" not in Quote("x").to_dict()
    c = Code("print(1)\nx = 2", CodeLayout.BLACK, FontSize.FS16).to_dict()
    assert c["codeContents"] == "print(1)\nx = 2" and c["layout"] == "code_black" and c["fontSizeCode"] == "fs16"
    assert "fontSizeCode" not in Code("x").to_dict()


def test_divider_exact() -> None:
    assert Divider(LineLayout.LINE2, id="SE-1").to_dict() == {"id": "SE-1", "layout": "line2", "@ctype": "horizontalLine"}


def test_custom_layout_string_allowed() -> None:
    # 실측: 서버는 layout 을 검사하지 않는다 -> enum 밖 문자열도 그대로
    assert Quote("x", layout="my_layout").to_dict()["layout"] == "my_layout"
    assert Block.from_dict(Quote("x", layout="my_layout").to_dict()).layout == "my_layout"  # type: ignore[attr-defined]


def test_table_widths_and_columns() -> None:
    t = Table([["가", "나"], [Cell("합침", col_span=2, background="#eeeeee", align=Align.CENTER)]])
    d = t.to_dict()
    assert d["width"] == 100 and d["columnCount"] == 2  # 실측: 표 width 빠지면 500
    r0, r1 = d["rows"]
    assert [c["width"] for c in r0["cells"]] == [50.0, 50.0]
    assert r1["cells"][0]["width"] == 100.0 and r1["cells"][0]["colSpan"] == 2
    assert r1["cells"][0]["backgroundColor"] == "#eeeeee" and r1["cells"][0]["textAlign"] == "center"
    assert r0["@ctype"] == "tableRow" and r0["cells"][0]["@ctype"] == "tableCell"
    assert r0["cells"][0]["value"][0]["nodes"][0]["value"] == "가"  # 칸 값은 문단 배열


@pytest.mark.parametrize("rows", [[], [[]]])
def test_table_requires_cells(rows: list[Any]) -> None:
    with pytest.raises(ValueError):
        Table(rows)


def test_cell_span_validation() -> None:
    with pytest.raises(ValueError):
        Cell("x", col_span=0)


def test_image_requires_upload_before_dict() -> None:
    img = Image(b"\x89PNG")
    assert img.uploaded is None
    with pytest.raises(ValueError, match="업로드"):
        img.to_dict()
    with pytest.raises(ValueError):
        Image(None)
    with pytest.raises(ValueError):
        Image(_img(), link="javascript:x")


def test_image_dict_matches_capture_shape() -> None:
    d = Image(_img(), link="https://naver.com").to_dict()
    assert d["path"] == "/h/a.png" and d["src"].endswith("/h/a.png?type=w1600")
    assert d["internalResource"] is True and d["link"] == "https://naver.com"


def test_image_group_and_strip() -> None:
    g = ImageGroup([_img("1.png"), _img("2.png")], ImageGroupLayout.COLLAGE).to_dict()
    assert g["layout"] == "collage" and [i["layout"] for i in g["images"]] == ["default", "default"]
    assert ImageStrip([_img("1.png"), _img("2.png")]).to_dict()["@ctype"] == "imageStrip"
    with pytest.raises(ValueError):
        ImageGroup([_img()])


def test_sticker_forms() -> None:
    api_item = {"seq": 1, "stickerCode": "cafe_001-1", "imageWidth": 185, "imageHeight": 160,
                "originalUrl": "https://storep-phinf.pstatic.net/cafe_001/original_1.gif"}
    st = Sticker.from_api(api_item, pack_code="cafe_001")
    assert st.code == "cafe_001-1" and st.comment_id == "cafe_001-1-185-160" and st.animated
    d = st.to_dict()
    assert d["packCode"] == "cafe_001" and d["seq"] == 1 and d["format"] == "animated"
    assert d["thumbnail"] == {"src": api_item["originalUrl"], "width": 185, "height": 160, "@ctype": "thumbnail"}
    parsed = Sticker.parse("motion3d_02-5-185-160")
    assert (parsed.pack_code, parsed.seq, parsed.width, parsed.height) == ("motion3d_02", 5, 185, 160)
    assert Sticker("p", 2).image_url.endswith("/p/original_2.png")
    with pytest.raises(ValueError):
        Sticker("", 1)
    with pytest.raises(ValueError):
        Sticker("p", 0)
    with pytest.raises(ValueError):
        Sticker.parse("nope")


def test_comment_sticker_id() -> None:
    assert _sticker_id(Sticker("cafe_001", 3, 185, 160)) == "cafe_001-3-185-160"
    assert _sticker_id("x-1-2-3") == "x-1-2-3"
    assert _sticker_id("") == ""


def test_link_card_from_api() -> None:
    data = {"oglink": {"url": "https://www.naver.com", "summary": {
        "domain": "www.naver.com", "url": "https://www.naver.com/", "title": "네이버", "description": "설명",
        "image": {"url": "https://s.pstatic.net/x.png", "width": 270, "height": 270}}}, "oglinkSign": "SIG"}
    card = LinkCard.from_api(data)
    d = card.to_dict()
    assert d["link"] == "https://www.naver.com" and d["oglinkSign"] == "SIG" and d["video"] is False
    assert d["thumbnail"]["src"] == "https://s.pstatic.net/x.png"
    assert LinkCard("https://a.com/b").domain == "a.com"
    with pytest.raises(ValueError):
        LinkCard.from_api({"oglink": {"error": {"code": "x"}}})
    with pytest.raises(ValueError):
        LinkCard("javascript:x")


# ---------------------------------------------------------------- 왕복 / 커스텀


@pytest.mark.parametrize("block", [
    Text(["a", [Span("b", bold=True, link="https://x.com"), Span("c", italic=True)]]),
    Heading("h"),
    Quote("q", source="s", layout=QuotationLayout.BUBBLE),
    Divider(LineLayout.LINE7),
    Code("x", CodeLayout.STRIPE, FontSize.FS13),
    Table([["a", Cell("b", background="#000000")], ["c", "d"]], border_style="thinLine"),
    Image(_img(), represent=True),
    ImageGroup([_img("1"), _img("2")]),
    ImageStrip([_img("1"), _img("2")]),
    Sticker("cafe_001", 1, 185, 160, animated=True),
    LinkCard("https://a.com", title="t", sign="s"),
    RawBlock({"@ctype": "audio", "layout": "default", "audioId": "x"}),
])
def test_roundtrip(block: Block) -> None:
    _roundtrip(block)


def test_unknown_keys_preserved_in_extra() -> None:
    raw = Divider(id="SE-1").to_dict() | {"align": "center", "future": {"a": 1}}
    b = Block.from_dict(raw)
    assert b.extra == {"align": "center", "future": {"a": 1}}
    assert b.to_dict() == raw


def test_extra_overrides_defaults() -> None:
    d = Image(_img(), extra={"format": "custom", "caption": [{"x": 1}]}).to_dict()
    assert d["format"] == "custom" and d["caption"] == [{"x": 1}] and d["@ctype"] == "image"
    s = Span("x", extra={"value": "덮어씀"}).to_dict()
    assert s["value"] == "덮어씀"


def test_unknown_ctype_becomes_raw_and_raw_fills_id() -> None:
    b = Block.from_dict({"@ctype": "schedule", "title": "x"})
    assert isinstance(b, RawBlock)
    d = b.to_dict()
    assert d["id"].startswith("SE-") and list(d)[-1] == "@ctype"  # 실측: id 없으면 500
    with pytest.raises(ValueError):
        RawBlock({"no": "ctype"})


def test_typed_from_dict_checks_ctype() -> None:
    assert isinstance(Text.from_dict(Text("x").to_dict()), Text)
    with pytest.raises(ValueError):
        Text.from_dict(Divider().to_dict())


def test_registry_holds_final_classes() -> None:
    for ctype, cls in Block._REGISTRY.items():
        assert getattr(sys.modules[cls.__module__], cls.__name__) is cls, ctype


def test_style_extra_and_unknown_font_size_preserved() -> None:
    raw = {"id": "n", "value": "x", "style": {"bold": True, "fontSizeCode": "fs999", "fontFamily": "nanumgothic",
                                                "@ctype": "nodeStyle"}, "@ctype": "textNode"}
    assert Span.from_dict(raw).to_dict() == raw


def test_paragraph_style_extra_preserved() -> None:
    raw = {"id": "p", "nodes": [{"id": "n", "value": "x", "@ctype": "textNode"}],
           "style": {"align": "right", "lineHeight": 2, "@ctype": "paragraphStyle"}, "@ctype": "paragraph"}
    assert Paragraph.from_dict(raw).to_dict() == raw


def test_non_http_link_from_server_preserved() -> None:
    raw = {"id": "n", "value": "x", "link": {"url": "mailto:a@b.c", "@ctype": "urlLink"}, "@ctype": "textNode"}
    assert Span.from_dict(raw).to_dict() == raw


# ---------------------------------------------------------------- 문서


def test_document_dict_and_json_roundtrip() -> None:
    doc = Document([Heading("h"), "본문\n\n둘째", Image(_img("1.png")), Divider(), Image(_img("2.png"))])
    d = doc.to_dict()["document"]
    assert [c["@ctype"] for c in d["components"]] == ["sectionTitle", "text", "image", "horizontalLine", "image"]
    assert [c["represent"] for c in d["components"] if c["@ctype"] == "image"] == [True, False]
    # dio: 텍스트 1 + 사진 1 (사진 수와 무관 - 실측)
    assert d["di"]["dio"] == [{"dis": "N", "dia": {"t": 0, "p": 0, "st": len("본문\n둘째".encode()), "sk": 1}},
                              {"dis": "N", "dia": {"t": 0, "p": 0, "st": 0, "sk": 0}}]
    again = Document.from_json(doc.to_json())
    assert again.to_dict() == doc.to_dict()
    assert again.text == "본문\n\n둘째"  # 본문 글자 (Text/Table)


def test_document_dio_without_text_or_images() -> None:
    d = Document([Divider()]).to_dict()["document"]
    assert d["di"]["dio"] == [{"dis": "N", "dia": {"t": 0, "p": 0, "st": 0, "sk": 1}}]
    only_img = Document([Image(_img())]).to_dict()["document"]
    assert only_img["di"]["dio"] == [{"dis": "N", "dia": {"t": 0, "p": 0, "st": 0, "sk": 0}}]


def test_document_errors() -> None:
    with pytest.raises(ValueError):
        Document([]).to_dict()
    with pytest.raises(TypeError):
        Document([123])
    with pytest.raises(ValueError):
        Document.from_text("")


def test_document_pending_images_includes_groups() -> None:
    doc = Document([Image(b"a"), ImageGroup([_img("1"), b"b"]), Image(_img())])
    assert [i.source for i in doc.pending_images()] == [b"a", b"b"]


def test_build_content_json_compat() -> None:
    d = json.loads(build_content_json("본문", [_img("1.png"), _img("2.png")]))["document"]
    assert [c["@ctype"] for c in d["components"]] == ["text", "image", "image"]
    assert len(d["di"]["dio"]) == 2


def test_document_of_inputs() -> None:
    assert [type(b) for b in document_of("x").blocks] == [Text]
    assert document_of("").blocks == []
    assert [type(b) for b in document_of(Divider()).blocks] == [Divider]
    assert [type(b) for b in document_of([Heading("h"), "t"]).blocks] == [Heading, Text]
    src = Document([Text("a")])
    copy = document_of(src)
    copy.blocks.append(Divider())
    assert len(src.blocks) == 1  # 원본 문서를 바꾸지 않는다


def test_comment_sticker_parsed() -> None:
    from caffeinate.models.comment import Comment

    # 실측 2026-11-24 댓글 응답 (줄임)
    c = Comment.from_api({"id": 1, "content": "", "sticker": {
        "id": "cafe_001-2-185-160", "packCode": "cafe_001", "url": "https://storep-phinf.pstatic.net/cafe_001/original_2.gif",
        "type": "pa100_100", "animation": True, "width": 129, "height": 112}})
    assert c.sticker is not None and c.sticker.comment_id == "cafe_001-2-185-160" and c.sticker.animated
    assert c.sticker.image_url.endswith("original_2.gif")
    assert Comment.from_api({"id": 2}).sticker is None
    assert Comment.from_api({"id": 3, "sticker": {"id": "broken"}}).sticker is None


def test_sticker_pack_from_api() -> None:
    from caffeinate import StickerPack

    p = StickerPack.from_api({"packCode": "cafe_001", "isFree": True, "isAnimated": True, "stickerCount": 24,
                              "packOrder": 1, "stickerType": "common"})
    assert (p.pack_code, p.animated, p.count, p.order, p.type) == ("cafe_001", True, 24, 1, "common")


def test_image_caption_roundtrip() -> None:
    d = Image(_img(), caption="사진 설명").to_dict()
    assert d["caption"][0]["nodes"][0]["value"] == "사진 설명" and d["caption"][0]["@ctype"] == "paragraph"
    assert Image(_img()).to_dict()["caption"] is None
    _roundtrip(Image(_img(), caption=["a", "b"]))
    odd = Image(_img(), id="i").to_dict() | {"caption": {"weird": 1}}
    assert Block.from_dict(odd).to_dict() == odd


def test_link_card_layouts() -> None:
    from caffeinate import LinkCardLayout

    assert [m.value for m in LinkCardLayout] == ["text", "image", "vertical_image", "large_image"]
    assert LinkCard("https://a.com", layout=LinkCardLayout.TEXT).to_dict()["layout"] == "text"


# ---------------------------------------------------------------- 댓글 블록


def test_comment_draft_byte_limit() -> None:
    from caffeinate import COMMENT_MAX_BYTES, CommentDraft

    assert COMMENT_MAX_BYTES == 6000
    CommentDraft("가" * 3000)   # 실측 OK
    CommentDraft("a" * 6000)    # 실측 OK
    CommentDraft("😀" * 6000)   # 실측 OK - CP949 에 없는 글자는 "?" 1바이트
    for bad in ("가" * 3001, "a" * 6001, "😀" * 6001):  # 실측 400
        with pytest.raises(ValueError):
            CommentDraft(bad)


@pytest.mark.parametrize("body", ["", "   ", []])
def test_comment_draft_empty(body: Any) -> None:
    from caffeinate import CommentDraft

    with pytest.raises(ValueError):
        CommentDraft.of(body)


def test_comment_draft_of_blocks() -> None:
    from caffeinate import CommentDraft

    d = CommentDraft.of([Text(["a", "b"]), "c", Sticker("p", 1), Image(_img())])
    assert d.text == "a\nb\nc" and d.sticker.comment_id == "p-1-185-160" and d.uploaded_image is not None
    assert [type(b) for b in d.to_blocks()] == [Text, Sticker, Image]
    assert CommentDraft.of("x", sticker="p-2-10-20", image=_img()).sticker.width == 10
    again = CommentDraft.of(d)
    assert (again.text, again.sticker, again.image) == (d.text, d.sticker, d.image)


@pytest.mark.parametrize("parts,exc", [
    ([Sticker("p", 1), Sticker("p", 2)], ValueError),
    ([Image(_img()), Image(_img())], ValueError),
    ([Text([[Span("굵게", bold=True)]])], ValueError),
    ([Text([[Span("링크", link="https://a.com")]])], ValueError),
    ([Heading("h")], TypeError),
    ([123], TypeError),
    ([Image(_img(), caption="c")], ValueError),
])
def test_comment_draft_rejects(parts: list[Any], exc: type[Exception]) -> None:
    from caffeinate import CommentDraft

    with pytest.raises(exc):
        CommentDraft.of(parts)


def test_comment_draft_dict_roundtrip_and_extra() -> None:
    from caffeinate import CommentDraft

    d = CommentDraft("hi", "cafe_001-1-185-160", _img(), extra={"custom": "1"})
    f = d.to_dict(7)
    assert list(f) == ["content", "stickerId", "imagePath", "imageFileName", "imageWidth", "imageHeight",
                       "refCommentId", "custom"]
    assert f["imagePath"] == "/h/" and f["refCommentId"] == 7
    again = CommentDraft.from_dict(f)
    assert again.to_dict(7) == f
    assert CommentDraft.from_dict({"content": "x", "stickerId": ""}).sticker is None
    with pytest.raises(ValueError):
        CommentDraft("x", image=b"raw").to_dict()   # 업로드 전
    with pytest.raises(TypeError):
        CommentDraft("x", sticker=123)


def test_document_to_dict_does_not_mutate_represent() -> None:
    a, b = Image(_img("1")), Image(_img("2"))
    d = Document([a, b]).to_dict()["document"]["components"]
    assert [c["represent"] for c in d] == [True, False]
    assert a.represent is None and b.represent is None   # 사용자 객체는 그대로
    c = Image(_img("3"), represent=True)
    d2 = Document([a, c]).to_dict()["document"]["components"]
    assert [x["represent"] for x in d2] == [False, True]


# ---------------------------------------------------------------- 서체 · 줄 간격 · 기본 서식


def test_font_family_and_line_height_like_editor() -> None:
    # 에디터 캡처 [2026-11-24]: 서체 = nodeStyle.fontFamily, 줄 간격 200% = paragraphStyle.lineHeight 2
    p = Paragraph([Span("서식 테스트 문장", font=FontFamily.NANUM_MYEONGJO)], Align.JUSTIFY, 2)
    d = p.to_dict()
    assert d["nodes"][0]["style"] == {"fontFamily": "nanummyeongjo", "@ctype": "nodeStyle"}
    assert d["style"] == {"align": "justify", "lineHeight": 2, "@ctype": "paragraphStyle"}
    back = Paragraph.from_dict(d)
    assert back.line_height == 2 and back.spans[0].style.font is FontFamily.NANUM_MYEONGJO
    assert back.to_dict() == d


def test_font_family_validation_and_unknown_preserved() -> None:
    with pytest.raises(ValueError, match="서체"):
        Span("x", font="comic")
    with pytest.raises(ValueError, match="줄 간격"):
        Paragraph(["x"], line_height=0)
    s = Span.from_dict({"value": "x", "style": {"fontFamily": "bogus", "@ctype": "nodeStyle"}, "@ctype": "textNode"})
    assert s.style.font is None and s.to_dict()["style"]["fontFamily"] == "bogus"
    p = Paragraph.from_dict({"nodes": [], "style": {"lineHeight": "big", "@ctype": "paragraphStyle"},
                             "@ctype": "paragraph"})
    assert p.line_height is None and p.to_dict()["style"]["lineHeight"] == "big"


def test_defaults_priority_span_over_block_over_document() -> None:
    doc = Document([
        Text(["a", [Span("b", font=FontFamily.NANUM_GOTHIC, color="#ff0000")],
              Paragraph(["c"], Align.RIGHT, 1.5)],
             defaults=ParagraphDefaults(style=TextStyle(font=FontFamily.NANUM_SQUARE), line_height=1.8)),
        Heading("h"),
        Quote("q", source="s"),
    ], defaults=ParagraphDefaults(style=TextStyle(font=FontFamily.MARUBURI, color="#333333"),
                                  align=Align.JUSTIFY, line_height=2))
    comps = doc.to_dict()["document"]["components"]
    a, b, c = comps[0]["value"]
    assert a["nodes"][0]["style"] == {"fontFamily": "nanumsquare", "fontColor": "#333333", "@ctype": "nodeStyle"}
    assert a["style"] == {"align": "justify", "lineHeight": 1.8, "@ctype": "paragraphStyle"}
    assert b["nodes"][0]["style"]["fontFamily"] == "nanumgothic" and b["nodes"][0]["style"]["fontColor"] == "#ff0000"
    assert c["style"]["align"] == "right" and c["style"]["lineHeight"] == 1.5
    assert comps[1]["title"][0]["nodes"][0]["style"]["fontFamily"] == "nanummaruburi"
    assert comps[2]["source"][0]["style"]["lineHeight"] == 2
    # 객체는 바뀌지 않는다
    assert doc.blocks[1].content[0].spans[0].style is None
    assert Document.from_dict(doc.to_dict()).to_dict()["document"]["components"] == comps


def test_document_of_keeps_defaults() -> None:
    doc = Document(["a"], defaults=ParagraphDefaults(line_height=2))
    out = document_of(doc)
    assert out is not doc and out.defaults == doc.defaults
    assert out.to_dict()["document"]["components"][0]["value"][0]["style"]["lineHeight"] == 2
