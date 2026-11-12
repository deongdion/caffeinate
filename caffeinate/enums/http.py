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
        """크롬이 같은 출처 요청에서 Origin 헤더를 생략하는 메서드"""
        return self in (HttpMethod.GET, HttpMethod.HEAD)


class RequestKind(StrEnum):
    """요청 성격: 페이지 JS fetch(XHR) 인지, 문서 이동(주소창/링크) 인지"""

    XHR = "xhr"
    DOCUMENT = "document"


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
