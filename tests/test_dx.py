"""0.4.0 공개 API 편의 기능 (네트워크 없음)

카페 식별자 해석/캐시, 쓰기 결과 타입(삭제/좋아요), 예외 매핑, 요청 간격, 비동기 반복자, images 자동 업로드.
"""
import asyncio
import itertools
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from caffeinate import (
    ArticleNotFoundError,
    ArticlePage,
    ArticleRef,
    ArticleSummary,
    CafeNotFoundError,
    Caffeinate,
    Comment,
    CommentPage,
    LikeStatus,
    NaverAPIError,
    NotLoggedInError,
    PageInfo,
    PermissionDeniedError,
    RateLimitedError,
    Settings,
    UploadedImage,
)
from caffeinate.core import endpoints
from caffeinate.core.errors import api_error_class
from caffeinate.core.session import CafeSession, ensure_success, parse_json
from caffeinate.enums import HttpMethod
from caffeinate.services import articles as articles_mod
from caffeinate.services.base import BaseService, image_source
from caffeinate.services.likes import react_status

CAFE_HTML = '<html><script>var g_sClubId = "x"; clubid=31547053;</script></html>'


@dataclass
class FakeResp:
    status_code: int = 200
    data: Any = None
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        if self.data is None:
            return json.loads(self.text)
        return self.data


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Caffeinate:
    monkeypatch.setattr(BaseService, "_require_login", lambda self: None)
    return Caffeinate()


# ---------------------------------------------------------------- 카페 식별자
def _count_html(monkeypatch: pytest.MonkeyPatch, c: Caffeinate, html: str = CAFE_HTML) -> list[str]:
    calls: list[str] = []

    async def fake_get_html(url: str, **kw: Any) -> str:
        calls.append(url)
        await asyncio.sleep(0)
        return html

    monkeypatch.setattr(c.session, "get_html", fake_get_html)
    return calls


def test_resolve_id_forms_and_cache(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    calls = _count_html(monkeypatch, client)

    async def go() -> list[int]:
        return [
            await client.cafes.resolve_id(31547053),
            await client.cafes.resolve_id("31547053"),
            await client.cafes.resolve_id("https://cafe.naver.com/f-e/cafes/31547053/menus/1"),
            await client.cafes.resolve_id("deongdion"),
            await client.cafes.resolve_id("DeongDion"),            # 대소문자 무관 캐시
            await client.cafes.resolve_id("https://cafe.naver.com/deongdion"),
        ]

    assert asyncio.run(go()) == [31547053] * 6
    assert calls == ["https://cafe.naver.com/deongdion"]  # slug 는 한 번만 조회


def test_concurrent_slug_resolution_fetches_once(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    calls = _count_html(monkeypatch, client)

    async def go() -> list[int]:
        return list(await asyncio.gather(*(client.cafes.resolve_id("deongdion") for _ in range(5))))

    assert asyncio.run(go()) == [31547053] * 5
    assert len(calls) == 1


def test_services_accept_slug(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    html_calls = _count_html(monkeypatch, client)
    urls: list[str] = []

    async def fake_get_json(url: str, **kw: Any) -> Any:
        urls.append(url)
        return {"result": {"menus": [], "articleList": []}}

    monkeypatch.setattr(client.session, "get_json", fake_get_json)

    async def go() -> None:
        await client.boards.all("deongdion")
        await client.boards.articles("deongdion", 1)
        await client.boards.notices("https://cafe.naver.com/deongdion", 1)
        await client.members.membership("31547053")

    asyncio.run(go())
    assert len(html_calls) == 1
    assert urls == [
        endpoints.cafe_menus(31547053),
        endpoints.article_list(31547053, 1),
        endpoints.notice_list(31547053, 1),
        endpoints.cafe_members(31547053),
    ]


def test_unknown_slug_404_is_cafe_not_found(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    async def fake_get_html(url: str, **kw: Any) -> str:
        raise NaverAPIError("HTML 요청 실패 (404)", 404, "")

    monkeypatch.setattr(client.session, "get_html", fake_get_html)
    with pytest.raises(CafeNotFoundError):
        asyncio.run(client.cafes.resolve_id("no-such-cafe-xyz"))


# ---------------------------------------------------------------- 예외 매핑
@pytest.mark.parametrize(
    ("status", "body", "exc"),
    [
        (404, {"result": {"errorCode": "4003", "reason": "없는 글"}}, ArticleNotFoundError),
        (404, None, ArticleNotFoundError),
        (400, {"result": {"errorCode": "0010"}}, CafeNotFoundError),
        (403, {"result": {"errorCode": "4004"}}, PermissionDeniedError),
        (500, {"result": {"errorCode": "40003"}}, PermissionDeniedError),
        (403, {"message": {"error": {"code": "2001", "msg": "연달아"}}}, RateLimitedError),
        (429, None, RateLimitedError),
        (401, {"result": {"errorCode": "0004"}}, NotLoggedInError),
        (500, {"error": {"errorCode": "10004"}}, NotLoggedInError),
        (500, {"result": {"errorCode": "9999"}}, NaverAPIError),
    ],
)
def test_error_mapping(status: int, body: Any, exc: type[NaverAPIError]) -> None:
    with pytest.raises(NaverAPIError) as info:
        parse_json(FakeResp(status, body, "x") if body is not None else _NoJson(status), "u")  # type: ignore[arg-type]
    assert type(info.value) is exc
    assert info.value.status == status
    if exc is not NaverAPIError:
        assert info.value.hint


@dataclass
class _NoJson:
    status_code: int
    text: str = "<html>"

    def json(self) -> Any:
        raise ValueError


def test_api_error_class_code_wins_over_status() -> None:
    assert api_error_class(403, "2001") is RateLimitedError
    assert api_error_class(404, None) is ArticleNotFoundError
    assert api_error_class(None, None) is NaverAPIError


def test_comment_2001_retry_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BaseService, "_require_login", lambda self: None)
    c = Caffeinate(Settings(comment_retry_max=1, comment_retry_delays=(0.0,)))
    responses = [
        FakeResp(403, {"message": {"error": {"code": "2001", "msg": "연달아"}}}),
        FakeResp(200, {"commentId": 5, "refCommentId": 5}),
    ]

    async def fake_request(method: Any, url: str, **kw: Any) -> FakeResp:
        return responses.pop(0)

    monkeypatch.setattr(c.session, "request", fake_request)
    assert asyncio.run(c.comments.add(ArticleRef(cafe_id=1, article_id=2, menu_id=3), "x")) == 5


# ---------------------------------------------------------------- 쓰기 결과
def test_ensure_success_shapes() -> None:
    ensure_success({"message": {"status": "200", "error": {"code": "", "msg": ""}, "result": {"msg": "Success"}}}, "글")
    ensure_success({"msg": "Success"}, "댓글")
    with pytest.raises(NaverAPIError):
        ensure_success({"msg": "Fail"}, "댓글")
    with pytest.raises(PermissionDeniedError):
        ensure_success({"message": {"status": "500", "error": {"code": "4004", "msg": "멤버만"}}}, "글")
    with pytest.raises(NaverAPIError):
        ensure_success(None, "글")


def _capture(monkeypatch: pytest.MonkeyPatch, c: Caffeinate, responses: list[FakeResp]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_request(method: Any, url: str, **kw: Any) -> FakeResp:
        calls.append({"method": str(method), "url": url, **kw})
        return responses.pop(0)

    monkeypatch.setattr(c.session, "request", fake_request)
    return calls


def test_article_delete_returns_none(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    ok = {"message": {"status": "200", "error": {"code": "", "msg": ""}, "result": {"msg": "Success"}}}
    calls = _capture(monkeypatch, client, [FakeResp(data=ok), FakeResp(data={"message": {"status": "500"}})])
    ref = ArticleRef(cafe_id=1, article_id=2, menu_id=3)
    assert asyncio.run(client.articles.delete(ref)) is None
    assert calls[0]["url"] == endpoints.ARTICLE_DELETE
    with pytest.raises(NaverAPIError):
        asyncio.run(client.articles.delete(ref))


def test_comment_delete_returns_none(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    _capture(monkeypatch, client, [FakeResp(data={"msg": "Success"}), FakeResp(data={"msg": "Fail"})])
    ref = ArticleRef(cafe_id=1, article_id=2, menu_id=3)
    assert asyncio.run(client.comments.delete(ref, 9)) is None
    with pytest.raises(NaverAPIError):
        asyncio.run(client.comments.delete(ref, 9))


def test_like_response_parsed() -> None:
    raw = {"contentsId": "31547053_deongdion_197", "reactionType": "like", "count": 1, "isReacted": True}
    st = react_status(raw, "31547053_deongdion_197")
    assert isinstance(st, LikeStatus)
    assert (st.like_count, st.liked, st.content_id) == (1, True, "31547053_deongdion_197")
    st = react_status({"reactionType": "like", "count": 0, "isReacted": False}, "c")
    assert (st.like_count, st.liked, st.content_id) == (0, False, "c")
    with pytest.raises(NaverAPIError):
        react_status({"code": "4013", "message": "토큰"}, "c")


def test_update_returns_ref(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    _capture(monkeypatch, client, [FakeResp(data={"result": {"articleId": 7, "menuId": 1}})])
    ref = asyncio.run(client.articles.update(ArticleRef(cafe_id=1, article_id=7), 1, "t", "b"))
    assert ref == ArticleRef(cafe_id=1, article_id=7, menu_id=1)


# ---------------------------------------------------------------- images 자동 업로드
def test_write_images_auto_upload_keeps_order(
    monkeypatch: pytest.MonkeyPatch, client: Caffeinate, tmp_path: Path
) -> None:
    _count_html(monkeypatch, client)
    uploads: list[tuple[int, int, bytes, str]] = []

    async def fake_upload(cafe_id: Any, menu_id: int, data: bytes, filename: str = "image.png") -> UploadedImage:
        uploads.append((cafe_id, menu_id, data, filename))
        await asyncio.sleep(0)
        return UploadedImage(url=f"/h/{filename}", path="/h", domain="d", file_name=filename)

    monkeypatch.setattr(client.photos, "upload", fake_upload)
    seen: list[list[str]] = []

    def fake_content(body: str, images: list[UploadedImage] | None = None) -> str:
        seen.append([i.file_name for i in images or []])
        return "{}"

    monkeypatch.setattr(articles_mod, "build_content_json", fake_content)
    posted: list[Any] = []

    async def fake_post_json(url: str, json_body: Any = None, **kw: Any) -> Any:
        posted.append((url, json_body))
        return {"result": {"articleId": 42}}

    monkeypatch.setattr(client.session, "post_json", fake_post_json)
    f = tmp_path / "c.png"
    f.write_bytes(b"\x89PNGc")
    pre = UploadedImage(url="/h/pre.png", path="/h", domain="d", file_name="pre.png")
    ref = asyncio.run(client.articles.write(
        "deongdion", 1, "t", "b", images=[b"\x89PNGa", pre, (b"\x89PNGb", "b.png"), str(f), f]
    ))
    assert ref == ArticleRef(cafe_id=31547053, article_id=42, menu_id=1)
    assert seen == [["image.png", "pre.png", "b.png", "c.png", "c.png"]]
    assert [(u[0], u[1], u[3]) for u in uploads] == [
        (31547053, 1, "image.png"), (31547053, 1, "b.png"), (31547053, 1, "c.png"), (31547053, 1, "c.png"),
    ]
    assert posted[0][0] == endpoints.editor_write_article(31547053, 1)


def test_image_source() -> None:
    assert image_source(b"x") == (b"x", "image.png")
    assert image_source(b"x", "a.jpg") == (b"x", "a.jpg")
    assert image_source((b"y", "b.gif")) == (b"y", "b.gif")


# ---------------------------------------------------------------- 요청 간격
class _FakeCurl:
    def __init__(self) -> None:
        self.starts: list[float] = []

    async def request(self, *a: Any, **kw: Any) -> FakeResp:
        self.starts.append(time.monotonic())
        await asyncio.sleep(0.01)
        return FakeResp(200, {})


def _paced_starts(interval: float, n: int) -> list[float]:
    s = CafeSession(Settings(min_request_interval=interval))
    fake = _FakeCurl()

    async def go() -> None:
        await asyncio.gather(*(
            s._send_with_retry(fake, HttpMethod.GET, "https://x", None, [], None, 22)  # type: ignore[arg-type]
            for _ in range(n)
        ))

    asyncio.run(go())
    return fake.starts


def test_min_request_interval_spaces_concurrent_requests() -> None:
    starts = _paced_starts(0.05, 4)
    gaps = [b - a for a, b in itertools.pairwise(starts)]
    assert len(starts) == 4 and all(g >= 0.05 for g in gaps), gaps


def test_min_request_interval_off_by_default() -> None:
    assert Settings().min_request_interval == 0.0
    starts = _paced_starts(0.0, 4)
    assert starts[-1] - starts[0] < 0.04
    with pytest.raises(ValueError):
        Settings(min_request_interval=-1)


# ---------------------------------------------------------------- 비동기 반복자
def _summary(i: int) -> ArticleSummary:
    return ArticleSummary(article_id=i, cafe_id=1, menu_id=2, subject=f"s{i}")


def test_iter_articles_pages_limit_and_loop_guard(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    pages = {
        1: [1, 2, 3],
        2: [3, 4, 5],          # 3 은 밀려서 겹침 -> 한 번만
        3: [1, 2, 3],          # 범위 초과 -> 1페이지 반복 (새 글 없음 -> 멈춤)
    }
    requested: list[int] = []

    async def fake_articles(cafe_id: Any, menu_id: int, *, page: int = 1, **kw: Any) -> ArticlePage:
        requested.append(page)
        return ArticlePage(
            items=[_summary(i) for i in pages.get(page, pages[1])], page=page,
            page_info=PageInfo(last_page=10, has_next=True),
        )

    monkeypatch.setattr(client.boards, "articles", fake_articles)

    async def collect(**kw: Any) -> list[int]:
        return [a.article_id async for a in client.boards.iter_articles(1, 2, **kw)]

    assert asyncio.run(collect()) == [1, 2, 3, 4, 5]
    assert requested == [1, 2, 3]
    requested.clear()
    assert asyncio.run(collect(limit=4)) == [1, 2, 3, 4]
    assert requested == [1, 2]
    assert asyncio.run(collect(limit=0)) == []
    requested.clear()
    assert asyncio.run(collect(max_pages=1)) == [1, 2, 3]


def test_iter_articles_stops_on_has_next_false(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    async def fake_articles(cafe_id: Any, menu_id: int, *, page: int = 1, **kw: Any) -> ArticlePage:
        return ArticlePage(items=[_summary(page)], page=page, page_info=PageInfo(has_next=page < 2))

    monkeypatch.setattr(client.boards, "articles", fake_articles)

    async def collect() -> list[int]:
        return [a.article_id async for a in client.boards.iter_articles(1, 2)]

    assert asyncio.run(collect()) == [1, 2]


def test_comments_iter_and_all(monkeypatch: pytest.MonkeyPatch, client: Caffeinate) -> None:
    def comment(i: int) -> Comment:
        return Comment.from_api({"id": i, "content": f"c{i}"})

    async def fake_page(ref: Any, *, page: int = 1, size: int = 100) -> CommentPage:
        ids = {1: [1, 2], 2: [3]}.get(page, [3])  # 마지막을 넘으면 마지막 페이지 반복
        return CommentPage(items=[comment(i) for i in ids], has_next=True)

    monkeypatch.setattr(client.comments, "page", fake_page)
    ref = ArticleRef(cafe_id=1, article_id=2, menu_id=3)

    async def collect(**kw: Any) -> list[int]:
        return [c.comment_id async for c in client.comments.iter(ref, **kw)]

    assert asyncio.run(collect()) == [1, 2, 3]
    assert asyncio.run(collect(limit=2)) == [1, 2]
    assert [c.comment_id for c in asyncio.run(client.comments.all(ref))] == [1, 2, 3]
