"""카페 모델"""
from dataclasses import dataclass, field
from typing import Any, Self

from ..enums import CafeOpenType
from ..utils.parsing import JSON, as_dict, as_int, pick


def _open_type(value: Any) -> CafeOpenType | None:
    try:
        return CafeOpenType(str(value)) if value else None
    except ValueError:
        return None


@dataclass(slots=True, kw_only=True)
class Cafe:
    """카페 기본 정보 (homepc myCafe.cafes[] 또는 gw article 응답의 cafe)"""

    cafe_id: int
    name: str = ""
    url: str = ""                 # slug (cafe.naver.com/{url})
    member_count: int = 0
    introduction: str = ""
    image_url: str = ""
    # homepc myCafe.cafes[].manageCafe [실측 2026-11-24]: 내가 만든(매니저) 카페 True, 멤버로만 가입한 카페 False.
    # 부매니저/스태프로 있는 카페의 값은 미확인
    is_manager: bool = False
    # homepc myCafe.cafes[].openType (O/C/H) [실측 2026-11-24]. 응답에 없거나 모르는 값이면 None
    open_type: CafeOpenType | None = None
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @property
    def link(self) -> str:
        return f"https://cafe.naver.com/{self.url}" if self.url else f"https://cafe.naver.com/f-e/cafes/{self.cafe_id}"

    @classmethod
    def from_api(cls, d: Any) -> Self:
        d = as_dict(d)
        # homepc myCafe.cafes[] 는 cafeThumbnailPcUrl / cafeIconImageUrl [실측 2026-11-13]
        image = pick(d, "image", "cafeImage", "thumbnail", "cafeIconImageUrl", "cafeThumbnailPcUrl")
        return cls(
            cafe_id=as_int(pick(d, "cafeId", "id", "clubId", "clubid", "cafeid")),
            name=str(pick(d, "cafeName", "name", "pcCafeName", "cafeNm", default="")),
            url=str(pick(d, "cafeUrl", "url", "cafeURL", "cafeUrlPath", default="")),
            member_count=as_int(pick(d, "memberCount", "memberListTotalCount", "cafeMemberCount")),
            introduction=str(pick(d, "introduction", default="")),
            image_url=str(image.get("url", "")) if isinstance(image, dict) else str(image or ""),
            is_manager=d.get("manageCafe") in (True, "Y", "true"),
            open_type=_open_type(d.get("openType")),
            raw=d,
        )
