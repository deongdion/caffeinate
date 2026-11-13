"""회원: 로그인 식별자, 카페 가입 여부, 내 정보"""
from ..core import endpoints
from ..core.config import CAFE_SECTION_HOME
from ..core.errors import NaverAPIError, NotLoggedInError
from ..models import CafeGrade, Identifier, Membership, MyInfo
from ..utils.parsing import dig
from .base import BaseService, CafeLike


class MemberService(BaseService):
    """회원 기능 (`cafe.members`). cafe_id 인자는 숫자 ID / slug / 카페 URL 모두 받는다."""

    async def identifier(self, cafe_id: CafeLike | None = None) -> Identifier:
        """로그인 계정 식별 정보 -> Identifier [실측: message.result]

        - cafe_id: 주면 그 카페 기준 정보(카페 내 닉네임 등)도 함께 온다

            ident = await cafe.members.identifier()
            print(ident.logged_in, ident.user_id)
        """
        cid = await self._cafe_id(cafe_id) if cafe_id else None
        data = await self.session.get_json(
            endpoints.MEMBER_IDENTIFIER,
            params={"cafeId": cid} if cid else None,
            headers=dict(endpoints.PRODUCT_HEADERS),  # [실측 2026-11-13] 프론트는 apis/gw XHR 전부에 붙인다
            referer=endpoints.cafe_page(cid) if cid else CAFE_SECTION_HOME,
        )
        return Identifier.from_api(dig(data, "message", "result") or dig(data, "result"))

    async def is_logged_in(self) -> bool:
        """서버에 물어 실제 로그인 상태인지 (쿠키 만료 검사). 오류면 False"""
        try:
            return (await self.identifier()).logged_in
        except NaverAPIError:
            return False

    async def membership(self, cafe_id: CafeLike) -> Membership:
        """카페 가입 여부/카페 내 정보 -> Membership [실측, 로그인 필요 - 비로그인 401 NotLoggedInError]

            m = await cafe.members.membership("deongdion")
        """
        cid = await self._cafe_id(cafe_id)
        data = await self.session.get_json(
            endpoints.cafe_members(cid),
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cid),
        )
        return Membership.from_api(dig(data, "result"))

    async def grade(self, cafe_id: CafeLike) -> CafeGrade:
        """카페 내 내 등급/활동 통계 -> CafeGrade [실측 2026-11-13]

        cafemain v1.0 cafes/{id}/my?memberDataOptions=NFLEA - memberLevel(level/levelName/config),
        memberStat(방문/글/댓글/좋아요). 카페 멤버가 아니면 PermissionDeniedError(500, 40003).
        """
        cid = await self._cafe_id(cafe_id)
        data = await self.session.get_json(
            endpoints.cafe_my(cid),
            params={"memberDataOptions": "NFLEA"},
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cid),
        )
        return CafeGrade.from_api(dig(data, "result"))

    async def my_info(self, cafe_id: CafeLike) -> MyInfo:
        """내 정보 통합 -> MyInfo: 계정 식별자 + 카페 내 멤버 정보 (+ 멤버면 등급/활동 통계). 로그인 필요

        [실측] 멤버면 members 응답에 nickname/memberLevel/memberStat 이 들어 있다 (없을 때만 등급 후보 조회).

            info = await cafe.members.my_info("deongdion")
            print(info.nickname, info.is_member, info.grade)
        """
        cid = await self._cafe_id(cafe_id)
        ident = await self.identifier(cid)
        if not ident.logged_in:
            raise NotLoggedInError("이 기능은 네이버 로그인이 필요합니다")
        membership = await self.membership(cid)
        info = MyInfo(cafe_id=cid, identifier=ident, membership=membership)
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
                info.grade = await self.grade(cid)
        return info
