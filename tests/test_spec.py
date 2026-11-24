"""models/spec.py - 블록 <-> spec <-> JSON Schema, 템플릿 채우기 (AI 채우기 흐름)"""
import json
from typing import Any

import pytest

from caffeinate import (
    Align,
    Block,
    Cell,
    Code,
    CodeLayout,
    CommentDraft,
    Divider,
    Document,
    FontSize,
    Heading,
    Image,
    ImageGroup,
    LineLayout,
    LinkCard,
    Paragraph,
    QuotationLayout,
    Quote,
    RawBlock,
    Span,
    SpecError,
    Sticker,
    Table,
    Text,
    UploadedImage,
)
from caffeinate.models.spec import from_spec, to_spec

jsonschema = pytest.importorskip("jsonschema")


def _img(name: str = "a.png") -> UploadedImage:
    return UploadedImage(url=f"/h/{name}", path="/h", domain="https://cafeptthumb-phinf.pstatic.net",
                         file_name=name, file_size=10, width=64, height=48)


def _rich_doc() -> Document:
    return Document([
        Heading("소제목"),
        Text(["보통 문단", [Span("굵게", bold=True), " ", Span("링크", link="https://a.com", color="#ff0000")],
              Paragraph([Span("가운데", size=FontSize.FS24)], Align.CENTER)]),
        Quote("인용", source="출처", layout=QuotationLayout.LINE),
        Divider(LineLayout.LINE3),
        Code("print(1)", CodeLayout.BLACK, FontSize.FS16),
        Table([["a", Cell("b", background="#eeeeee", align=Align.RIGHT)], [Cell("합침", col_span=2)]]),
        Image(_img(), caption="설명", link="https://a.com"),
        Image("photo.png"),
        ImageGroup([_img("1"), _img("2")]),
        Sticker("cafe_001", 1, 185, 160, animated=True),
        LinkCard("https://www.naver.com", title="네이버", sign="SIG"),
    ])


# ---------------------------------------------------------------- spec 왕복


def test_plain_text_spec_is_string() -> None:
    assert to_spec(Text("a\nb")) == {"type": "text", "content": "a\nb"}
    assert to_spec(Table([["a", "b"]])) == {"type": "table", "rows": [["a", "b"]]}
    assert to_spec(Divider()) == {"type": "divider", "layout": "default"}


@pytest.mark.parametrize("block", _rich_doc().blocks + [RawBlock({"@ctype": "audio", "x": 1})])
def test_spec_roundtrip(block: Block) -> None:
    spec = to_spec(block)
    again = from_spec(json.loads(json.dumps(spec)))   # JSON 을 거쳐도 같다
    assert type(again) is type(block)
    assert to_spec(again) == spec


def test_spec_roundtrip_matches_content_json() -> None:
    doc = _rich_doc()
    doc.blocks = [b for b in doc.blocks if not (isinstance(b, Image) and b.uploaded is None)]
    again = Document.from_spec(doc.to_spec(ids=True))
    def strip(v: Any, top: bool = True) -> Any:
        # 블록 id 는 spec 으로 넘어가고, 문단/글자/칸 같은 안쪽 id 는 새로 만든다
        if isinstance(v, dict):
            return {k: strip(x, False) for k, x in v.items() if top or k != "id"}
        if isinstance(v, list):
            return [strip(x, False) for x in v]
        return v

    a, b = doc.to_dict()["document"]["components"], again.to_dict()["document"]["components"]
    assert [c["id"] for c in a] == [c["id"] for c in b]
    assert [strip(c) for c in a] == [strip(c) for c in b]


def test_spec_ids_optional() -> None:
    d = Divider(id="SE-x")
    assert "id" not in to_spec(d) and to_spec(d, ids=True)["id"] == "SE-x"
    assert from_spec({"type": "divider", "id": "SE-y"}).id == "SE-y"


# ---------------------------------------------------------------- 자유 작성 스키마


def test_document_schema_is_valid_and_accepts_spec() -> None:
    schema = Document.json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_rich_doc().to_spec(), schema)
    jsonschema.validate(_rich_doc().to_spec(ids=True), schema)


@pytest.mark.parametrize("bad", [
    {"blocks": []},
    {"blocks": [{"type": "nope"}]},
    {"blocks": [{"type": "text"}]},
    {"blocks": [{"type": "text", "content": "x", "extra_key": 1}]},
    {"blocks": [{"type": "quote", "content": "x", "layout": "not_a_layout"}]},
    {"blocks": [{"type": "table", "rows": "x"}]},
])
def test_document_schema_rejects(bad: Any) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, Document.json_schema())


def test_ai_like_output_to_document() -> None:
    ai = {"blocks": [
        {"type": "heading", "content": "AI 제목"},
        {"type": "text", "content": [{"spans": ["강조: ", {"text": "중요", "bold": True, "color": "#ff0000"}]}]},
        {"type": "table", "rows": [["항목", "값"], ["a", {"content": "1", "align": "center"}]]},
        {"type": "sticker", "pack_code": "cafe_001", "seq": 3},
    ]}
    jsonschema.validate(ai, Document.json_schema())
    doc = Document.from_spec(ai)
    comps = doc.to_dict()["document"]["components"]
    assert [c["@ctype"] for c in comps] == ["sectionTitle", "text", "table", "sticker"]
    assert comps[1]["value"][0]["nodes"][1]["style"]["bold"] is True


@pytest.mark.parametrize("bad", [
    {"blocks": [{"type": "nope"}]},
    {"blocks": [{"type": "text", "content": [{"spans": [{"text": "x", "color": "red"}]}]}]},  # 블록 검사 ValueError
    {"blocks": [{"type": "text", "content": [{"spans": [{"text": "x", "link": "javascript:1"}]}]}]},
    {"blocks": [{"type": "table", "rows": [[]]}]},
    {"blocks": [{"type": "image"}]},
    {"blocks": [{"type": "sticker", "pack_code": "p", "seq": 0}]},
    {"blocks": ["just a string"]},
    {"blocks": []},
    {"nope": 1},
    {"blocks": [{"type": "text", "content": 123}]},
])
def test_from_spec_errors_are_spec_error(bad: Any) -> None:
    with pytest.raises(SpecError):
        Document.from_spec(bad)


def test_spec_error_catchable_as_value_and_type_error() -> None:
    assert issubclass(SpecError, ValueError) and issubclass(SpecError, TypeError)


# ---------------------------------------------------------------- 템플릿 채우기


def _template() -> Document:
    return Document([
        Heading("", hint="글 제목"),
        Text("", hint="세 문단 본문"),
        Image(b"\x89PNG raw", hint="사진 설명 한 줄"),
        Divider(LineLayout.LINE2),
        Quote("", source="", layout=QuotationLayout.BUBBLE),
        Table([["", ""], ["", ""], ["", ""]], hint="장점/단점 표"),
        Code(""),
        Sticker("cafe_001", 1),
        Image(_img()),   # hint 없는 사진은 채울 칸 없음
    ])


def test_fill_schema_shape() -> None:
    schema = _template().fill_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert list(schema["properties"]) == ["0_heading", "1_text", "2_image", "4_quote", "5_table", "6_code"]
    assert schema["required"] == list(schema["properties"]) and schema["additionalProperties"] is False
    assert schema["properties"]["0_heading"]["properties"]["content"]["description"] == "글 제목"
    assert schema["properties"]["2_image"]["properties"]["caption"]["description"] == "사진 설명 한 줄"
    assert set(schema["properties"]["4_quote"]["required"]) == {"content", "source"}
    rows = schema["properties"]["5_table"]["properties"]["rows"]
    assert (rows["minItems"], rows["maxItems"], rows["items"]["minItems"], rows["items"]["maxItems"]) == (3, 3, 2, 2)


def _filled() -> dict[str, Any]:
    return {
        "0_heading": {"content": "채운 제목"},
        "1_text": {"content": "첫 문단\n둘째\n셋째"},
        "2_image": {"caption": "빨간 사진"},
        "4_quote": {"content": "명언", "source": "누군가"},
        "5_table": {"rows": [["구분", "내용"], ["장점", "빠름"], ["단점", "비쌈"]]},
        "6_code": {"code": "x = 1"},
    }


def test_fill_keeps_structure_and_fills_content() -> None:
    tpl = _template()
    data = _filled()
    jsonschema.validate(data, tpl.fill_schema())
    out = tpl.fill(data)
    assert [type(b) for b in out.blocks] == [type(b) for b in tpl.blocks]
    assert [b.id for b in out.blocks] == [b.id for b in tpl.blocks]          # id 유지
    assert out.blocks[0].content[0].text == "채운 제목"                      # type: ignore[attr-defined]
    assert [p.text for p in out.blocks[1].content] == ["첫 문단", "둘째", "셋째"]  # type: ignore[attr-defined]
    assert out.blocks[2].caption[0].text == "빨간 사진"                      # type: ignore[attr-defined]
    assert out.blocks[2].source is tpl.blocks[2].source                      # type: ignore[attr-defined]
    assert out.blocks[3].layout == LineLayout.LINE2                          # type: ignore[attr-defined]
    assert out.blocks[4].layout == QuotationLayout.BUBBLE                    # type: ignore[attr-defined]
    assert out.blocks[5].rows[2].cells[1].content[0].text == "비쌈"          # type: ignore[attr-defined]
    assert out.blocks[7] == tpl.blocks[7]                                    # 스티커 그대로
    assert tpl.blocks[0].content[0].text == ""                               # type: ignore[attr-defined]  원본 불변


def test_fill_keeps_hint_and_extra() -> None:
    tpl = Document([Text("", hint="h", extra={"layout": "custom"})])
    out = tpl.fill({"0_text": {"content": "x"}})
    assert out.blocks[0].hint == "h" and out.to_dict()["document"]["components"][0]["layout"] == "custom"


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("1_text"),
    lambda d: d.update({"9_text": {"content": "x"}}),
    lambda d: d["5_table"].update({"rows": [["a", "b"]]}),
    lambda d: d["5_table"].update({"rows": [["a"], ["b", "c"], ["d", "e"]]}),
    lambda d: d.update({"1_text": "not an object"}),
    lambda d: d.update({"1_text": {"content": 5}}),
])
def test_fill_strict_errors(mutate: Any) -> None:
    data = _filled()
    mutate(data)
    with pytest.raises(SpecError):
        _template().fill(data)


def test_fill_non_strict_allows_partial() -> None:
    out = _template().fill({"0_heading": {"content": "만"}}, strict=False)
    assert out.blocks[0].content[0].text == "만"                             # type: ignore[attr-defined]
    assert out.blocks[1].content[0].text == ""                               # type: ignore[attr-defined]


def test_fill_rich_mode() -> None:
    tpl = Document([Text("", hint="서식 가능")])
    schema = tpl.fill_schema(rich=True)
    jsonschema.Draft202012Validator.check_schema(schema)
    data = {"0_text": {"content": [{"spans": [{"text": "굵", "bold": True}, " 보통"], "align": "center"}]}}
    jsonschema.validate(data, schema)
    out = tpl.fill(data)
    p = out.to_dict()["document"]["components"][0]["value"][0]
    assert p["style"]["align"] == "center" and p["nodes"][0]["style"]["bold"] is True


def test_filled_document_serializes() -> None:
    tpl = _template()
    tpl.blocks[2] = Image(_img("raw.png"), hint="사진 설명 한 줄")   # 업로드된 사진으로 바꿔서 직렬화 가능하게
    out = tpl.fill(_filled())
    comps = out.to_dict()["document"]["components"]
    assert comps[2]["caption"][0]["nodes"][0]["value"] == "빨간 사진"


# ---------------------------------------------------------------- 댓글


def test_comment_schema_and_spec() -> None:
    schema = CommentDraft.json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    spec = {"text": "AI 댓글\n둘째 줄", "sticker": "cafe_001-2-185-160"}
    jsonschema.validate(spec, schema)
    d = CommentDraft.from_spec(spec, image=_img())
    assert d.to_dict()["stickerId"] == "cafe_001-2-185-160" and d.uploaded_image is not None
    assert d.to_spec() == spec
    assert "sticker" not in CommentDraft.json_schema(sticker=False)["properties"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"text": "x", "sticker": "bad id"}, schema)
    with pytest.raises(ValueError):
        CommentDraft.from_spec({"text": ""})          # 빈 댓글
    with pytest.raises(ValueError):
        CommentDraft.from_spec({"other": 1})
    assert CommentDraft.from_spec({"text": "x", "sticker": ""}).sticker is None


def test_spec_font_line_height_and_defaults_roundtrip() -> None:
    from caffeinate import FontFamily, ParagraphDefaults, TextStyle

    spec = {"defaults": {"font": "nanumsquare", "line_height": 1.8, "align": "justify"},
            "blocks": [{"type": "text", "defaults": {"color": "#333333"},
                        "content": [{"spans": [{"text": "명조", "font": "nanummyeongjo"}], "line_height": 2}]},
                       {"type": "quote", "content": "q", "defaults": {"font": "nanummaruburi"}}]}
    doc = Document.from_spec(spec)
    assert doc.defaults == ParagraphDefaults(style=TextStyle(font=FontFamily.NANUM_SQUARE), align="justify",
                                             line_height=1.8)
    assert doc.to_spec()["defaults"] == spec["defaults"]
    assert doc.to_spec()["blocks"][0]["defaults"] == {"color": "#333333"}
    def no_ids(x: object) -> object:
        if isinstance(x, dict):
            return {k: no_ids(v) for k, v in x.items() if k != "id"}
        return [no_ids(v) for v in x] if isinstance(x, list) else x

    assert no_ids(Document.from_spec(doc.to_spec()).to_dict()["document"]["components"]) == \
        no_ids(doc.to_dict()["document"]["components"])
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(spec, Document.json_schema())
    with pytest.raises(SpecError):
        Document.from_spec({"defaults": {"font": "comic"}, "blocks": ["x"]})
