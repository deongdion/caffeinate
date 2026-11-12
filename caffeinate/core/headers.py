"""
실제 크롬과 같은 헤더 구성 (순서/값/Fetch Metadata/Referer 정책)

2026-11-12 실측 (Chrome 157, tls.peet.ws HTTP/2 HEADERS 프레임) :

  XHR(fetch) : [content-length], sec-ch-ua-platform, user-agent, sec-ch-ua, [content-type], [커스텀 x-...],
               sec-ch-ua-mobile, accept, [origin], sec-fetch-site, sec-fetch-mode,
               sec-fetch-dest, [referer], accept-encoding, accept-language, [cookie], priority
  문서 이동  : sec-ch-ua, sec-ch-ua-mobile, sec-ch-ua-platform, upgrade-insecure-requests,
               user-agent, accept, sec-fetch-site, sec-fetch-mode, sec-fetch-user,
               sec-fetch-dest, [referer], accept-encoding, accept-language, [cookie], priority

  - 페이지 JS 가 붙인 헤더(content-type, x-cafe-product 등)는 sec-ch-ua 바로 뒤
  - origin 은 sec-fetch-site 앞. 같은 출처 GET 에는 없고, 교차 출처(CORS)나 POST 에는 붙음
  - Referer 는 strict-origin-when-cross-origin: 교차 출처면 출처(https://host/)만 전송
"""
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

from ..enums import HttpMethod, RequestKind, SecFetchDest, SecFetchMode, SecFetchSite
from ..models.fingerprint import Fingerprint

ACCEPT_ENCODING: Final = "gzip, deflate, br, zstd"
ACCEPT_XHR: Final = "application/json, text/plain, */*"
ACCEPT_DOCUMENT: Final = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8,"
    "application/signed-exchange;v=b3;q=0.7"
)
PRIORITY: Final[dict[RequestKind, str]] = {
    RequestKind.XHR: "u=1, i",
    RequestKind.DOCUMENT: "u=0, i",
}

_XHR_HEAD: Final = ("sec-ch-ua-platform", "user-agent", "sec-ch-ua")
_XHR_TAIL: Final = (
    "sec-ch-ua-mobile", "accept", "origin", "sec-fetch-site", "sec-fetch-mode",
    "sec-fetch-dest", "referer", "accept-encoding", "accept-language", "cookie", "priority",
)
_DOC_ORDER: Final = (
    "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform", "upgrade-insecure-requests",
    "user-agent", "accept", "sec-fetch-site", "sec-fetch-mode", "sec-fetch-user",
    "sec-fetch-dest", "referer", "accept-encoding", "accept-language", "cookie", "priority",
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
    """strict-origin-when-cross-origin (크롬 기본 Referrer-Policy)"""
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
    origin: str | None = None        # 명시하지 않으면 referer 로부터 크롬 규칙대로 유도
    content_type: str | None = None
    content_length: int | None = None  # 본문이 있으면 크롬처럼 맨 앞에 (curl 은 맨 뒤에 붙임)
    extra: dict[str, str] | None = None
    cookie: str | None = None
    user_activated: bool = True      # 문서 이동이 사용자 클릭/입력으로 일어났는지


def build_headers(fp: Fingerprint, ctx: RequestContext) -> dict[str, str]:
    """크롬과 같은 순서의 헤더 dict (curl 에 그대로 순서대로 전달됨)"""
    custom: dict[str, str] = {}
    if ctx.content_type:
        custom["content-type"] = ctx.content_type
    for k, v in (ctx.extra or {}).items():
        custom[k.lower()] = v

    base: dict[str, str] = {
        "sec-ch-ua": fp.sec_ch_ua,
        "sec-ch-ua-mobile": fp.sec_ch_ua_mobile,
        "sec-ch-ua-platform": fp.sec_ch_ua_platform,
        "user-agent": fp.user_agent,
        "accept-encoding": ACCEPT_ENCODING,
        "accept-language": fp.accept_language,
        "priority": PRIORITY[ctx.kind],
    }
    site = sec_fetch_site(ctx.url, ctx.referer)
    if ref := referer_for(ctx.url, ctx.referer):
        base["referer"] = ref
    if ctx.cookie:
        base["cookie"] = ctx.cookie

    if ctx.kind is RequestKind.XHR:
        base["accept"] = custom.pop("accept", ACCEPT_XHR)
        base["sec-fetch-site"] = site if site is not SecFetchSite.NONE else SecFetchSite.SAME_ORIGIN
        base["sec-fetch-mode"] = SecFetchMode.CORS
        base["sec-fetch-dest"] = SecFetchDest.EMPTY
        origin = ctx.origin
        if origin is None and ctx.referer and (
            not ctx.method.is_safe or site is not SecFetchSite.SAME_ORIGIN
        ):
            origin = origin_of(ctx.referer)
        if origin:
            base["origin"] = origin
        ordered = _content_length(ctx)
        ordered.update({k: base[k] for k in _XHR_HEAD if k in base})
        ordered.update(custom)
        ordered.update({k: base[k] for k in _XHR_TAIL if k in base})
        return ordered

    base["accept"] = custom.pop("accept", ACCEPT_DOCUMENT)
    base["upgrade-insecure-requests"] = "1"
    base["sec-fetch-site"] = site
    base["sec-fetch-mode"] = SecFetchMode.NAVIGATE
    if ctx.user_activated:
        base["sec-fetch-user"] = "?1"
    base["sec-fetch-dest"] = SecFetchDest.DOCUMENT
    if ctx.origin and not ctx.method.is_safe:
        base["origin"] = ctx.origin
    ordered = _content_length(ctx)
    ordered.update({k: base[k] for k in _DOC_ORDER if k in base})
    if "origin" in base:
        ordered = _insert_before(ordered, "sec-fetch-site", "origin", base["origin"])
    ordered.update(custom)
    return ordered


def _content_length(ctx: RequestContext) -> dict[str, str]:
    return {"content-length": str(ctx.content_length)} if ctx.content_length is not None else {}


def _insert_before(d: dict[str, str], anchor: str, key: str, value: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        if k == anchor:
            out[key] = value
        out[k] = v
    out.setdefault(key, value)
    return out
