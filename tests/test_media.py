"""파일·동영상·지도·수식·글감·임베드·투표·일정 블록 [실측 2026-11-24 캡처 기준]"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from caffeinate import (
    Block,
    Document,
    Embed,
    File,
    Formula,
    Map,
    Material,
    MaterialType,
    Place,
    RawBlock,
    Schedule,
    Text,
    Thumbnail,
    UploadedFile,
    UploadedVideo,
    Video,
    Vote,
    VoteItem,
    VoteResultView,
    VoteSort,
    static_map_url,
)
from caffeinate.models.media import (
    format_date_range_with_text,
    format_date_with_text,
    format_with_comma,
    material_thumbnail_url,
    normalize_realestate,
)
from caffeinate.models.spec import SpecError, from_spec, to_spec
from caffeinate.utils.imagesize import image_size
from caffeinate.utils.multipart import FilePart, encode_parts

CAPS = json.loads((Path(__file__).parent / "editor_captures.json").read_text(encoding="utf-8"))
KST = timezone(timedelta(hours=9))
SEOUL = Place("서울역 (고속철도)", 37.554073, 126.9707021, "서울특별시 용산구 한강대로 405", "11630456", "1588-7788")
AIRPORT = Place("서울역 공항철도", 37.553739, 126.9696659, "서울특별시 용산구 청파로 378", "20536662", "1599-7788")


# ---------------------------------------------------------------- 에디터 캡처와 같은 dict


@pytest.mark.parametrize("name", ["file", "placesMap", "vote", "video", "material", "formula"])
def test_editor_capture_roundtrip_exact(name: str) -> None:
    cap = CAPS[name]
    block = Block.from_dict(cap)
    assert not isinstance(block, RawBlock)
    out = block.to_dict()
    assert out == cap
    assert list(out) == list(cap)  # 키 순서까지 에디터 직렬화와 같게


def test_schedule_capture_gets_uuid() -> None:
    """에디터 삽입 직후 데이터에는 uuid 가 없고, 저장하려면 필요하다 [실측] -> 자동으로 붙는다"""
    cap = CAPS["schedule"]
    out = Block.from_dict(cap).to_dict()
    assert out["data"].pop("uuid")
    assert out == cap


def test_registered_ctypes() -> None:
    for ctype, cls in {"file": File, "video": Video, "placesMap": Map, "formula": Formula, "material": Material,
                       "oembed": Embed}.items():
        assert Block._REGISTRY[ctype] is cls
    assert isinstance(Block.from_dict(CAPS["vote"]), Vote)
    broken = {"id": "SE-1", "@ctype": "custom", "subtype": "vote", "data": {"voteName": "a"}}
    assert Block.from_dict(broken).to_dict() == broken      # 항목 없는 투표도 버리지 않고 보존
    unknown = Block.from_dict({"@ctype": "custom", "subtype": "nope", "data": {}})
    assert isinstance(unknown, RawBlock)


# ---------------------------------------------------------------- 지도


def test_static_map_url_matches_editor() -> None:
    one = CAPS["placesMap"]["thumbnail"]["src"].split("&dataversion")[0]
    assert static_map_url([SEOUL]) == one
    two = ("https://simg.pstatic.net/static.map/v2/map/staticmap.bin?caller=smarteditor"
           "&markers=viewSizeRatio%3A0.7%7Ccolor%3A0x11cc73%7Clabel%3Aa%7Cpos%3A126.9707021%2037.554073%7Csize%3Amid"
           "%7Ctype%3Aa&markers=viewSizeRatio%3A0.7%7Ccolor%3A0x11cc73%7Clabel%3Ab%7Cpos%3A126.9696659%2037.553739"
           "%7Csize%3Amid%7Ctype%3Aa&w=620&h=200&scale=2")
    assert static_map_url([SEOUL, AIRPORT]) == two


def test_place_from_api_uses_road_address() -> None:
    p = Place.from_api({"id": "1", "name": "n", "x": "126.1", "y": "37.2", "address": "지번", "roadAddress": "도로명",
                        "tel": "", "type": "s"})
    assert (p.latitude, p.longitude, p.address, p.place_id) == (37.2, 126.1, "도로명", "1")


def test_map_requires_places() -> None:
    with pytest.raises(ValueError):
        Map([])
    with pytest.raises(TypeError):
        Map(["서울역"])  # type: ignore[list-item]
    assert Map(SEOUL).places == [SEOUL]  # type: ignore[arg-type]


# ---------------------------------------------------------------- 파일 / 동영상


def test_file_pending_and_uploaded() -> None:
    f = File(b"abc")
    assert f.uploaded is None
    with pytest.raises(ValueError, match="업로드"):
        f.to_dict()
    f.source = UploadedFile("id", "a.txt", 3)
    assert f.to_dict()["fileId"] == "id"
    with pytest.raises(ValueError):
        File()


def test_video_meta_and_limits() -> None:
    v = Video(UploadedVideo("VID", 10, 4, 640, 360, "th"), title="제목", description="설명", tags=["t"])
    d = v.to_dict()
    assert d["mediaMeta"] == {"title": "제목", "tags": ["t"], "description": "설명", "@ctype": "mediaMeta"}
    assert d["represent"] is False
    with pytest.raises(ValueError):
        Video(b"x", title="가" * 41)
    with pytest.raises(ValueError):
        Video(b"x", tags=[str(i) for i in range(11)])


def test_video_display_size_like_editor() -> None:
    d = Video(UploadedVideo("V", 1, 7, 1280, 720, "t")).to_dict()
    assert (d["originalWidth"], d["originalHeight"], d["width"], d["height"]) == (1280, 720, 800, 450)
    d = Video(UploadedVideo("V", 1, 4, 640, 360, "t")).to_dict()
    assert (d["width"], d["height"]) == (640, 360)


def test_first_video_becomes_represent_temporarily() -> None:
    v = Video(UploadedVideo("VID", 10, 4, 640, 360, "th"))
    comps = Document([Text("a"), v]).to_dict()["document"]["components"]
    assert comps[1]["represent"] is True
    assert v.represent is None


# ---------------------------------------------------------------- 수식


def test_formula_needs_render() -> None:
    f = Formula(r"\frac{a}{b}")
    assert not f.rendered
    with pytest.raises(ValueError, match="렌더링"):
        f.to_dict()
    tpl = Formula("  ")    # 빈 latex 는 템플릿(AI 채우기)용으로 만들 수 있다
    with pytest.raises(ValueError, match="렌더링"):
        tpl.to_dict()
    f.html, f.thumbnail = "<div class='lama-viewer'></div>", Thumbnail(src="https://x/y.png", width=1, height=1)
    assert f.to_dict()["fontSizeCode"] == "fs15"


# ---------------------------------------------------------------- 투표


def test_vote_serialize_rules() -> None:
    v = Vote("점심", ["김밥", VoteItem("라면", image="https://img/x.png"), "국수"], multiple=9, secret=False,
             result_view=VoteResultView.ALWAYS, sort=VoteSort.MOST_VOTED, close_voters=10, cafe_id=1, writer_id="u")
    d = v.to_dict()["data"]
    assert d["selectableCount"] == 3       # 항목 수로 줄인다 (에디터 serialize)
    assert d["closeCondition"] == "voter_count" and d["closeConditionVoterCount"] == 10
    assert d["closeConditionEndTime"] is None
    assert d["viewProperty"] == {"resultItemSortType": "most_voted", "showVoterChoice": True,
                                 "resultViewCondition": "always"}
    assert d["isSecret"] is False
    assert [i["itemOrder"] for i in d["items"]] == [1, 2, 3]
    assert d["items"][1]["itemImageUrl"] == "https://img/x.png"


def test_vote_close_time_and_errors() -> None:
    v = Vote("a", ["x", "y"], close_at=datetime(2026, 12, 1, 18, tzinfo=KST))
    d = v.to_dict()["data"]
    assert d["closeCondition"] == "time" and d["closeConditionEndTime"] == 1796115600000
    with pytest.raises(ValueError):
        Vote("a", ["x"])
    with pytest.raises(ValueError, match="제목"):
        Vote("", ["x", "y"]).to_dict()      # 빈 제목은 만들 수 있지만 보낼 수 없다
    with pytest.raises(ValueError):
        Vote("a", ["x", "y"], close_at=datetime(2026, 1, 1, tzinfo=KST), close_voters=3)
    with pytest.raises(ValueError, match="항목 이름"):
        Vote("a", ["x", " "]).to_dict()


def test_vote_image_path_is_pending() -> None:
    """경로 문자열은 업로드 대상 (주소로 착각하면 경로가 그대로 저장된다 - 실측 버그)"""
    v = Vote("a", [VoteItem("x", image="C:/a.png"), VoteItem("y", image="https://cafeptthumb-phinf.pstatic.net/a")])
    assert [i.name for i in v.pending_images] == ["x"]
    with pytest.raises(ValueError, match="업로드"):
        v.to_dict()


def test_vote_keeps_server_fields_on_roundtrip() -> None:
    cap = json.loads(json.dumps(CAPS["vote"]))
    cap["data"]["voteId"] = 19975032
    cap["data"]["uuid"] = "V-1"
    out = Block.from_dict(cap).to_dict()
    assert out["data"]["voteId"] == 19975032 and out["data"]["uuid"] == "V-1"


# ---------------------------------------------------------------- 일정


def test_schedule_defaults_and_place() -> None:
    s = Schedule("모임", datetime(2026, 12, 1, 19), place=SEOUL)  # noqa: DTZ001 - 시간대 없는 값 검사
    d = s.to_dict()["data"]
    assert d["startDateTimeStamp"] == 1796119200000          # 시간대 없는 값은 서울
    assert d["endDateTimeStamp"] - d["startDateTimeStamp"] == 3600000
    assert d["location"] == SEOUL.name and d["latitude"] == SEOUL.latitude
    assert d["timeZone"]["offsetMinute"] == 540
    assert d["uuid"]
    with pytest.raises(ValueError):
        Schedule("x", datetime(2026, 1, 2, tzinfo=KST), datetime(2026, 1, 1, tzinfo=KST))
    with pytest.raises(ValueError):
        Schedule("x")


# ---------------------------------------------------------------- 글감 / 임베드


BOOK = {"title": "해리 포터와 마법사의 돌 1", "author": "조앤 K. 롤링", "thumbnail": "t", "bigThumbnail": "big",
        "linkUrl": "https://l", "publisher": "문학수첩", "publishDay": "20241120", "isbn": "51182815714", "sign": "S"}


def test_material_book_matches_editor_capture() -> None:
    """2026-11-24 통합 검색 '해리포터' 첫 책을 에디터로 넣은 결과와 같은 detailInfo"""
    m = Material.from_search(MaterialType.BOOK, BOOK)
    d = m.to_dict()
    assert [(x["labelName"], [v["value"] for v in x["values"]]) for x in d["detailInfo"]] == [
        ("author", ["조앤 K. 롤링"]), ("publisher", ["문학수첩"]), ("publishDay", ["2024.11.20."]),
        ("publishYear", ["2024"])]
    assert d["dataId"] == "51182815714" and "subId" not in d and "volNo" not in d
    assert d["volScs"] in {str(i) for i in range(1, 10)}
    assert material_thumbnail_url("book", BOOK) == "big"


def test_material_realestate_normalized() -> None:
    item = {"complexNumber": 124533, "name": "래미안", "type": "A01", "useApprovalDate": "20210827",
            "url": "https://u", "dealPriceRange": {"ceiling": "8억", "floor": "3억"},
            "representativePhotoUrl": "https://p", "sign": "S"}
    d = Material.from_search("realestate", item).to_dict()
    vals = {x["labelName"]: x["values"][0]["value"] for x in d["detailInfo"]}
    assert vals == {"type": "아파트", "dealPriceRange": "3억~8억", "useApprovalDate": "2021.08.27."}
    assert d["dataId"] == "124533" and d["layout"] == "default"
    assert material_thumbnail_url("realestate", normalize_realestate(item)) == "https://p"


def test_material_unknown_kind() -> None:
    with pytest.raises(ValueError):
        Material.from_search("stock", {})


@pytest.mark.parametrize(("raw", "full", "year"), [
    ("20241120", "2024.11.20.", "2024"), ("2024.1.5", "2024.01.05.", "2024"), ("202401", "2024.01.", "2024"),
    ("2024", "2024.", "2024"), ("2024-13-01", "", ""), ("abc", "", ""), ("", "", "")])
def test_format_date_with_text(raw: str, full: str, year: str) -> None:
    assert format_date_with_text(raw) == full
    assert format_date_with_text(raw, True) == year


def test_formatters() -> None:
    assert format_with_comma(1234567) == "1,234,567"
    assert format_with_comma("1234.5") == "1,234.5"
    assert format_date_range_with_text("2026.11.20 ~ 11.21") == "2026.11.20. ~ 2026.11.21."


def test_embed_from_api() -> None:
    data = {"oglink": {"url": "https://youtu.be/x", "summary": {"description": "d"}},
            "oembed": {"type": "video", "version": "1.0", "html": "<iframe></iframe>", "title": "T", "width": 200,
                       "height": 150, "providerName": "YouTube"}, "oembedSign": "S"}
    e = Embed.from_api(data, "https://youtu.be/x")
    d = e.to_dict()
    assert (d["inputUrl"], d["oembedSign"], d["description"], d["contentMode"]) == ("https://youtu.be/x", "S", "d",
                                                                                     "fit")
    assert Block.from_dict(d).to_dict() == d
    with pytest.raises(ValueError):
        Embed.from_api({"oglink": {}}, "https://a")


# ---------------------------------------------------------------- spec


def test_spec_roundtrip_new_blocks() -> None:
    blocks = [
        File(UploadedFile("id", "a.txt", 3)), File("C:/a.txt"),
        Video(UploadedVideo("V", 1, 2, 3, 4, "t"), title="제목", tags=["a"]),
        Map([SEOUL, AIRPORT]), Formula("x^2"),
        Vote("v", ["a", VoteItem("b", image="https://i")], multiple=0, close_voters=3),
        Schedule("s", datetime(2026, 12, 1, 19, tzinfo=KST), all_day=True, place=SEOUL),
        Material.from_search("book", BOOK),
        Embed("https://youtu.be/x", "<iframe></iframe>", "T"),
    ]
    for b in blocks:
        again = from_spec(to_spec(b))
        assert type(again) is type(b)
        assert to_spec(again) == to_spec(b)


def test_spec_errors() -> None:
    with pytest.raises(SpecError):
        from_spec({"type": "schedule", "title": "a", "start": "어제"})
    with pytest.raises(SpecError):
        from_spec({"type": "map", "places": [{"name": "a"}]})
    with pytest.raises(SpecError):
        from_spec({"type": "vote", "title": "a", "items": ["x"]})
    with pytest.raises(SpecError):
        from_spec({"type": "embed", "data": {"@ctype": "text"}})


def test_fill_vote_and_schedule() -> None:
    tpl = Document([Vote("제목", ["1", "2"], hint="투표 주제"), Schedule("일정", datetime(2026, 1, 1, tzinfo=KST))])
    schema = tpl.fill_schema()
    assert schema["properties"]["0_vote"]["properties"]["items"]["minItems"] == 2
    out = tpl.fill({"0_vote": {"title": "점심", "items": ["김밥", "라면"]},
                    "1_schedule": {"title": "모임", "location": "대구"}})
    assert [i.name for i in out.blocks[0].items] == ["김밥", "라면"]
    assert out.blocks[1].location == "대구"
    with pytest.raises(SpecError):
        tpl.fill({"0_vote": {"title": "x", "items": ["a"]}, "1_schedule": {"title": "y", "location": ""}})


def test_document_schema_validates_new_blocks() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    doc = {"blocks": [{"type": "vote", "title": "a", "items": ["x", "y"]},
                      {"type": "schedule", "title": "s", "start": "2026-12-01T19:00"},
                      {"type": "formula", "latex": "x"},
                      {"type": "map", "places": [{"name": "a", "latitude": 1, "longitude": 2}]}]}
    jsonschema.validate(doc, Document.json_schema())
    Document.from_spec(doc)


# ---------------------------------------------------------------- 유틸


def test_image_size() -> None:
    png = bytes.fromhex("89504e470d0a1a0a0000000d494844520000003c00000028")
    assert image_size(png) == (60, 40)
    assert image_size(b"GIF89a\x10\x00\x20\x00") == (16, 32)
    assert image_size(b"nope") is None


def test_encode_parts_keeps_order() -> None:
    ctype, body = encode_parts([("a", "1"), FilePart(name="f", filename="x.png", data=b"D", content_type="image/png"),
                                ("b", "2")])
    assert ctype.startswith("multipart/form-data; boundary=")
    i_a, i_f, i_b = body.index(b'name="a"'), body.index(b'name="f"'), body.index(b'name="b"')
    assert i_a < i_f < i_b


def test_empty_templates_fill_then_serialize() -> None:
    """빈 칸 템플릿 (투표·일정·수식) -> fill -> to_dict 가능"""
    tpl = Document([Vote("", ["", ""]), Schedule("", datetime(2026, 12, 5, 14, tzinfo=KST)), Formula("", hint="이차방정식")])
    with pytest.raises(ValueError):
        tpl.to_dict()
    keys = list(tpl.fill_schema()["properties"])
    doc = tpl.fill({keys[0]: {"title": "점심", "items": ["김밥", "라면"]},
                    keys[1]: {"title": "모임", "location": "성수"}, keys[2]: {"latex": "x^2"}})
    comps = Document(doc.blocks[:2]).to_dict()["document"]["components"]
    assert comps[0]["data"]["voteName"] == "점심" and comps[1]["data"]["content"] == "모임"
    assert doc.blocks[2].latex == "x^2" and not doc.blocks[2].rendered
