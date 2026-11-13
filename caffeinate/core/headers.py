"""
실제 파이어폭스와 같은 헤더 구성 (순서/값/Fetch Metadata/Referer 정책)

[실측 2026-11-13] Camoufox(Firefox 158, headless/headed 동일) -> tls.peet.ws HTTP/2 HEADERS 프레임
(+ Playwright headers_array: 리다이렉트 없는 요청에선 wire 순서와 같음을 확인):

  XHR     : user-agent, accept, accept-language, accept-encoding, [referer*],
            [작성자 헤더: content-type / x-... (setRequestHeader 순서)], [content-length], [origin],
            [referer*], [cookie...], sec-fetch-dest, sec-fetch-mode, sec-fetch-site, te
            (priority 없음)
  fetch() : user-agent, accept, accept-language, accept-encoding, [referer*],
            [작성자 헤더: content-type / x-...], [content-length], [origin], [referer*], [cookie...],
            sec-fetch-dest, sec-fetch-mode, sec-fetch-site, priority(u=4), te
  <script>: user-agent, accept(*/*), accept-language, accept-encoding, [referer*], [cookie...],
            sec-fetch-dest(script), sec-fetch-mode(no-cors), sec-fetch-site, te   (origin/priority 없음)
            [실측 2026-11-13 like 위젯 JSONP UI 캡처 + tls.peet.ws]
  본문 없는 XHR POST: ..., sec-fetch-site, content-length: 0, te  [실측 2026-11-13 tls.peet.ws]
  문서 이동: user-agent, accept, accept-language, accept-encoding, [referer*],
            [content-type, content-length, origin  <- 폼 POST], [referer*], [cookie...],
            upgrade-insecure-requests, sec-fetch-dest, sec-fetch-mode, sec-fetch-site,
            [sec-fetch-user], priority(u=0, i), te

  * referer 위치는 두 가지 [실측 2026-11-13]:
    - 앞(accept-encoding 바로 뒤): 페이지가 Referrer-Policy 를 명시한 경우(네이버 카페 페이지는 응답 헤더로
      unsafe-url)의 XHR/문서, 그리고 fetch() 는 정책 유무와 무관하게 앞.
      카페 프론트 실캡처: CommentPost/CommentReply/CommentDelete(apis.naver.com), editor 글쓰기
      (apis.cafe.naver.com), gw 조회(article.cafe.naver.com), 문서 이동 모두 앞.
      명시 정책이면 값과 무관 (meta 로 strict-origin-when-cross-origin 을 명시해도 앞).
    - 뒤(origin 다음, cookie 앞): 정책 없는 페이지(기본값)의 XHR/문서, 그리고 교차 사이트 하위 요청에서
      완화 정책(unsafe-url)이 strict-origin-when-cross-origin 으로 강등된 경우(XHR/fetch 모두).
  * 리다이렉트 뒤 hop 은 순서가 또 다르다 [실측 2026-11-13, 루프백 에코(HTTP/1.1 원본 순서) + tls.peet.ws h2
    교차 확인. Playwright headers_array 는 리다이렉트 hop 의 sec-fetch-* 를 빠뜨려 쓰지 않음]:
      XHR/fetch: ..., accept-encoding, [content-type, content-length], [origin], [작성자 x-...], referer,
                 [cookie...], sec-fetch-*, [priority], te
      문서     : ..., accept-encoding, [content-type, content-length], referer, [origin], [cookie...],
                 upgrade-insecure-requests, sec-fetch-*, sec-fetch-user, priority, te
  - cookie 는 HTTP/2 에서 쿠키마다 별도 `cookie` 헤더로 쪼개서 보낸다 -> wire_headers() 가 분리
    (순서: path 긴 것 먼저, 같으면 생성 순 - 같은 이름 재설정은 처음 생성 위치 유지)
  - 작성자가 Accept 를 안 주면 XHR/fetch 모두 `*/*` (카페 프론트 axios 는 항상
    `application/json, text/plain, */*` 를 준다 [실측 카페 캡처])
  - 카페 프론트 axios 쓰기 요청의 작성자 헤더 순서는 Content-Type -> X-Cafe-Product
    [실측 2026-11-13 CommentPost/Reply/Delete, editor 글쓰기 UI 캡처]
  - 파이어폭스는 sec-ch-ua 계열을 보내지 않는다
  - origin: 같은 출처 GET 에는 없음, POST(같은 출처 포함)·교차 출처(CORS)·폼 POST 에는 있음
  - Referer 는 요청을 일으킨 페이지의 Referrer-Policy 를 따른다. 네이버 카페 페이지는
    `Referrer-Policy: unsafe-url` 이라 같은 사이트(apis.naver.com 등)에도 전체 URL 이 간다
    [실측 2026-11-13 카페 캡처]. 단 XHR/fetch 가 교차 사이트(예: tls.peet.ws)로 가면 파이어폭스가
    unsafe-url 을 strict-origin-when-cross-origin 으로 강등해 `https://cafe.naver.com/` 만 보낸다
    (문서 이동은 강등 없음) [실측 2026-11-13]. 정책 없는 페이지는 strict-origin-when-cross-origin
    [실측 2026-11-13 tls.browserleaks.com -> tls.peet.ws 링크 이동]
  - HTTP/2 HEADERS 프레임 우선순위 weight: 문서 42, XHR/fetch 22 (H2_WEIGHT)
"""
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

from ..enums import HttpMethod, ReferrerPolicy, RequestKind, SecFetchDest, SecFetchMode, SecFetchSite
from ..models.fingerprint import Fingerprint

ACCEPT_ENCODING: Final = "gzip, deflate, br, zstd"
ACCEPT_XHR: Final = "application/json, text/plain, */*"   # 카페 프론트(axios) 기본값 [실측 2026-11-13]
ACCEPT_FETCH: Final = "*/*"                                # fetch() 기본값 [실측 2026-11-13]
ACCEPT_DOCUMENT: Final = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
PRIORITY: Final[dict[RequestKind, str | None]] = {
    RequestKind.XHR: None,          # [실측 2026-11-13] 파이어폭스 XMLHttpRequest 는 priority 를 보내지 않는다
    RequestKind.FETCH: "u=4",
    RequestKind.DOCUMENT: "u=0, i",
    RequestKind.SCRIPT: None,       # [실측 2026-11-13 tls.peet.ws] 동적 <script> (JSONP) 도 priority 없음
}
# [실측 2026-11-13] HTTP/2 HEADERS 프레임 PRIORITY 플래그의 weight (depends_on=0, exclusive=0)
H2_WEIGHT: Final[dict[RequestKind, int]] = {
    RequestKind.XHR: 22,
    RequestKind.FETCH: 22,
    RequestKind.DOCUMENT: 42,
    RequestKind.SCRIPT: 22,         # [실측 2026-11-13 tls.peet.ws]
}
TE: Final = "trailers"

_HEAD: Final = ("user-agent", "accept", "accept-language", "accept-encoding")
_SEC_FETCH: Final = ("sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site")
# 작성자 헤더 뒤 꼬리 (referer 가 앞 위치면 이미 빠져 있다)
_SCRIPT_TAIL: Final[tuple[str, ...]] = (
    "content-length", "origin", "referer", "cookie", *_SEC_FETCH, "priority", "te",
)
_DOC_TAIL: Final[tuple[str, ...]] = (
    "content-type", "content-length", "origin", "referer", "cookie",
    "upgrade-insecure-requests", *_SEC_FETCH, "sec-fetch-user", "priority", "te",
)
# 리다이렉트 뒤 hop [실측 2026-11-13]
_SCRIPT_REDIRECT_TAIL: Final[tuple[str, ...]] = ("referer", "cookie", *_SEC_FETCH, "priority", "te")
_DOC_REDIRECT_TAIL: Final[tuple[str, ...]] = (
    "content-type", "content-length", "referer", "origin", "cookie",
    "upgrade-insecure-requests", *_SEC_FETCH, "sec-fetch-user", "priority", "te",
)
# 교차 사이트 하위 요청(XHR/fetch)에서 파이어폭스가 strict-origin-when-cross-origin 으로 강등하는 완화 정책
# (network.http.referer.disallowCrossSiteRelaxingDefault). unsafe-url 은 [실측 2026-11-13],
# no-referrer-when-downgrade 는 같은 파이어폭스 규칙으로 본다 [추정]
_RELAXING: Final = frozenset({ReferrerPolicy.UNSAFE_URL, ReferrerPolicy.NO_REFERRER_WHEN_DOWNGRADE})
# 이 도메인 페이지는 Referrer-Policy: unsafe-url [실측 2026-11-13 응답 헤더: cafe.naver.com 의 구 iframe / ca-fe /
# f-e 페이지, section.cafe.naver.com, apis.cafe.naver.com, cafe.like / route-like]. 모든 *.naver.com 페이지가
# 같다고 본다 (위 외 호스트는 [추정])
_UNSAFE_URL_SITES: Final = ("naver.com",)


def origin_of(url: str) -> str:
    u = urlparse(url)
    port = f":{u.port}" if u.port else ""
    return f"{u.scheme}://{(u.hostname or '').lower()}{port}"


def _site(host: str) -> str:
    """등록 도메인(eTLD+1) 근사 - naver.com / pstatic.net 등 2단 도메인 기준"""
    parts = host.lower().split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "or", "go", "ne", "ac", "com", "net") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


_SITE_RANK: Final = {
    SecFetchSite.NONE: 0, SecFetchSite.SAME_ORIGIN: 1, SecFetchSite.SAME_SITE: 2, SecFetchSite.CROSS_SITE: 3,
}


def sec_fetch_site(url: str, initiator: str | None) -> SecFetchSite:
    if not initiator:
        return SecFetchSite.NONE
    if origin_of(url) == origin_of(initiator):
        return SecFetchSite.SAME_ORIGIN
    a, b = urlparse(url), urlparse(initiator)
    if a.scheme == b.scheme and _site(a.hostname or "") == _site(b.hostname or ""):
        return SecFetchSite.SAME_SITE
    return SecFetchSite.CROSS_SITE


def worst_site(a: SecFetchSite, b: SecFetchSite) -> SecFetchSite:
    """리다이렉트 체인의 Sec-Fetch-Site: 지금까지 거친 URL 중 가장 '먼' 값 (Fetch Metadata 규격)"""
    return a if _SITE_RANK[a] >= _SITE_RANK[b] else b


def default_referrer_policy(referer: str | None) -> ReferrerPolicy:
    """Referer 페이지의 Referrer-Policy (알려진 네이버 페이지는 unsafe-url, 그 외 파이어폭스 기본값)"""
    host = (urlparse(referer).hostname or "").lower() if referer else ""
    if any(host == d or host.endswith("." + d) for d in _UNSAFE_URL_SITES):
        return ReferrerPolicy.UNSAFE_URL
    return ReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN


def _strip_url(url: str) -> str:
    """Referer 로 보낼 URL: fragment / userinfo 제거"""
    u = urlparse(url.split("#", 1)[0])
    if u.username or u.password:
        u = u._replace(netloc=u.netloc.rsplit("@", 1)[1])
    return u.geturl()


@dataclass(slots=True, frozen=True)
class EffectivePolicy:
    policy: ReferrerPolicy
    explicit: bool      # 페이지가 정책을 명시 (False: 파이어폭스 기본값)
    downgraded: bool    # 교차 사이트 하위 요청이라 완화 정책이 강등됨


def effective_policy(
    url: str, referer: str, policy: ReferrerPolicy | None = None, kind: RequestKind | None = None
) -> EffectivePolicy:
    """이 요청에 실제 적용되는 Referrer-Policy.

    policy 생략 시 알려진 네이버 페이지는 명시 unsafe-url, 그 외는 정책 없음(파이어폭스 기본값).
    kind 가 XHR/fetch 이고 교차 사이트면 완화 정책을 strict-origin-when-cross-origin 으로 강등
    [실측 2026-11-13]. 문서 이동(kind=DOCUMENT/None)은 강등하지 않는다 [실측 2026-11-13].
    """
    base = policy or default_referrer_policy(referer)
    explicit = policy is not None or base is ReferrerPolicy.UNSAFE_URL
    if (
        kind is not None
        and kind.is_script
        and base in _RELAXING
        and sec_fetch_site(url, referer) is SecFetchSite.CROSS_SITE
    ):
        return EffectivePolicy(ReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN, explicit=False, downgraded=True)
    return EffectivePolicy(base, explicit=explicit, downgraded=False)


def referer_for(
    url: str,
    referer: str | None,
    policy: ReferrerPolicy | None = None,
    *,
    kind: RequestKind | None = None,
    cross_origin_chain: bool = False,
) -> str | None:
    """Referer 값. policy 생략 시 default_referrer_policy(referer).

    - kind: XHR/fetch 면 교차 사이트 강등을 적용 (None/문서 이동은 미적용)
    - cross_origin_chain: 리다이렉트 체인에 referer 와 다른 출처 hop 이 있었음. 파이어폭스는 이때
      strict-origin-when-cross-origin 에서 최종 hop 이 referer 와 같은 출처로 돌아와도 출처만 보낸다
      [실측 2026-11-13 루프백 페이지 -> hb.cran.dev 302 -> 루프백]
    """
    if not referer:
        return None
    policy = effective_policy(url, referer, policy, kind).policy
    downgrade = referer.startswith("https://") and not url.startswith("https://")
    same_origin = origin_of(url) == origin_of(referer) and not cross_origin_chain
    origin_only = origin_of(referer) + "/"
    match policy:
        case ReferrerPolicy.NO_REFERRER:
            return None
        case ReferrerPolicy.UNSAFE_URL:
            return _strip_url(referer)
        case ReferrerPolicy.ORIGIN:
            return origin_only
        case ReferrerPolicy.NO_REFERRER_WHEN_DOWNGRADE:
            return None if downgrade else _strip_url(referer)
        case _:  # strict-origin-when-cross-origin
            if same_origin:
                return _strip_url(referer)
            return None if downgrade else origin_only


@dataclass(slots=True, kw_only=True)
class RequestContext:
    url: str
    method: HttpMethod = HttpMethod.GET
    kind: RequestKind = RequestKind.XHR
    referer: str | None = None       # 요청을 일으킨 페이지 URL (정책 적용 전 전체 URL)
    referrer_policy: ReferrerPolicy | None = None  # None: referer 페이지 기준 기본값
    origin: str | None = None        # 명시하지 않으면 referer 로부터 브라우저 규칙대로 유도
    content_type: str | None = None
    content_length: int | None = None  # 본문이 있으면 브라우저 위치에 (curl 은 맨 뒤에 붙임)
    extra: dict[str, str] | None = None
    cookie: str | None = None        # "a=1; b=2" - wire_headers() 가 HTTP/2 처럼 쿠키별로 쪼갠다
    user_activated: bool = True      # 문서 이동이 사용자 클릭/입력으로 일어났는지
    site: SecFetchSite | None = None  # 리다이렉트 체인에서 누적한 Sec-Fetch-Site (None: 계산)
    redirected: bool = False          # 리다이렉트로 따라간 hop (헤더 순서가 다름)
    cross_origin_chain: bool = False  # 앞선 hop 중 referer 와 다른 출처가 있었음 (Referer 값에 영향)


def build_headers(fp: Fingerprint, ctx: RequestContext) -> dict[str, str]:
    """파이어폭스와 같은 순서의 헤더 dict (cookie 는 한 줄 - 전송은 wire_headers 로)"""
    custom: dict[str, str] = {k.lower(): v for k, v in (ctx.extra or {}).items()}
    for k in ("cookie", "referer", "origin", "content-length", "host"):
        custom.pop(k, None)  # 브라우저가 관리하는 헤더는 작성자가 못 바꾼다 (forbidden header)
    kind = ctx.kind
    site = ctx.site or sec_fetch_site(ctx.url, ctx.referer)
    default_accept = {
        RequestKind.XHR: ACCEPT_XHR, RequestKind.FETCH: ACCEPT_FETCH, RequestKind.SCRIPT: ACCEPT_FETCH,
    }.get(kind, ACCEPT_DOCUMENT)

    h: dict[str, str] = {
        "user-agent": fp.user_agent,
        "accept": custom.pop("accept", default_accept),
        "accept-language": fp.accept_language,
        "accept-encoding": ACCEPT_ENCODING,
        "te": TE,
    }
    if priority := PRIORITY[kind]:
        h["priority"] = priority
    early_referer = False
    if ctx.referer and (
        ref := referer_for(
            ctx.url, ctx.referer, ctx.referrer_policy, kind=kind, cross_origin_chain=ctx.cross_origin_chain
        )
    ):
        h["referer"] = ref
        eff = effective_policy(ctx.url, ctx.referer, ctx.referrer_policy, kind)
        # [실측 2026-11-13] 명시 정책(네이버 unsafe-url) 또는 fetch() 면 accept-encoding 바로 뒤.
        # 기본 정책의 XHR/문서, 교차 사이트 강등, 리다이렉트 hop 은 뒤쪽.
        early_referer = (
            not ctx.redirected and not eff.downgraded and (eff.explicit or kind is RequestKind.FETCH)
        )
    ctype = custom.pop("content-type", None) or ctx.content_type
    # [실측 2026-11-13 tls.peet.ws] 본문 없는 XHR POST(xhr.send(null))는 content-length: 0 을
    # 작성자 헤더 자리가 아니라 sec-fetch-* 뒤(te 앞)에 보낸다. 예: cafe-mobile/PhotoInfraSessionKey.json
    late_empty_length = ctx.content_length == 0 and kind is RequestKind.XHR and not ctx.redirected
    if ctx.content_length is not None and not late_empty_length:
        h["content-length"] = str(ctx.content_length)
    if ctx.cookie:
        h["cookie"] = ctx.cookie

    # 작성자 헤더: content-type 먼저, 이어서 커스텀 헤더. 브라우저는 setRequestHeader 순서 그대로 보내고,
    # 카페 axios 쓰기 요청은 Content-Type -> X-Cafe-Product [실측 2026-11-13 CommentPost/Reply/Delete,
    # editor 글쓰기 UI 캡처]
    author: dict[str, str] = {}
    if ctype and kind is not RequestKind.DOCUMENT:
        author["content-type"] = ctype
    author.update(custom)

    origin = ctx.origin
    if kind is RequestKind.SCRIPT:
        # <script src> 는 no-cors GET 이라 Origin 을 보내지 않는다 [실측 2026-11-13 like 위젯 JSONP 캡처]
        h["sec-fetch-site"] = site if site is not SecFetchSite.NONE else SecFetchSite.SAME_ORIGIN
        h["sec-fetch-mode"] = SecFetchMode.NO_CORS
        h["sec-fetch-dest"] = SecFetchDest.SCRIPT
        origin = None
    elif kind.is_script:
        h["sec-fetch-site"] = site if site is not SecFetchSite.NONE else SecFetchSite.SAME_ORIGIN
        h["sec-fetch-mode"] = SecFetchMode.CORS
        h["sec-fetch-dest"] = SecFetchDest.EMPTY
        if origin is None and ctx.referer and (
            not ctx.method.is_safe or site is not SecFetchSite.SAME_ORIGIN
        ):
            origin = origin_of(ctx.referer)
    else:
        if ctype:
            h["content-type"] = ctype
        h["upgrade-insecure-requests"] = "1"
        h["sec-fetch-site"] = site
        h["sec-fetch-mode"] = SecFetchMode.NAVIGATE
        if ctx.user_activated:
            h["sec-fetch-user"] = "?1"
        h["sec-fetch-dest"] = SecFetchDest.DOCUMENT
        # [실측 2026-11-13] 폼 POST 문서 이동은 같은 출처여도 origin 을 보낸다. GET 은 없음.
        if ctx.method.is_safe:
            origin = None
        elif origin is None and ctx.referer:
            origin = origin_of(ctx.referer)
    if origin:
        h["origin"] = origin

    ordered: dict[str, str] = {k: h[k] for k in _HEAD}
    if early_referer:
        ordered["referer"] = h["referer"]
    if ctx.redirected and kind.is_script:
        # [실측 2026-11-13] 리다이렉트 hop: 본문 헤더 -> origin -> 작성자 헤더 -> referer -> cookie
        if "content-type" in author:
            ordered["content-type"] = author.pop("content-type")
        ordered.update({k: h[k] for k in ("content-length", "origin") if k in h})
        ordered.update(author)
        tail = _SCRIPT_REDIRECT_TAIL
    elif ctx.redirected:
        tail = _DOC_REDIRECT_TAIL
    elif kind.is_script:
        ordered.update(author)
        tail = _SCRIPT_TAIL
    else:
        tail = _DOC_TAIL
    ordered.update({k: h[k] for k in tail if k in h and k not in ordered})
    if late_empty_length:
        ordered.pop("te", None)
        ordered["content-length"] = "0"
        ordered["te"] = TE
    return ordered


def wire_headers(headers: dict[str, str]) -> list[tuple[str, str]]:
    """curl 에 넘길 (이름, 값) 목록. cookie 는 HTTP/2 파이어폭스처럼 쿠키마다 별도 헤더로 분리.

    [실측 2026-11-13] 파이어폭스는 h2 에서 `cookie: a=1`, `cookie: b=2` ... 로 나눠 보낸다.
    curl_cffi 의 split_cookies 옵션은 직접 넣은 Cookie 헤더에는 적용되지 않아(실측) 여기서 나눈다.
    """
    out: list[tuple[str, str]] = []
    for k, v in headers.items():
        if k == "cookie":
            out.extend(("cookie", part.strip()) for part in v.split(";") if part.strip())
        else:
            out.append((k, v))
    return out
