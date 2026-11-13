"""예외 계층

    CaffeinateError                 이 라이브러리의 모든 예외 (except CaffeinateError 로 한 번에 잡기)
    ├── NaverAPIError               서버 응답 오류 (status / code / body 속성)
    │   └── NotLoggedInError        로그인 필요 / 쿠키 만료 -> 다시 로그인
    ├── NetworkError                재시도 후에도 실패한 연결/타임아웃
    ├── ParseError (ValueError)     URL/식별자/응답 해석 실패
    └── LoginError                  브라우저 로그인 흐름 실패

각 예외는 `hint` 속성(해결 방법 안내, 없으면 None)을 가진다. str(e) 에도 붙어 나온다.
"""

LOGIN_HINT = (
    "로그인 쿠키가 없거나 만료되었습니다. `python login.py` 또는 "
    "`await Caffeinate.login(options=LoginOptions(...))` 로 다시 로그인하세요."
)


class CaffeinateError(Exception):
    """이 라이브러리의 최상위 예외"""

    hint: str | None = None  # 사용자가 할 일 (클래스 기본값, 인스턴스별로 덮어쓸 수 있음)

    def __str__(self) -> str:
        msg = super().__str__()
        hint = self.hint
        if hint and hint not in msg:
            return f"{msg}\n  -> {hint}" if msg else hint
        return msg


class NaverAPIError(CaffeinateError):
    """네이버 API 응답 오류 (HTTP 상태 또는 응답 본문의 에러 코드)

    - status : HTTP 상태 코드 (서버 요청 전에 막힌 경우 None)
    - code   : 응답 본문의 에러 코드 문자열 (예: "0004", "2001", "40003")
    - body   : 응답 본문 앞부분 (최대 500자, 디버깅용)
    """

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

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.args[0]!r}, status={self.status!r}, code={self.code!r})"


class NotLoggedInError(NaverAPIError):
    """로그인이 필요한 API 를 비로그인/만료 쿠키로 호출 (NaverAPIError 의 하위 클래스)"""

    hint = LOGIN_HINT


class NetworkError(CaffeinateError):
    """재시도 후에도 실패한 네트워크 오류"""

    hint = "네트워크/프록시 상태를 확인하거나 Settings(timeout=..., max_retries=...) 를 늘려 보세요."


class ParseError(CaffeinateError, ValueError):
    """URL/카페/게시글 식별자 또는 응답을 해석하지 못함"""


class LoginError(CaffeinateError):
    """브라우저 로그인 흐름 실패 (브라우저 없음, 자격증명 오류, 보호조치, 시간 초과 등)"""
