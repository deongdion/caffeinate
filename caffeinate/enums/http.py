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

    [실측 2026-11-13] 카페 프론트의 API 호출은 거의 모두 XMLHttpRequest(axios).
    파이어폭스는 XMLHttpRequest 에는 priority 헤더를 보내지 않고, fetch() 에는 u=4 를 보낸다.
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
