"""카페: 내 카페 목록, 카페 식별자 해석"""
import asyncio
import re

from ..core import endpoints
from ..core.config import CAFE_SECTION_HOME, CAFE_WEB_ORIGIN
from ..core.errors import CaffeinateError, ParseError
from ..models import Cafe
from ..utils.parsing import JSON, as_list, dig, parse_cafe_url
from .base import BaseService

_RE_SLUG = re.compile(r"^[A-Za-z0-9_-]+$")
_RE_CLUBID = (
    re.compile(r'clubid[=":]+\s*(\d+)', re.IGNORECASE),
    re.compile(r'"cafeId"\s*:\s*(\d+)'),
)
# MyCafeListGNBView.nhn 의 카페 항목: slug + 이름 [실측 2026-11-12]
_RE_GNB_ITEM = re.compile(
    r'<div class="cafe_name">\s*<h5><a[^>]*href="https://cafe\.naver\.com/([A-Za-z0-9_-]+)"[^>]*>\s*([^<]+?)\s*</a>',
    re.DOTALL,
)


class CafeService(BaseService):
    async def my_cafes_raw(self, *, count: int = 50) -> JSON:
        """카페홈 homepc 응답 원본"""
        return await self.session.get_json(
            endpoints.CAFE_HOME_PC,
            params={"myCafeCount": count, "useMyCafeEvent": "true", "articleCount": 3},
            referer=CAFE_SECTION_HOME,
        )

    async def my_cafes(self, *, count: int = 50) -> list[Cafe]:
        """내가 가입한 카페 목록 (로그인 필요 - 비로그인이면 빈 목록)

        [실측 2026-11-12] homepc myCafe.cafes 가 가입 직후/일부 계정에서 빈 배열 -> 레거시 GNB 로 폴백
        """
        data = await self.my_cafes_raw(count=count)
        rows = [Cafe.from_api(c) for c in as_list(dig(data, "result", "myCafe", "cafes"))]
        return rows or await self.my_cafes_gnb()

    async def my_cafes_gnb(self) -> list[Cafe]:
        """내 카페 목록 폴백: MyCafeListGNBView.nhn (cp949 HTML) - 카페 ID 는 slug 마다 조회"""
        resp = await self.session.get(endpoints.MY_CAFE_GNB, referer=f"{CAFE_WEB_ORIGIN}/")
        if resp.status_code != 200:
            return []
        html = resp.content.decode("cp949", errors="replace")
        items = list(dict(_RE_GNB_ITEM.findall(html)).items())  # slug 중복 제거, 순서 유지

        async def to_cafe(slug: str, name: str) -> Cafe:
            try:
                cafe_id = await self.id_from_slug(slug)
            except CaffeinateError:
                cafe_id = 0
            return Cafe(cafe_id=cafe_id, name=name, url=slug)

        return list(await asyncio.gather(*(to_cafe(slug, name) for slug, name in items)))

    async def resolve_id(self, value: int | str) -> int:
        """카페 ID / slug / URL -> cafeId"""
        s = str(value).strip()
        if s.isdigit():
            return int(s)
        parsed = parse_cafe_url(s)
        if isinstance(parsed["cafe_id"], int):
            return parsed["cafe_id"]
        slug = parsed["cafe_url"]
        if not isinstance(slug, str) or not _RE_SLUG.match(slug):
            raise ParseError(f"카페를 해석할 수 없습니다: {value}")
        return await self.id_from_slug(slug)

    async def id_from_slug(self, slug: str) -> int:
        """cafe.naver.com/{slug} 페이지에서 clubid 추출 (실측)"""
        html = await self.session.get_html(f"{CAFE_WEB_ORIGIN}/{slug}", referer=f"{CAFE_WEB_ORIGIN}/")
        for rx in _RE_CLUBID:
            if m := rx.search(html):
                return int(m.group(1))
        raise ParseError(f"slug '{slug}'에서 clubid를 찾지 못했습니다 (카페가 존재하는지 확인)")
