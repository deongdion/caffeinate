"""회원: 로그인 식별자, 카페 가입 여부, 내 정보"""
from ..core import endpoints
from ..core.config import CAFE_SECTION_HOME
from ..core.errors import NaverAPIError, NotLoggedInError
from ..models import CafeGrade, Identifier, Membership, MyInfo
from ..utils.parsing import dig
from .base import BaseService


class MemberService(BaseService):
    async def identifier(self, cafe_id: int | None = None) -> Identifier:
        """로그인 계정 식별 정보 [실측: message.result]"""
        data = await self.session.get_json(
            endpoints.MEMBER_IDENTIFIER,
            params={"cafeId": cafe_id} if cafe_id else None,
            headers=dict(endpoints.PRODUCT_HEADERS),  # [실측 2026-11-13] 프론트는 apis/gw XHR 전부에 붙인다
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

    async def grade(self, cafe_id: int) -> CafeGrade:
        """카페 내 내 등급/활동 통계 [실측 2026-11-13]

        cafemain v1.0 cafes/{id}/my?memberDataOptions=NFLEA - memberLevel(level/levelName/config),
        memberStat(방문/글/댓글/좋아요). 카페 멤버가 아니면 NaverAPIError(500, 40003).
        """
        data = await self.session.get_json(
            endpoints.cafe_my(cafe_id),
            params={"memberDataOptions": "NFLEA"},
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cafe_id),
        )
        return CafeGrade.from_api(dig(data, "result"))

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
                info.grade = CafeGrade(
                    nickname=membership.cafe_nickname,
                    member_key=membership.member_key,
                    level=membership.level,
                    level_name=membership.level_name,
                    stats=membership.stats,
                )
            else:
                info.grade = await self.grade(cafe_id)
        return info
