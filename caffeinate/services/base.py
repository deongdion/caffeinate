"""서비스 공통 베이스"""
from typing import TYPE_CHECKING

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


def gw_params(cafe: int | str, **extra: str | int) -> dict[str, str | int]:
    """gw v4 경로의 카페 부분이 숫자 ID 면 useCafeId=true, slug 면 false (실측: 반대면 400)"""
    is_id = isinstance(cafe, int) or str(cafe).isdigit()
    return {"useCafeId": "true" if is_id else "false", **extra}
