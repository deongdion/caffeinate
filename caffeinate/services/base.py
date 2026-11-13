"""서비스 공통 베이스"""
from typing import TYPE_CHECKING

from ..core.errors import NotLoggedInError
from ..core.session import CafeSession

if TYPE_CHECKING:
    from ..lib import Caffeinate


class BaseService:
    """기능별 API 묶음. 세션을 공유하고, 다른 서비스는 client 를 통해 접근한다."""

    def __init__(self, client: "Caffeinate") -> None:
        self._client = client

    @property
    def session(self) -> CafeSession:
        return self._client.session

    def _require_login(self) -> None:
        """쓰기 전 로그인 쿠키 확인 - 없으면 서버에 요청을 보내지 않고 막는다

        [실측 2026-11-13] 쿠키가 없으면 editor 스택은 500(10004 NaverUser 인증 실패)을 돌려주므로,
        로컬에서 먼저 NotLoggedInError 로 변환한다. 쿠키가 있어도 만료면 서버 오류코드로 걸러진다.
        """
        if not self.session.cookies.has_login:
            raise NotLoggedInError("로그인 쿠키가 없습니다. Caffeinate.login() 으로 먼저 로그인하세요.")


def gw_params(cafe: int | str, **extra: str | int) -> dict[str, str | int]:
    """gw v4 경로의 카페 부분이 숫자 ID 면 useCafeId=true, slug 면 false (실측: 반대면 400)"""
    is_id = isinstance(cafe, int) or str(cafe).isdigit()
    return {"useCafeId": "true" if is_id else "false", **extra}
