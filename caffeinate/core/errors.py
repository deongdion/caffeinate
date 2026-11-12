"""예외 계층"""


class CaffeinateError(Exception):
    """이 라이브러리의 최상위 예외"""


class NaverAPIError(CaffeinateError):
    """네이버 API 응답 오류 (HTTP 상태 또는 응답 본문의 에러 코드)"""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        body: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.code = code


class NotLoggedInError(NaverAPIError):
    """로그인이 필요한 API 를 비로그인/만료 쿠키로 호출"""


class NetworkError(CaffeinateError):
    """재시도 후에도 실패한 네트워크 오류"""


class ParseError(CaffeinateError, ValueError):
    """URL/카페/게시글 식별자를 해석하지 못함"""


class LoginError(CaffeinateError):
    """브라우저 로그인 흐름 실패 (브라우저 없음, CDP 연결 실패, 시간 초과)"""
