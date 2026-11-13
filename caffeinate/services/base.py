"""서비스 공통 베이스 + 공개 입력 타입 (CafeLike, ImageLike)"""
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

from ..core.errors import NotLoggedInError, ParseError
from ..core.session import CafeSession
from ..models import UploadedImage
from ..utils.parsing import is_ascii_digits

if TYPE_CHECKING:
    from ..lib import Caffeinate

CafeLike: TypeAlias = int | str
"""카페 식별자: 숫자 ID(18886295), 숫자 문자열("18886295"), slug("remonterace"), 카페 URL"""

ImageLike: TypeAlias = UploadedImage | bytes | str | Path | tuple[bytes, str]
"""이미지 입력: 이미 올린 UploadedImage, bytes, 파일 경로(str/Path), (bytes, 파일명) 튜플"""


def image_source(image: bytes | str | Path | tuple[bytes, str], filename: str | None = None) -> tuple[bytes, str]:
    """업로드 전 이미지 입력 -> (데이터, 파일명). bytes 의 기본 파일명은 image.png (MIME 은 시그니처로도 판단)"""
    if isinstance(image, tuple):
        data, name = image
        return bytes(data), filename or name
    if isinstance(image, bytes | bytearray):
        return bytes(image), filename or "image.png"
    p = Path(image)
    return p.read_bytes(), filename or p.name


class BaseService:
    """기능별 API 묶음. 세션을 공유하고, 다른 서비스는 client 를 통해 접근한다."""

    def __init__(self, client: "Caffeinate") -> None:
        self._client = client

    @property
    def session(self) -> CafeSession:
        """클라이언트가 공유하는 CafeSession"""
        return self._client.session

    async def _cafe_id(self, cafe: CafeLike) -> int:
        """CafeLike -> 숫자 cafeId. 숫자면 그대로, slug/URL 은 cafes.resolve_id (클라이언트 캐시 사용)"""
        if isinstance(cafe, bool):
            raise ParseError(f"카페 식별자가 아닙니다: {cafe!r}")
        if isinstance(cafe, int):
            return cafe
        s = str(cafe).strip()
        if is_ascii_digits(s):
            return int(s)
        return await self._client.cafes.resolve_id(s)

    def _require_login(self) -> None:
        """쓰기 전 로그인 쿠키 확인 - 없으면 서버에 요청을 보내지 않고 막는다

        [실측 2026-11-13] 쿠키가 없으면 editor 스택은 500(10004 NaverUser 인증 실패)을 돌려주므로,
        로컬에서 먼저 NotLoggedInError 로 변환한다. 쿠키가 있어도 만료면 서버 오류코드로 걸러진다.
        """
        if not self.session.cookies.has_login:
            raise NotLoggedInError("로그인 쿠키가 없습니다.")


def gw_params(cafe: int | str, **extra: str | int) -> dict[str, str | int]:
    """gw v4 경로의 카페 부분이 숫자 ID 면 useCafeId=true, slug 면 false (실측: 반대면 400)"""
    is_id = isinstance(cafe, int) or is_ascii_digits(str(cafe))
    return {"useCafeId": "true" if is_id else "false", **extra}
