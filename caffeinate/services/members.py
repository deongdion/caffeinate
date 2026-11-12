"""회원: 로그인 식별자, 카페 가입 여부, 내 정보"""
from ..core import endpoints
from ..core.config import CAFE_SECTION_HOME
from ..core.errors import NaverAPIError, NotLoggedInError
from ..models import Identifier, Membership, MyInfo
from ..utils.parsing import JSON, as_dict, dig
from .base import BaseService


class MemberService(BaseService):
    async def identifier(self, cafe_id: int | None = None) -> Identifier:
        """로그인 계정 식별 정보 [실측: message.result]"""
        data = await self.session.get_json(
            endpoints.MEMBER_IDENTIFIER,
            params={"cafeId": cafe_id} if cafe_id else None,
            referer=endpoints.cafe_page(cafe_id) if cafe_id else CAFE_SECTION_HOME,
        )
        return Identifier.from_api(dig(data, "message", "result") or dig(data, "result"))

    async def is_logged_in(self) -> bool:
        try:
            return (await self.identifier()).logged_in
        except NaverAPIError:
            return False

    async def membership(self, cafe_id: int) -> Membership:
        """카페 가입 여부 [실측, 로그인 필요 - 비로그인 401]"""
        data = await self.session.get_json(
            endpoints.cafe_members(cafe_id),
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cafe_id),
        )
        return Membership.from_api(dig(data, "result"))

    async def grade(self, cafe_id: int) -> JSON | None:
        """[미확정] 카페 내 등급 - 후보 엔드포인트를 차례로 시도"""
        for url in endpoints.cafe_grade_candidates(cafe_id):
            try:
                data = await self.session.get_json(
                    url, headers=dict(endpoints.PRODUCT_HEADERS), referer=endpoints.cafe_page(cafe_id)
                )
            except NaverAPIError:
                continue
            if res := as_dict(dig(data, "result")):
                return res
        return None

    async def my_info(self, cafe_id: int) -> MyInfo:
        """내 정보 통합: 계정 식별자 + 카페 내 멤버 정보
        [실측] 멤버면 members 응답에 nickname/memberLevel/memberStat 이 들어 있다 (없을 때만 등급 후보 조회)"""
        ident = await self.identifier(cafe_id)
        if not ident.logged_in:
            raise NotLoggedInError("이 기능은 네이버 로그인이 필요합니다")
        membership = await self.membership(cafe_id)
        info = MyInfo(cafe_id=cafe_id, identifier=ident, membership=membership)
        if info.is_member:
            if membership.level_name:
                info.grade = {"level": membership.level, "levelName": membership.level_name}
            else:
                info.grade = await self.grade(cafe_id)
        return info
