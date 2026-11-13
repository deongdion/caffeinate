"""카페 모델"""
from dataclasses import dataclass, field
from typing import Any, Self

from ..utils.parsing import JSON, as_dict, as_int, pick


@dataclass(slots=True, kw_only=True)
class Cafe:
    """카페 기본 정보 (homepc myCafe.cafes[] 또는 gw article 응답의 cafe)"""

    cafe_id: int
    name: str = ""
    url: str = ""                 # slug (cafe.naver.com/{url})
    member_count: int = 0
    introduction: str = ""
    image_url: str = ""
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
            raw=d,
        )
