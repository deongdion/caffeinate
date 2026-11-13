"""좋아요(공감)"""
from typing import Any

from ..core import endpoints
from ..core.errors import ParseError
from ..enums import ReactionType
from ..models import ArticleRef, LikeMembers, LikeStatus
from ..utils.parsing import JSON, as_dict, as_list, dig
from .base import BaseService


def content_ids(ref: ArticleRef) -> tuple[str, ...]:
    """like 서비스 cid 후보: {cafeId}_{slug}_{articleId} (slug 를 모르면 빈 튜플)

    [실측 2026-11-13] 브라우저는 {cafeId}_{slug}_{articleId} 로 요청하고, slug 는 카페의 참 slug
    (gw 게시글 응답 cafe.url) 여야 한다. 틀린 slug(대소문자만 달라도)로 조회하면 빈 결과가 아니라
    reactions=[] 인 콘텐츠와 guestToken 이 와서, 그대로 등록하면 엉뚱한 cid 에 좋아요가 쌓인다.
    예전에는 30857348 카페의 참 slug 인 "loyaltylife" 를 모든 카페의 폴백 후보로 넣었는데,
    다른 카페에서는 존재하지 않는 cid 라 제거했다 (참 slug 는 LikeService 가 게시글 상세에서 얻는다).
    """
    return (f"{ref.cafe_id}_{ref.cafe_url}_{ref.article_id}",) if ref.cafe_url else ()


class LikeService(BaseService):
    async def _true_ref(self, ref: ArticleRef) -> ArticleRef:
        """게시글 상세의 cafe.url(참 slug)로 cafe_url 을 채운 ref"""
        article = await self._client.articles.get(ref)
        slug = article.cafe.url or None
        if not slug:
            raise ParseError(f"게시글 응답에 카페 slug(cafe.url)가 없습니다: {ref.link}")
        return ArticleRef(cafe_id=ref.cafe_id, article_id=ref.article_id, menu_id=ref.menu_id, cafe_url=slug)

    async def _search(self, r: ArticleRef, cid: str) -> JSON:
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
        return as_dict(next(iter(as_list(dig(data, "contents"))), None))

    async def status(self, ref: ArticleRef | str) -> LikeStatus:
        """좋아요 수 / 내가 눌렀는지 [실측]

        URL 에서 얻은 slug 로 먼저 조회하고, 반응이 비어 있으면(틀린 slug 이거나 좋아요 0개)
        게시글 상세에서 참 slug 를 얻어 다시 조회한다.
        """
        r = await self._client.articles.resolve(ref)
        tried: dict[str, JSON] = {}
        for cid in content_ids(r):
            tried[cid] = content = await self._search(r, cid)
            if as_list(content.get("reactions")):
                return LikeStatus.from_api(content, cid)
        true_ref = await self._true_ref(r)
        cid = content_ids(true_ref)[0]
        content = tried[cid] if cid in tried else await self._search(true_ref, cid)
        return LikeStatus.from_api(content, cid)

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
            headers=dict(endpoints.PRODUCT_HEADERS),  # [실측 2026-11-13] 프론트는 apis/gw XHR 전부에 붙인다
            referer=endpoints.article_page(r.cafe_id, r.article_id),
        )
        return LikeMembers.from_api(dig(data, "result", default={}))

    async def _react(self, ref: ArticleRef | str, reaction: ReactionType, method: str) -> Any:
        """등록/취소. 틀린 slug 로도 토큰이 발급되므로(실측) 항상 게시글 상세의 참 slug 로 cid 를 만든다"""
        self._require_login()  # 비로그인 좋아요는 gw 조회 단계(401 0004)에서 막히므로 미리 막는다
        r = await self._true_ref(await self._client.articles.resolve(ref))
        for cid in content_ids(r):
            got = await self._guest_token(r, cid)
            if got is None:
                continue  # 토큰 발급 실패
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
        raise ParseError(f"like 위젯 토큰을 발급받지 못했습니다: {r.link}")

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
