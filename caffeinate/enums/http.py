"""HTTP / Fetch Metadata 관련 열거형"""
from enum import StrEnum


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    HEAD = "HEAD"

    @property
    def is_safe(self) -> bool:
        """브라우저가 같은 출처 요청에서 Origin 헤더를 생략하는 메서드"""
        return self in (HttpMethod.GET, HttpMethod.HEAD)


class RequestKind(StrEnum):
    """요청 성격: 페이지 JS 요청(XMLHttpRequest / fetch) 인지, 문서 이동(주소창/링크) 인지

    [실측 2026-11-13] 카페 프론트의 API 호출(apis.naver.com, article.cafe.naver.com/gw)은
    XMLHttpRequest(axios). bff.cafe.naver.com/graphql 만 fetch().
    파이어폭스는 XMLHttpRequest 에는 priority 헤더를 보내지 않고, fetch() 에는 u=4 를 보낸다.
    헤더 순서도 다르다: fetch() 는 referer 가 accept-encoding 바로 뒤, XHR/문서는 origin 뒤.
    HTTP/2 HEADERS 프레임 우선순위 weight: 문서 42, XHR/fetch 22.
    """

    XHR = "xhr"            # XMLHttpRequest (axios) - 기본
    FETCH = "fetch"        # fetch()
    DOCUMENT = "document"

    @property
    def is_script(self) -> bool:
        return self is not RequestKind.DOCUMENT


class SecFetchSite(StrEnum):
    NONE = "none"
    SAME_ORIGIN = "same-origin"
    SAME_SITE = "same-site"
    CROSS_SITE = "cross-site"


class SecFetchMode(StrEnum):
    CORS = "cors"
    NAVIGATE = "navigate"
    NO_CORS = "no-cors"


class SecFetchDest(StrEnum):
    EMPTY = "empty"
    DOCUMENT = "document"


class ReferrerPolicy(StrEnum):
    """요청을 일으킨 페이지의 Referrer-Policy (Referer 값 결정)

    [실측 2026-11-13] cafe.naver.com 페이지(구 iframe/ca-fe/f-e 모두)는 응답 헤더
    `Referrer-Policy: unsafe-url` 을 준다 -> apis.naver.com / article.cafe.naver.com 같은
    교차 출처 요청에도 Referer 가 전체 URL(쿼리 포함)로 간다 (실제 Camoufox 캡처 확인).
    정책이 없는 페이지는 파이어폭스 기본값 strict-origin-when-cross-origin.
    """

    UNSAFE_URL = "unsafe-url"
    STRICT_ORIGIN_WHEN_CROSS_ORIGIN = "strict-origin-when-cross-origin"
    NO_REFERRER_WHEN_DOWNGRADE = "no-referrer-when-downgrade"
    ORIGIN = "origin"
    NO_REFERRER = "no-referrer"
