"""카페: 내 카페 목록, 카페 식별자 해석"""
import asyncio
import re

from ..core import endpoints
from ..core.config import CAFE_SECTION_HOME, CAFE_WEB_ORIGIN
from ..core.errors import CafeNotFoundError, CaffeinateError, NaverAPIError, ParseError
from ..models import Cafe
from ..utils.parsing import JSON, as_list, dig, is_ascii_digits, parse_cafe_url
from .base import BaseService, CafeLike

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
    """카페 단위 기능: 내 카페 목록, slug/URL -> 카페 ID 해석 (`cafe.cafes`)"""

    _slug_lock: asyncio.Lock | None = None

    async def my_cafes_raw(self, *, count: int = 50) -> JSON:
        """카페홈 homepc 응답 원본 (JSON dict). 보통은 my_cafes() 를 쓴다.

        - count: 받을 카페 수 (myCafeCount)
        """
        return await self.session.get_json(
            endpoints.CAFE_HOME_PC,
            params={"myCafeCount": count, "useMyCafeEvent": "true", "articleCount": 3},
            headers=dict(endpoints.PRODUCT_HEADERS),  # [실측 2026-11-13] 프론트는 apis/gw XHR 전부에 붙인다
            referer=CAFE_SECTION_HOME,
        )

    async def my_cafes(self, *, count: int = 50) -> list[Cafe]:
        """내가 가입한 카페 목록 -> list[Cafe] (로그인 필요 - 비로그인이면 빈 목록)

            for c in await cafe.cafes.my_cafes():
                print(c.cafe_id, c.url, c.name)

        [실측 2026-11-13] homepc 응답은 message.result.myCafe.cafes[] 이다 (최상위 result 아님).
        예전에는 result.myCafe.cafes 를 읽어 항상 빈 목록 -> GNB 폴백(카페마다 HTML 요청)으로 빠졌다.
        목록이 정말 비면 레거시 GNB 로 폴백한다.
        """
        data = await self.my_cafes_raw(count=count)
        cafes = dig(data, "message", "result", "myCafe", "cafes") or dig(data, "result", "myCafe", "cafes")
        rows = [Cafe.from_api(c) for c in as_list(cafes)]
        return rows or await self.my_cafes_gnb()

    async def my_cafes_gnb(self) -> list[Cafe]:
        """내 카페 목록 폴백 -> list[Cafe]: MyCafeListGNBView.nhn (cp949 HTML) - 카페 ID 는 slug 마다 조회

        slug 마다 카페 홈 HTML 을 받으므로, 짧은 시간 대량 요청이 되지 않게 순서대로 조회한다.
        """
        resp = await self.session.get(endpoints.MY_CAFE_GNB, referer=f"{CAFE_WEB_ORIGIN}/")
        if resp.status_code != 200:
            return []
        html = resp.content.decode("cp949", errors="replace")
        items = list(dict(_RE_GNB_ITEM.findall(html)).items())  # slug 중복 제거, 순서 유지

        out: list[Cafe] = []
        for slug, name in items:
            try:
                cafe_id = await self.id_from_slug(slug)
            except CaffeinateError:
                cafe_id = 0
            out.append(Cafe(cafe_id=cafe_id, name=name, url=slug))
        return out

    async def resolve_id(self, value: CafeLike) -> int:
        """카페 ID / 숫자 문자열 / slug / 카페 URL -> 숫자 cafeId

        slug 는 카페 홈 HTML 을 한 번 받아 해석하고, 결과는 클라이언트 메모리에 캐시한다
        (같은 클라이언트에서 다시 물으면 네트워크 요청 없음). 모든 서비스의 `cafe` 인자가 이 메서드를 쓴다.

            await cafe.cafes.resolve_id("remonterace")                      # -> 18886295
            await cafe.cafes.resolve_id("https://cafe.naver.com/remonterace")
        """
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        s = str(value).strip()
        if is_ascii_digits(s):
            return int(s)
        parsed = parse_cafe_url(s)
        if isinstance(parsed["cafe_id"], int):
            return parsed["cafe_id"]
        slug = parsed["cafe_url"]
        if not isinstance(slug, str) or not _RE_SLUG.match(slug):
            raise ParseError(f"카페를 해석할 수 없습니다: {value}")
        return await self.id_from_slug(slug)

    async def id_from_slug(self, slug: str) -> int:
        """slug -> cafeId. cafe.naver.com/{slug} 페이지에서 clubid 추출 (실측), 클라이언트 캐시 사용

        없는 카페(HTTP 404)는 CafeNotFoundError, 페이지에 clubid 가 없으면 ParseError.
        """
        key = slug.lower()  # [추정] slug 는 대소문자 구분 없음 (네이버 카페 주소)
        cache = self._client._cafe_ids
        if key in cache:
            return cache[key]
        if self._slug_lock is None:
            self._slug_lock = asyncio.Lock()
        async with self._slug_lock:  # 같은 slug 를 동시에 물어도 한 번만 요청
            if key in cache:
                return cache[key]
            try:
                html = await self.session.get_html(f"{CAFE_WEB_ORIGIN}/{slug}", referer=f"{CAFE_WEB_ORIGIN}/")
            except NaverAPIError as e:
                if e.status == 404:
                    raise CafeNotFoundError(f"카페를 찾을 수 없습니다: {slug}", e.status, e.body) from e
                raise
            for rx in _RE_CLUBID:
                if m := rx.search(html):
                    cache[key] = int(m.group(1))
                    return cache[key]
        raise ParseError(f"slug '{slug}'에서 clubid를 찾지 못했습니다 (카페가 존재하는지 확인)")
