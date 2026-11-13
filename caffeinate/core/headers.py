"""
실제 파이어폭스와 같은 헤더 구성 (순서/값/Fetch Metadata/Referer 정책)

2026-11-13 실측 (Camoufox = Firefox 158, tls.peet.ws HTTP/2 HEADERS 프레임):

  XHR/fetch  : user-agent, accept, accept-language, accept-encoding, [referer], [content-type],
               [커스텀 x-...], [content-length], [origin], [cookie],
               sec-fetch-dest, sec-fetch-mode, sec-fetch-site, [priority], te
               (priority: XMLHttpRequest 는 없음, fetch() 는 u=4)
  문서 이동  : user-agent, accept, accept-language, accept-encoding, [referer], [cookie],
               upgrade-insecure-requests, sec-fetch-dest, sec-fetch-mode, sec-fetch-site,
               [sec-fetch-user], priority(u=0, i), te

  - 파이어폭스는 sec-ch-ua 계열을 보내지 않는다
  - origin 은 같은 출처 GET 에는 없고, POST(같은 출처 포함)와 교차 출처(CORS)에는 붙음
  - Referer 는 strict-origin-when-cross-origin: 교차 출처면 출처(https://host/)만 전송
  - [추정] 문서 이동 POST 의 content-type/content-length/origin 위치는 XHR 과 같다고 본다 (미실측)
"""
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

from ..enums import HttpMethod, RequestKind, SecFetchDest, SecFetchMode, SecFetchSite
from ..models.fingerprint import Fingerprint

ACCEPT_ENCODING: Final = "gzip, deflate, br, zstd"
ACCEPT_XHR: Final = "application/json, text/plain, */*"   # 카페 프론트(axios) 기본값
ACCEPT_DOCUMENT: Final = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
PRIORITY: Final[dict[RequestKind, str | None]] = {
    RequestKind.XHR: None,          # [실측] 파이어폭스 XMLHttpRequest 는 priority 를 보내지 않는다
    RequestKind.FETCH: "u=4",
    RequestKind.DOCUMENT: "u=0, i",
}
TE: Final = "trailers"

_HEAD: Final = ("user-agent", "accept", "accept-language", "accept-encoding", "referer")
_BODY: Final = ("content-type",)            # 이 뒤에 커스텀 헤더
_AFTER_CUSTOM: Final = ("content-length", "origin", "cookie")
_XHR_TAIL: Final[tuple[str, ...]] = ("sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site", "priority", "te")
_DOC_TAIL: Final[tuple[str, ...]] = (
    "upgrade-insecure-requests", "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site",
    "sec-fetch-user", "priority", "te",
)


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


def sec_fetch_site(url: str, initiator: str | None) -> SecFetchSite:
    if not initiator:
        return SecFetchSite.NONE
    if origin_of(url) == origin_of(initiator):
        return SecFetchSite.SAME_ORIGIN
    a, b = urlparse(url), urlparse(initiator)
    if a.scheme == b.scheme and _site(a.hostname or "") == _site(b.hostname or ""):
        return SecFetchSite.SAME_SITE
    return SecFetchSite.CROSS_SITE


def referer_for(url: str, referer: str | None) -> str | None:
    """strict-origin-when-cross-origin (파이어폭스/크롬 기본 Referrer-Policy)"""
    if not referer:
        return None
    if origin_of(url) == origin_of(referer):
        return referer.split("#", 1)[0]
    if referer.startswith("https://") and not url.startswith("https://"):
        return None  # 다운그레이드
    return origin_of(referer) + "/"


@dataclass(slots=True, kw_only=True)
class RequestContext:
    url: str
    method: HttpMethod = HttpMethod.GET
    kind: RequestKind = RequestKind.XHR
    referer: str | None = None       # 요청을 일으킨 페이지 URL (정책 적용 전 전체 URL)
    origin: str | None = None        # 명시하지 않으면 referer 로부터 브라우저 규칙대로 유도
    content_type: str | None = None
    content_length: int | None = None  # 본문이 있으면 브라우저 위치에 (curl 은 맨 뒤에 붙임)
    extra: dict[str, str] | None = None
    cookie: str | None = None
    user_activated: bool = True      # 문서 이동이 사용자 클릭/입력으로 일어났는지


def build_headers(fp: Fingerprint, ctx: RequestContext) -> dict[str, str]:
    """파이어폭스와 같은 순서의 헤더 dict (curl 에 그대로 순서대로 전달됨)"""
    custom: dict[str, str] = {k.lower(): v for k, v in (ctx.extra or {}).items()}
    is_xhr = ctx.kind.is_script
    site = sec_fetch_site(ctx.url, ctx.referer)

    h: dict[str, str] = {
        "user-agent": fp.user_agent,
        "accept": custom.pop("accept", ACCEPT_XHR if is_xhr else ACCEPT_DOCUMENT),
        "accept-language": fp.accept_language,
        "accept-encoding": ACCEPT_ENCODING,
        "te": TE,
    }
    if priority := PRIORITY[ctx.kind]:
        h["priority"] = priority
    if ref := referer_for(ctx.url, ctx.referer):
        h["referer"] = ref
    if ctype := custom.pop("content-type", None) or ctx.content_type:
        h["content-type"] = ctype   # 직접 지정한 content-type(multipart 등)도 같은 위치
    if ctx.content_length is not None:
        h["content-length"] = str(ctx.content_length)
    if ctx.cookie:
        h["cookie"] = ctx.cookie

    if is_xhr:
        h["sec-fetch-site"] = site if site is not SecFetchSite.NONE else SecFetchSite.SAME_ORIGIN
        h["sec-fetch-mode"] = SecFetchMode.CORS
        h["sec-fetch-dest"] = SecFetchDest.EMPTY
        origin = ctx.origin
        if origin is None and ctx.referer and (
            not ctx.method.is_safe or site is not SecFetchSite.SAME_ORIGIN
        ):
            origin = origin_of(ctx.referer)
        tail = _XHR_TAIL
    else:
        h["upgrade-insecure-requests"] = "1"
        h["sec-fetch-site"] = site
        h["sec-fetch-mode"] = SecFetchMode.NAVIGATE
        if ctx.user_activated:
            h["sec-fetch-user"] = "?1"
        h["sec-fetch-dest"] = SecFetchDest.DOCUMENT
        origin = ctx.origin if not ctx.method.is_safe else None
        tail = _DOC_TAIL
    if origin:
        h["origin"] = origin

    ordered: dict[str, str] = {k: h[k] for k in (*_HEAD, *_BODY) if k in h}
    ordered.update(custom)
    ordered.update({k: h[k] for k in (*_AFTER_CUSTOM, *tail) if k in h})
    return ordered
