"""좋아요 JSONP / 사진 댓글 요청 구성 (네트워크 없음)

[실측 2026-11-13 Camoufox UI 캡처] 게시글 화면에서 하트 클릭/취소, 사진 댓글/사진 답글 등록 시
브라우저가 보낸 요청(호스트, 쿼리/폼 순서, 요청 종류, Referer)과 같은지 확인한다.
"""
import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from caffeinate import ArticleRef, Caffeinate
from caffeinate.core import endpoints
from caffeinate.core import fingerprint as fp_mod
from caffeinate.core.headers import RequestContext, build_headers
from caffeinate.enums import HttpMethod, ReactionType, RequestKind
from caffeinate.models import UploadedImage
from caffeinate.services.base import BaseService
from caffeinate.services.comments import comment_fields, image_fields
from caffeinate.services.likes import JsonpState, parse_jsonp, react_params, search_params
from caffeinate.services.photos import _comment_upload_query, user_id_from_session_key

FP = fp_mod.builtin()
HEAD = ["user-agent", "accept", "accept-language", "accept-encoding"]
SEC = ["sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site"]
FRAME = "https://cafe.naver.com/ca-fe/cafes/31547053/articles/206?menuid=1&referrerAllArticles=false&fromNext=true"
UPLOAD_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><item><index>0</index>'
    "<url>/MjAy/MDAx.abc.PNG/red.png</url><path>/MjAy/MDAx.abc.PNG</path><fileName>red.png</fileName>"
    "<width>40</width><height>30</height><fileSize>104</fileSize><imageType>PNG</imageType></item>"
)


# ---------------------------------------------------------------- 좋아요 JSONP
def test_jsonp_state_sequence_matches_capture() -> None:
    # 캡처: search callback=..._151 _=152, POST callback=..._151 _=153, DELETE callback=..._151 _=154
    jq = JsonpState(now_ms=1794553139151, rand=0.8004541951628941)
    assert jq.expando == "jQuery33108004541951628941"
    assert jq.next() == ("jQuery33108004541951628941_1794553139151", 1794553139152)
    assert jq.next() == ("jQuery33108004541951628941_1794553139151", 1794553139153)
    assert jq.next() == ("jQuery33108004541951628941_1794553139151", 1794553139154)


def test_like_search_params_order() -> None:
    jq = JsonpState(now_ms=100, rand=0.5)
    p = search_params("31547053_deongdion_206", jq)
    assert list(p) == ["suppress_response_codes", "callback", "q", "isDuplication", "cssIds", "pool", "_"]
    assert p["q"] == "CAFE[31547053_deongdion_206]" and p["cssIds"] == "BASIC_PC,CAFE_PC" and p["pool"] == "cafe"
    assert (p["callback"], p["_"]) == ("jQuery33105_100", 101)


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_like_react_params_order(method: str) -> None:
    jq = JsonpState(now_ms=100, rand=0.5)
    jq.next()  # search 가 먼저 콜백을 만든다
    p = react_params(method, ReactionType.LIKE, 31547053, "tok", 1794553139177, jq)
    expected = [
        "suppress_response_codes", "_method", "callback", "displayId", "reactionType", "categoryId", "guestToken",
        "timestamp", "_ch", "isDuplication", "lang", "countType", "count", "history", "runtimeStatus",
    ]
    if method == "POST":
        expected.append("isPostTimeline")  # 취소(DELETE)에는 없다 [캡처]
    assert list(p) == [*expected, "_"]
    assert p["_method"] == method and p["callback"] == "jQuery33105_100" and p["_"] == 102
    assert p["timestamp"] == 1794553139177 and p["categoryId"] == 31547053


def test_parse_jsonp() -> None:
    assert parse_jsonp('/**/jQuery331_1({"a": 1, "b": "x(y)"});') == {"a": 1, "b": "x(y)"}
    assert parse_jsonp('{"a": 2}') == {"a": 2}


def test_script_kind_headers_match_capture() -> None:
    # [실측] route-like JSONP: Accept */*, referer 앞, cookie, sec-fetch script/no-cors, Origin/priority 없음
    ctx = RequestContext(
        url="https://route-like.naver.com/v1/search/contents?q=x", kind=RequestKind.SCRIPT,
        referer=FRAME, cookie="NID_AUT=1",
    )
    h = build_headers(FP, ctx)
    assert list(h) == [*HEAD, "referer", "cookie", *SEC, "te"]
    assert h["accept"] == "*/*" and h["referer"] == FRAME
    assert (h["sec-fetch-dest"], h["sec-fetch-mode"], h["sec-fetch-site"]) == ("script", "no-cors", "same-site")


def test_empty_xhr_post_content_length_last() -> None:
    # [실측 tls.peet.ws] xhr.send(null) POST: content-length: 0 이 sec-fetch-* 뒤, te 앞
    ctx = RequestContext(
        url=endpoints.COMMENT_PHOTO_SESSION_KEY, method=HttpMethod.POST, referer=FRAME,
        content_length=0, cookie="NID_AUT=1",
    )
    h = build_headers(FP, ctx)
    assert list(h) == [*HEAD, "referer", "origin", "cookie", *SEC, "content-length", "te"]
    assert h["content-length"] == "0" and "content-type" not in h


# ---------------------------------------------------------------- 사진 댓글 폼
def test_comment_fields_order_with_image() -> None:
    img = UploadedImage(url="/A/B.PNG/red.png", path="/A/B.PNG", domain="d", file_name="red.png", width=40, height=30)
    assert image_fields(img) == {
        "imagePath": "/A/B.PNG/", "imageFileName": "red.png", "imageWidth": 40, "imageHeight": 30,
    }
    assert list(comment_fields("t", "", img)) == [
        "content", "stickerId", "imagePath", "imageFileName", "imageWidth", "imageHeight",
    ]
    assert list(comment_fields("t", "", img, 5)) == [
        "content", "stickerId", "imagePath", "imageFileName", "imageWidth", "imageHeight", "refCommentId",
    ]
    assert list(comment_fields("t")) == ["content", "stickerId"]
    # path 가 비어 있으면 url 에서 파일명을 떼어 만든다
    no_path = UploadedImage(url="/A/B.PNG/red.png", path="", domain="d", file_name="red.png")
    assert image_fields(no_path)["imagePath"] == "/A/B.PNG/"


def test_comment_upload_query_order() -> None:
    assert list(_comment_upload_query("me")) == [
        "userId", "extractExif", "extractAnimatedCnt", "autorotate", "extractDominantColor",
        "type", "customQuery", "denyAnimatedImage", "skipXcamFiltering",
    ]
    assert _comment_upload_query("me")["extractExif"] == "false"


def test_user_id_from_session_key() -> None:
    import base64

    key = base64.b64encode(b"20261113160104\x071794554251967\x07cafe2\x07someone\x070\x072\x07abc").decode()
    assert user_id_from_session_key(key) == "someone"
    assert user_id_from_session_key("not-base64!!") == ""


# ---------------------------------------------------------------- 서비스 흐름 (세션 가로채기)
@dataclass
class FakeResp:
    status_code: int = 200
    text: str = ""
    data: Any = None
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        if self.data is None:
            return json.loads(self.text)
        return self.data


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Caffeinate:
    monkeypatch.setattr(BaseService, "_require_login", lambda self: None)
    return Caffeinate()


def _capture(monkeypatch: pytest.MonkeyPatch, c: Caffeinate, responses: list[FakeResp]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_request(method: Any, url: str, **kw: Any) -> FakeResp:
        calls.append({"method": str(method), "url": url, **kw})
        return responses.pop(0)

    monkeypatch.setattr(c.session, "request", fake_request)
    return calls


def test_photo_reply_flow(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    import base64

    key = base64.b64encode(b"x\x07y\x07cafe2\x07me\x070").decode()
    calls = _capture(monkeypatch, client, [
        FakeResp(data={"message": {"status": "200", "error": {"code": "", "msg": ""}, "result": key}}),
        FakeResp(text=UPLOAD_XML),
        FakeResp(data={"commentId": 9, "refCommentId": 7}),
    ])
    ref = ArticleRef(cafe_id=31547053, article_id=206, menu_id=1)
    cid = asyncio.run(client.comments.reply(ref, 7, "hi there", image=b"\x89PNG\r\n\x1a\nxx", filename="red.png"))
    assert cid == 9
    sk, up, post = calls
    frame = endpoints.article_frame_page(31547053, 206, 1)
    # 1) 세션키: 본문 없는 POST, 작성자 헤더 없음
    assert (sk["method"], sk["url"], sk["data"], sk.get("headers")) == (
        "POST", endpoints.COMMENT_PHOTO_SESSION_KEY, "", None,
    )
    assert sk["referer"] == frame
    # 2) 업로드: 세션키 경로, 쿠키 없음, 댓글 업로더 쿼리
    assert up["url"] == endpoints.photo_upload(key) and up["credentials"] is False
    assert up["params"] == _comment_upload_query("me") and up["referer"] == frame
    assert up["headers"]["content-type"].startswith("multipart/form-data; boundary=----geckoformboundary")
    assert b'name="image"; filename="red.png"\r\nContent-Type: image/png' in up["data"]
    # 3) 답글 폼: 캡처 순서
    assert post["url"] == endpoints.COMMENT_REPLY and post["referer"] == frame
    assert post["headers"] == {"x-cafe-product": "pc"}
    assert list(post["data"].items()) == [
        ("content", "hi there"), ("stickerId", ""), ("imagePath", "/MjAy/MDAx.abc.PNG/"),
        ("imageFileName", "red.png"), ("imageWidth", 40), ("imageHeight", 30), ("refCommentId", 7),
        ("cafeId", 31547053), ("articleId", 206), ("requestFrom", "A"),
    ]


def test_text_comment_unchanged(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    calls = _capture(monkeypatch, client, [FakeResp(data={"commentId": 3, "refCommentId": 3})])
    ref = ArticleRef(cafe_id=1, article_id=2, menu_id=3)
    assert asyncio.run(client.comments.add(ref, "x")) == 3
    assert list(calls[0]["data"]) == ["content", "stickerId", "cafeId", "articleId", "requestFrom"]


def test_like_flow_jsonp(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    async def fake_get(ref: Any) -> Any:
        return SimpleNamespace(cafe=SimpleNamespace(url="deongdion"))

    monkeypatch.setattr(client.articles, "get", fake_get)
    calls = _capture(monkeypatch, client, [
        FakeResp(text='/**/cb({"contents":[{"contentsId":"1_deongdion_2","reactions":[]}],'
                      '"guestToken":"g","timestamp":1794553139177});'),
        FakeResp(text='/**/cb({"isReacted":false,"count":0});'),
    ])
    ref = ArticleRef(cafe_id=1, article_id=2, menu_id=3)
    resp = asyncio.run(client.likes.unlike(ref))
    assert (resp.like_count, resp.liked, resp.content_id) == (0, False, "1_deongdion_2")
    assert resp.raw == {"isReacted": False, "count": 0}
    search, react = calls
    frame = endpoints.article_frame_page(1, 2, 3)
    for c in (search, react):
        assert c["kind"] is RequestKind.SCRIPT and c["referer"] == frame and c["method"] == "GET"
    assert search["url"] == endpoints.LIKE_ROUTE_SEARCH
    assert react["url"] == endpoints.like_content("1_deongdion_2")
    p = react["params"]
    assert p["_method"] == "DELETE" and "isPostTimeline" not in p
    assert (p["guestToken"], p["timestamp"]) == ("g", 1794553139177)
    assert p["callback"] == search["params"]["callback"] and p["_"] == search["params"]["_"] + 1
