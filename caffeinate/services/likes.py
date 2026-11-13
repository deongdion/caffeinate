"""좋아요(공감)"""
from typing import Any

from ..core import endpoints
from ..core.errors import ParseError
from ..enums import ReactionType
from ..models import ArticleRef, LikeMembers, LikeStatus
from ..utils.parsing import as_list, dig
from .base import BaseService


def content_ids(ref: ArticleRef) -> tuple[str, str]:
    """like 서비스 cid 후보들 (조회가 비면 다음 후보 사용)

    [실측 2026-11-13 사람 세션 캡처] 브라우저는 {cafeId}_loyaltylife_{articleId} 로 요청하고,
    기존 실측(E2E 성공)은 {cafeId}_{slug}_{articleId}. 두 네임스페이스가 공존하므로
    slug 조회가 비면 loyaltylife 로 다시 시도한다.
    """
    return (
        f"{ref.cafe_id}_{ref.cafe_url}_{ref.article_id}",
        f"{ref.cafe_id}_loyaltylife_{ref.article_id}",
    )


class LikeService(BaseService):
    async def _full_ref(self, ref: ArticleRef | str) -> ArticleRef:
        r = await self._client.articles.resolve(ref)
        if r.cafe_url:
            return r
        # slug 를 모르면 게시글 상세에서 cafe.url 을 얻는다
        article = await self._client.articles.get(r)
        return article.ref

    async def status(self, ref: ArticleRef | str) -> LikeStatus:
        """좋아요 수 / 내가 눌렀는지 [실측]"""
        r = await self._full_ref(ref)
        contents: list[Any] = []
        cid = ""
        for cid in content_ids(r):
            data = await self.session.get_json(
                endpoints.LIKE_SEARCH,
                params={
                    "suppress_response_codes": "true",
                    "q": f"CAFE[{cid}]",
                    "isDuplication": "false",
                    "cssIds": "MULTI_PC,CAFE_PC",
                },
                referer=endpoints.article_page(r.cafe_id, r.article_id),
            )
            contents = as_list(dig(data, "contents"))
            if contents:
                break
        return LikeStatus.from_api(contents[0] if contents else {}, cid)

    async def like(self, ref: ArticleRef | str, reaction: ReactionType = ReactionType.LIKE) -> Any:
        """좋아요 등록 [실측 2026-11-12 / 2026-11-13 사람 세션 재확인]"""
        return await self._react(ref, reaction, "POST")

    async def unlike(self, ref: ArticleRef | str, reaction: ReactionType = ReactionType.LIKE) -> Any:
        """좋아요 취소 [실측 2026-11-12 / 2026-11-13 사람 세션 재확인]"""
        return await self._react(ref, reaction, "DELETE")

    async def members(self, ref: ArticleRef | str, *, per_page: int = 10) -> LikeMembers:
        """좋아요 누른 멤버 목록

        [실측 2026-11-13 사람 세션 캡처 + 라이브 응답 확인] 좋아요 클릭 후 브라우저가
        gw/v5 likeIt/members?perPage=10 을 호출한다.
        result: {totalCount, nextTimestamp, users[{nick, memberKey, likeItTime, isCafeMember,...}],
                 article{isLikeIt}, cafe{id, name, url(진짜 slug)}}.
        like 서비스 cid 는 이 cafe.url(slug) 기준이다 - 별칭으로 resolve 했으면 여기서 참 slug 확인 가능.
        """
        self._require_login()
        r = await self._client.articles.resolve(ref)
        data = await self.session.get_json(
            endpoints.like_members(r.cafe_id, r.article_id, per_page),
            referer=endpoints.article_page(r.cafe_id, r.article_id),
        )
        return LikeMembers.from_api(dig(data, "result", default={}))

    async def _react(self, ref: ArticleRef | str, reaction: ReactionType, method: str) -> Any:
        self._require_login()  # 비로그인 좋아요는 gw 조회 단계(401 0004)에서 막히므로 미리 막는다
        r = await self._full_ref(ref)
        for cid in content_ids(r):
            got = await self._guest_token(r, cid)
            if got is None:
                continue  # 이 cid 로는 콘텐츠가 없음 -> 다음 후보
            token, issued_at = got
            return await self.session.get_json(
                endpoints.like_content(cid),
                params={
                    "suppress_response_codes": "true",
                    "_method": method,
                    "displayId": "CAFE",
                    "reactionType": reaction.value,
                    "categoryId": r.cafe_id,
                    "guestToken": token,
                    "timestamp": issued_at,
                    "_ch": "pcw",
                    "isDuplication": "false",
                    "lang": "ko",
                    "countType": "default",
                    "count": 1,
                    "history": "",
                    "runtimeStatus": "",
                    "isPostTimeline": "false",
                },
                referer=endpoints.article_page(r.cafe_id, r.article_id),
            )
        raise ParseError("like 콘텐츠를 찾지 못했습니다 (slug/loyaltylife 모두 조회 실패)")

    async def _guest_token(self, r: ArticleRef, cid: str) -> tuple[str, int] | None:
        """like 위젯 토큰 -> (guestToken, timestamp). 콘텐츠가 없으면 None.

        [실측] 등록/취소 요청의 timestamp 는 현재 시각이 아니라 이 search 응답의 timestamp 여야 한다.
        토큰이 발급 시각에 묶여 있어, 다른 값을 보내면 4013 이 온다.
        """
        data = await self.session.get_json(
            endpoints.LIKE_ROUTE_SEARCH,
            params={
                "suppress_response_codes": "true",
                "q": f"CAFE[{cid}]",
                "isDuplication": "false",
                "cssIds": "BASIC_PC,CAFE_PC",
                "pool": "cafe",
            },
            referer=endpoints.article_page(r.cafe_id, r.article_id),
        )
        token = str(dig(data, "guestToken") or "")
        issued_at = dig(data, "timestamp")
        if not token or not isinstance(issued_at, int):
            return None
        return token, issued_at
