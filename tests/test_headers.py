"""core/headers.py - 파이어폭스 wire 순서/값

[실측 2026-11-13] Camoufox 158 -> tls.peet.ws HEADERS 프레임, 카페 프론트 UI 캡처(headers_array),
리다이렉트는 루프백 에코(원본 순서) + tls.peet.ws 교차 확인 기준.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from caffeinate.core import fingerprint as fp_mod
from caffeinate.core.cookies import CookieStore
from caffeinate.core.headers import (
    H2_WEIGHT,
    RequestContext,
    build_headers,
    effective_policy,
    referer_for,
    sec_fetch_site,
    wire_headers,
    worst_site,
)
from caffeinate.core.session import CafeSession, form_encode
from caffeinate.enums import HttpMethod, ReferrerPolicy, RequestKind, SecFetchSite

FP = fp_mod.builtin()
API = "https://apis.naver.com/cafe-web/cafe-cafemain-api/v1.0/cafes/1/menus"
PAGE = "https://cafe.naver.com/f-e/cafes/1/menus/2?page=3"
IFRAME = "https://cafe.naver.com/ca-fe/cafes/31547053/articles/176?fromNext=true"
PLAIN = "https://tls.peet.ws/api/all?first=1"   # Referrer-Policy 없는 페이지
HEAD = ["user-agent", "accept", "accept-language", "accept-encoding"]
SEC = ["sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site"]


# ---------------------------------------------------------------- 네이버 페이지 (명시 정책 unsafe-url)
def test_xhr_get_from_naver_page_referer_first() -> None:
    # [실측] 카페 gw/apis 조회 XHR: referer 가 accept-encoding 바로 뒤, 작성자 헤더 -> origin -> cookie
    ctx = RequestContext(url=API, referer=PAGE, extra={"x-cafe-product": "pc"}, cookie="NID_AUT=x")
    h = build_headers(FP, ctx)
    assert list(h) == [*HEAD, "referer", "x-cafe-product", "origin", "cookie", *SEC, "te"]
    assert "priority" not in h  # XMLHttpRequest 는 priority 없음
    assert h["referer"] == PAGE  # 네이버 페이지는 Referrer-Policy: unsafe-url -> 같은 사이트 교차 출처에도 전체 URL
    assert h["origin"] == "https://cafe.naver.com"    # CORS 라 Origin
    assert h["sec-fetch-site"] == "same-site"
    assert h["accept"] == "application/json, text/plain, */*"
    assert h["user-agent"] == FP.user_agent


@pytest.mark.parametrize("url", [
    "https://apis.naver.com/cafe-web/cafe-mobile/CommentPost.json",
    "https://apis.naver.com/cafe-web/cafe-mobile/CommentReply.json",
    "https://apis.naver.com/cafe-web/cafe-mobile/CommentDelete.json",
])
def test_comment_write_matches_frontend_capture(url: str) -> None:
    # [실측 2026-11-13] 카페 프론트 UI 댓글 작성/답글/삭제 캡처 순서 그대로
    ctx = RequestContext(
        url=url, method=HttpMethod.POST, referer=IFRAME,
        content_type="application/x-www-form-urlencoded", content_length=78,
        extra={"x-cafe-product": "pc"}, cookie="nid_inf=1; NID_AUT=2; NID_SES=3",
    )
    names = [k for k, _ in wire_headers(build_headers(FP, ctx))]
    assert names == [
        *HEAD, "referer", "content-type", "x-cafe-product", "content-length", "origin",
        "cookie", "cookie", "cookie", *SEC, "te",
    ]
    h = build_headers(FP, ctx)
    assert h["referer"] == IFRAME and h["sec-fetch-site"] == "same-site"


def test_editor_write_matches_frontend_capture() -> None:
    # [실측 2026-11-13] 글쓰기 UI -> apis.cafe.naver.com/editor POST (JSON)
    ctx = RequestContext(
        url="https://apis.cafe.naver.com/editor/v2.0/cafes/31547053/menus/1/articles", method=HttpMethod.POST,
        referer="https://cafe.naver.com/ca-fe/cafes/31547053/menus/1/articles/write",
        content_type="application/json", content_length=914, extra={"x-cafe-product": "pc"}, cookie="a=1",
    )
    assert list(build_headers(FP, ctx)) == [
        *HEAD, "referer", "content-type", "x-cafe-product", "content-length", "origin", "cookie", *SEC, "te",
    ]


def test_xhr_post_same_origin_naver_has_origin() -> None:
    ctx = RequestContext(
        url="https://cafe.naver.com/api/x", method=HttpMethod.POST, referer=PAGE,
        content_type="application/json", content_length=12, extra={"x-a": "1"},
    )
    h = build_headers(FP, ctx)
    assert list(h) == [*HEAD, "referer", "content-type", "x-a", "content-length", "origin", *SEC, "te"]
    assert h["origin"] == "https://cafe.naver.com"  # POST 는 같은 출처여도 Origin
    assert h["content-length"] == "12"


def test_document_navigation_from_naver_referer_first() -> None:
    # [실측] 카페 문서 이동(MyCafeIntro/ArticleRead): referer -> cookie -> upgrade-insecure-requests
    ctx = RequestContext(url="https://cafe.naver.com/remonterace", referer="https://cafe.naver.com/",
                         kind=RequestKind.DOCUMENT, cookie="a=b")
    h = build_headers(FP, ctx)
    assert list(h) == [
        *HEAD, "referer", "cookie", "upgrade-insecure-requests", *SEC, "sec-fetch-user", "priority", "te",
    ]
    assert h["priority"] == "u=0, i"
    assert h["sec-fetch-mode"] == "navigate"
    assert h["accept"].startswith("text/html")


def test_xhr_cross_site_from_naver_page_downgraded() -> None:
    # [실측 2026-11-13] 카페 iframe -> tls.peet.ws XHR/fetch: unsafe-url 이 강등돼 출처만, 위치는 origin 뒤
    for kind in (RequestKind.XHR, RequestKind.FETCH):
        ctx = RequestContext(url="https://tls.peet.ws/api/all", method=HttpMethod.POST, referer=IFRAME, kind=kind,
                             content_type="application/x-www-form-urlencoded", content_length=3)
        h = build_headers(FP, ctx)
        keys = list(h)
        assert h["referer"] == "https://cafe.naver.com/"
        assert keys.index("referer") == keys.index("origin") + 1
        assert h["sec-fetch-site"] == "cross-site"
    # 문서 이동은 강등 없음 [실측]
    assert referer_for("https://example.com/", PAGE, kind=RequestKind.DOCUMENT) == PAGE
    assert effective_policy("https://example.com/", PAGE, kind=RequestKind.XHR).downgraded


# ---------------------------------------------------------------- 정책 없는 페이지 (기본값)
def test_xhr_post_default_policy_referer_after_origin() -> None:
    # [실측] tls.peet.ws(정책 없음) XHR: 작성자 헤더 -> content-length -> origin -> referer -> cookie
    ctx = RequestContext(url="https://tls.peet.ws/api/all?x=1", method=HttpMethod.POST, referer=PLAIN,
                         content_type="application/json;charset=UTF-8", content_length=7,
                         extra={"x-cafe-product": "pc"}, cookie="pp=3; zz=9")
    assert list(build_headers(FP, ctx)) == [
        *HEAD, "content-type", "x-cafe-product", "content-length", "origin", "referer", "cookie", *SEC, "te",
    ]


def test_explicit_policy_moves_referer_first() -> None:
    # [실측] meta 로 정책을 명시하면 값과 무관하게 앞 (strict-origin-when-cross-origin 명시도 앞)
    ctx = RequestContext(url="https://tls.peet.ws/api/all", method=HttpMethod.POST, referer=PLAIN,
                         referrer_policy=ReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
                         content_type="application/x-www-form-urlencoded", content_length=3)
    keys = list(build_headers(FP, ctx))
    assert keys.index("referer") == keys.index("accept-encoding") + 1


def test_fetch_order_and_priority() -> None:
    # [실측] fetch() 는 정책 없는 페이지에서도 referer 가 accept-encoding 바로 뒤, 기본 accept 는 */*
    ctx = RequestContext(url="https://tls.peet.ws/api/all?f=1", method=HttpMethod.POST, referer=PLAIN,
                         kind=RequestKind.FETCH, content_type="application/json", content_length=7,
                         extra={"x-cafe-product": "pc"}, cookie="a=1")
    h = build_headers(FP, ctx)
    assert list(h) == [
        *HEAD, "referer", "content-type", "x-cafe-product", "content-length", "origin", "cookie",
        *SEC, "priority", "te",
    ]
    assert h["priority"] == "u=4"
    assert h["accept"] == "*/*"


def test_document_form_post_default_policy_order() -> None:
    # [실측] 정책 없는 페이지 폼 POST: content-type, content-length, origin, referer, cookie, upgrade-insecure-requests
    ctx = RequestContext(url="https://tls.peet.ws/api/all?nav=form", method=HttpMethod.POST,
                         referer="https://tls.peet.ws/api/all?nav=link", kind=RequestKind.DOCUMENT,
                         content_type="application/x-www-form-urlencoded", content_length=3, cookie="a=b")
    h = build_headers(FP, ctx)
    assert list(h) == [
        *HEAD, "content-type", "content-length", "origin", "referer", "cookie",
        "upgrade-insecure-requests", *SEC, "sec-fetch-user", "priority", "te",
    ]
    assert h["origin"] == "https://tls.peet.ws"  # 같은 출처 폼 POST 도 Origin


# ---------------------------------------------------------------- 리다이렉트 hop
def test_redirected_xhr_hop_order() -> None:
    # [실측 2026-11-13] 리다이렉트 뒤: content-type, content-length, origin, 작성자 x-..., referer, cookie
    ctx = RequestContext(url="http://127.0.0.1:18765/echo", method=HttpMethod.POST, referer="http://127.0.0.1:18765/page",
                         content_type="application/x-www-form-urlencoded", content_length=3,
                         extra={"x-cafe-product": "pc"}, origin="null", cookie="ck1=1",
                         redirected=True, site=SecFetchSite.CROSS_SITE)
    h = build_headers(FP, ctx)
    assert list(h) == [
        *HEAD, "content-type", "content-length", "origin", "x-cafe-product", "referer", "cookie", *SEC, "te",
    ]
    assert h["origin"] == "null" and h["sec-fetch-site"] == "cross-site"


def test_redirected_document_hop_order() -> None:
    # [실측 2026-11-13] 폼 POST 307 뒤: content-type, content-length, referer, origin(null), cookie, upgrade...
    ctx = RequestContext(url="https://tls.peet.ws/api/all", method=HttpMethod.POST, referer=PAGE,
                         kind=RequestKind.DOCUMENT, content_type="application/x-www-form-urlencoded",
                         content_length=3, origin="null", cookie="ck1=1", redirected=True,
                         site=SecFetchSite.CROSS_SITE)
    assert list(build_headers(FP, ctx)) == [
        *HEAD, "content-type", "content-length", "referer", "origin", "cookie",
        "upgrade-insecure-requests", *SEC, "sec-fetch-user", "priority", "te",
    ]


def test_referer_after_cross_origin_chain() -> None:
    # [실측 2026-11-13] 기본 정책: A -> B(302) -> A 마지막 hop 도 출처만. unsafe-url 은 전체 URL
    page = "http://127.0.0.1:18765/page"
    echo = "http://127.0.0.1:18765/echo?t=1"
    assert referer_for(echo, page, kind=RequestKind.XHR) == page
    assert referer_for(echo, page, kind=RequestKind.XHR, cross_origin_chain=True) == "http://127.0.0.1:18765/"
    assert referer_for(echo, page, ReferrerPolicy.UNSAFE_URL, kind=RequestKind.XHR, cross_origin_chain=True) == page


@dataclass
class _Resp:
    status_code: int
    location: str | None = None
    headers: Any = field(init=False)

    def __post_init__(self) -> None:
        loc = self.location

        class _H:
            def get(self, k: str, d: Any = None) -> Any:
                return loc if k == "location" else d

            def get_list(self, k: str) -> list[str]:
                return []

        self.headers = _H()


def _run_chain(kind: RequestKind, method: str, codes: list[int], page: str) -> list[list[tuple[str, str]]]:
    """page 에서 hb(교차 사이트) 리다이렉트를 거쳐 page 와 같은 출처로 돌아오는 체인 (오프라인)"""
    sent: list[list[tuple[str, str]]] = []
    hops = [*[_Resp(c, "https://hb.example.org/r" if i + 1 < len(codes) else "https://tls.peet.ws/echo")
              for i, c in enumerate(codes)], _Resp(200)]

    async def fake(self: Any, session: Any, m: Any, url: str, body: Any, headers: Any, *a: Any) -> _Resp:
        sent.append([("method", m.value), ("url", url), ("body", repr(body)), *headers])
        return hops[len(sent) - 1]

    async def go() -> None:
        s = CafeSession(fingerprint=FP, cookies=CookieStore())
        s._send_with_retry = fake.__get__(s)  # type: ignore[method-assign]
        await s.request(method, "https://hb.example.org/start", referer=page, kind=kind,
                        data={"a": "1"} if method == "POST" else None)
        await s.close()

    asyncio.run(go())
    return sent


def test_session_redirect_xhr_post_302_tainted_and_get() -> None:
    # [실측 2026-11-13] XHR POST 302: GET 으로, 본문/content-* 제거, Origin null 유지, Referer 출처만, cross-site
    sent = _run_chain(RequestKind.XHR, "POST", [302], PLAIN)
    final = dict(sent[-1])
    assert final["method"] == "GET" and final["body"] == "None"
    assert "content-type" not in final and "content-length" not in final
    assert final["origin"] == "null"
    assert final["referer"] == "https://tls.peet.ws/"
    assert final["sec-fetch-site"] == "cross-site"
    first = dict(sent[0])
    assert first["origin"] == "https://tls.peet.ws" and first["sec-fetch-site"] == "cross-site"


def test_session_redirect_document_post_307_keeps_body_origin_null() -> None:
    sent = _run_chain(RequestKind.DOCUMENT, "POST", [307], PLAIN)
    final = dict(sent[-1])
    assert final["method"] == "POST" and final["content-length"] == "3"
    assert final["origin"] == "null"
    assert [k for k, _ in sent[-1][3:]].index("referer") < [k for k, _ in sent[-1][3:]].index("origin")


def test_session_redirect_document_get_no_origin() -> None:
    sent = _run_chain(RequestKind.DOCUMENT, "GET", [302], PLAIN)
    final = dict(sent[-1])
    assert "origin" not in final and final["sec-fetch-site"] == "cross-site"


def test_session_same_origin_redirect_not_tainted() -> None:
    # 같은 출처 안에서만 리다이렉트하면 tainted 아님 (Fetch 규격)
    sent: list[dict[str, str]] = []
    hops = [_Resp(307, "https://cafe.naver.com/b"), _Resp(200)]

    async def fake(self: Any, session: Any, m: Any, url: str, body: Any, headers: Any, *a: Any) -> _Resp:
        sent.append(dict(headers))
        return hops[len(sent) - 1]

    async def go() -> None:
        s = CafeSession(fingerprint=FP, cookies=CookieStore())
        s._send_with_retry = fake.__get__(s)  # type: ignore[method-assign]
        await s.request("POST", "https://cafe.naver.com/a", referer=PAGE, data={"a": "1"})
        await s.close()

    asyncio.run(go())
    assert sent[-1]["origin"] == "https://cafe.naver.com"
    assert sent[-1]["sec-fetch-site"] == "same-origin"


# ---------------------------------------------------------------- 기타
def test_form_encode_matches_axios() -> None:
    # [실측 2026-11-13] CommentPost 본문 content=hdr%20test%20c2&stickerId=&...
    assert form_encode({"content": "hdr test c2", "stickerId": ""}) == "content=hdr%20test%20c2&stickerId="
    assert form_encode({"a": "x/&=+!~*'()"}) == "a=x%2F%26%3D%2B!~*'()"
    assert form_encode({"content": "a b"}, RequestKind.DOCUMENT) == "content=a+b"  # HTML 폼 제출


def test_xhr_get_same_origin_has_no_origin() -> None:
    h = build_headers(FP, RequestContext(url="https://cafe.naver.com/api/x", referer=PAGE))
    assert "origin" not in h
    assert h["sec-fetch-site"] == "same-origin"


def test_custom_content_type_takes_body_position() -> None:
    ctx = RequestContext(url=API, method=HttpMethod.POST, referer=PLAIN,
                         extra={"Content-Type": "multipart/form-data; boundary=x"})
    h = build_headers(FP, ctx)
    keys = list(h)
    assert h["content-type"].startswith("multipart/")
    assert keys.index("content-type") == keys.index("accept-encoding") + 1
    keys = list(build_headers(FP, RequestContext(url=API, method=HttpMethod.POST, referer=PAGE,
                                                 extra={"Content-Type": "multipart/form-data; boundary=x"})))
    assert keys.index("content-type") == keys.index("referer") + 1


def test_forbidden_headers_ignored() -> None:
    h = build_headers(FP, RequestContext(url=API, referer=PAGE, extra={"Referer": "https://evil/", "Cookie": "x=1"}))
    assert h["referer"] == PAGE and "cookie" not in h


def test_wire_headers_split_cookies() -> None:
    # [실측] 파이어폭스 h2 는 쿠키마다 별도 cookie 헤더
    h = build_headers(FP, RequestContext(url=API, referer=PAGE, cookie="pp=3; zz=9; aa=2"))
    wire = wire_headers(h)
    assert [v for k, v in wire if k == "cookie"] == ["pp=3", "zz=9", "aa=2"]
    names = [k for k, _ in wire]
    assert names.index("cookie") == names.index("origin") + 1


def test_h2_weight() -> None:
    assert H2_WEIGHT[RequestKind.DOCUMENT] == 42
    assert H2_WEIGHT[RequestKind.XHR] == H2_WEIGHT[RequestKind.FETCH] == 22


def test_referer_policy() -> None:
    other = "https://example.com/a/b?q=1#frag"
    assert referer_for(API, None) is None
    assert referer_for(PAGE + "#frag", PAGE + "#frag") == PAGE
    # 정책 없는 사이트: strict-origin-when-cross-origin [실측]
    assert referer_for("https://example.com/x", other) == "https://example.com/a/b?q=1"
    assert referer_for(API, other) == "https://example.com/"
    assert referer_for("http://example.com/x", other) is None  # 다운그레이드
    # 네이버 페이지: unsafe-url [실측 Referrer-Policy 헤더]
    assert referer_for(API, PAGE) == PAGE
    assert referer_for(API, PAGE, kind=RequestKind.XHR) == PAGE  # 같은 사이트라 강등 없음
    assert referer_for("https://example.com/", PAGE) == PAGE
    assert referer_for("https://example.com/", PAGE, kind=RequestKind.XHR) == "https://cafe.naver.com/"
    assert referer_for(API, PAGE, ReferrerPolicy.NO_REFERRER) is None
    assert referer_for(API, PAGE, ReferrerPolicy.ORIGIN) == "https://cafe.naver.com/"


def test_sec_fetch_site() -> None:
    assert sec_fetch_site(API, None) is SecFetchSite.NONE
    assert sec_fetch_site(API, "https://apis.naver.com/x") is SecFetchSite.SAME_ORIGIN
    assert sec_fetch_site(API, PAGE) is SecFetchSite.SAME_SITE
    assert sec_fetch_site(API, "https://example.com/") is SecFetchSite.CROSS_SITE
    assert worst_site(SecFetchSite.SAME_ORIGIN, SecFetchSite.CROSS_SITE) is SecFetchSite.CROSS_SITE
    assert worst_site(SecFetchSite.SAME_SITE, SecFetchSite.SAME_ORIGIN) is SecFetchSite.SAME_SITE


def test_session_empty_post_disables_curl_content_type() -> None:
    # [실측 2026-11-13 tls.peet.ws] 본문 없는 XHR POST(PhotoInfraSessionKey.json): 브라우저는 content-type 을
    # 보내지 않고 content-length: 0 을 sec-fetch-* 뒤에 둔다. libcurl 기본 content-type 은 None 으로 끈다.
    sent: list[list[tuple[str, str | None]]] = []

    async def fake(self: Any, session: Any, m: Any, url: str, body: Any, headers: Any, *a: Any) -> _Resp:
        sent.append(list(headers))
        return _Resp(200)

    async def go() -> None:
        s = CafeSession(fingerprint=FP, cookies=CookieStore())
        s._send_with_retry = fake.__get__(s)  # type: ignore[method-assign]
        await s.request("POST", "https://apis.naver.com/x.json", referer=IFRAME, data="")
        await s.close()

    asyncio.run(go())
    names = [k for k, _ in sent[0]]
    assert names == [*HEAD, "referer", "origin", *SEC, "content-length", "te", "content-type"]
    assert dict(sent[0])["content-type"] is None and dict(sent[0])["content-length"] == "0"
