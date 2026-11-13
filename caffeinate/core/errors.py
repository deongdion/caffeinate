"""예외 계층

    CaffeinateError                 이 라이브러리의 모든 예외 (except CaffeinateError 로 한 번에 잡기)
    ├── NaverAPIError               서버 응답 오류 (status / code / body 속성)
    │   ├── NotLoggedInError        로그인 필요 / 쿠키 만료 (0004, 10004, HTTP 401) -> 다시 로그인
    │   ├── ArticleNotFoundError    없는/삭제된 게시글 (4003, HTTP 404)
    │   ├── CafeNotFoundError       없는 카페 (0010)
    │   ├── PermissionDeniedError   권한 없음: 멤버 전용 (4004), 비멤버/등급 부족 (40003)
    │   └── RateLimitedError        요청 제한: 댓글 연속 등록 (2001), 재시도 후에도 HTTP 429
    ├── NetworkError                재시도 후에도 실패한 연결/타임아웃
    ├── ParseError (ValueError)     URL/식별자/응답 해석 실패
    └── LoginError                  브라우저 로그인 흐름 실패

각 예외는 `hint` 속성(해결 방법 안내, 없으면 None)을 가진다. str(e) 에도 붙어 나온다.
NaverAPIError 하위 클래스는 서버 에러 코드/HTTP 상태로 고른다 (`api_error_class`, 표 `ERROR_CODES` /
`ERROR_STATUSES`). 모두 NaverAPIError 이므로 기존 `except NaverAPIError` / `e.code` 검사는 그대로 동작한다.
"""

LOGIN_HINT = (
    "로그인 쿠키가 없거나 만료되었습니다. "
    "`await Caffeinate.login(options=LoginOptions(username=..., password=...))` "
    "(창에서 직접 로그인하려면 `await Caffeinate.login()`) 로 다시 로그인하세요."
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


class ArticleNotFoundError(NaverAPIError):
    """없는/삭제된 게시글 [실측 2026-11-13: gw 상세 404 / 4003]"""

    hint = "게시글이 삭제되었거나 주소(카페 ID/글 번호)가 틀렸습니다."


class CafeNotFoundError(NaverAPIError):
    """없는 카페 [실측 2026-11-13: 400 / 0010]"""

    hint = "카페 ID 또는 slug(cafe.naver.com/<slug>)가 맞는지 확인하세요."


class PermissionDeniedError(NaverAPIError):
    """권한 없음 [실측 2026-11-13: 멤버 전용 403 / 4004, 비멤버 등급 조회 500 / 40003]"""

    hint = "카페 가입 또는 등급이 필요한 기능입니다. 로그인한 계정의 가입/등급 상태를 확인하세요."


class RateLimitedError(NaverAPIError):
    """요청 제한 [실측 2026-11-13: 댓글 연속 등록 403 / 2001] 또는 재시도 후에도 HTTP 429"""

    hint = (
        "짧은 시간에 요청이 너무 많습니다. 잠시 뒤 다시 시도하고, 대량 작업은 "
        "Settings(min_request_interval=1.0) 처럼 요청 간격을 두세요 (댓글 2001 은 comment_retry_* 로 자동 재시도)."
    )


# 서버 에러 코드 -> 예외 클래스 ([실측] 값). 코드가 상태보다 우선한다.
ERROR_CODES: dict[str, type[NaverAPIError]] = {
    "0004": NotLoggedInError,         # gw/like: 로그인하지 않음
    "10004": NotLoggedInError,        # editor: NaverUser 인증 실패
    "4003": ArticleNotFoundError,     # 없는 글 (HTTP 404)
    "0010": CafeNotFoundError,        # 없는 카페 (HTTP 400)
    "4004": PermissionDeniedError,    # 멤버 전용 (HTTP 403)
    "40003": PermissionDeniedError,   # 비멤버 등급 조회 (HTTP 500)
    "2001": RateLimitedError,         # 댓글 연속 등록 (HTTP 403)
}
# 에러 코드로 정해지지 않을 때의 HTTP 상태 -> 예외 클래스
ERROR_STATUSES: dict[int, type[NaverAPIError]] = {
    401: NotLoggedInError,
    404: ArticleNotFoundError,
    429: RateLimitedError,            # 세션의 429 재시도(max_retries)를 다 쓴 뒤
}


def api_error_class(status: int | None, code: str | None) -> type[NaverAPIError]:
    """서버 오류 (HTTP 상태, 본문 에러 코드) -> 가장 구체적인 NaverAPIError 하위 클래스"""
    if code and code in ERROR_CODES:
        return ERROR_CODES[code]
    if status is not None and status in ERROR_STATUSES:
        return ERROR_STATUSES[status]
    return NaverAPIError


class NetworkError(CaffeinateError):
    """재시도 후에도 실패한 네트워크 오류"""

    hint = "네트워크/프록시 상태를 확인하거나 Settings(timeout=..., max_retries=...) 를 늘려 보세요."


class ParseError(CaffeinateError, ValueError):
    """URL/카페/게시글 식별자 또는 응답을 해석하지 못함"""


class LoginError(CaffeinateError):
    """브라우저 로그인 흐름 실패 (브라우저 없음, 자격증명 오류, 보호조치, 시간 초과 등)"""
