"""좋아요(공감)"""
from typing import Any

from ..core import endpoints
from ..core.errors import ParseError
from ..enums import ReactionType
from ..models import ArticleRef, LikeStatus
from ..utils.parsing import as_list, dig
from .base import BaseService


def content_id(ref: ArticleRef) -> str:
    """like 서비스 cid: {cafeId}_{cafeUrl}_{articleId} (실측: slug 자리에 숫자 ID 를 넣으면 조회 결과 없음)"""
    return f"{ref.cafe_id}_{ref.cafe_url}_{ref.article_id}"


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
        cid = content_id(r)
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
        return LikeStatus.from_api(contents[0] if contents else {}, cid)

    async def like(self, ref: ArticleRef | str, reaction: ReactionType = ReactionType.LIKE) -> Any:
        """좋아요 등록 [실측 2026-11-12]"""
        return await self._react(ref, reaction, "POST")

    async def unlike(self, ref: ArticleRef | str, reaction: ReactionType = ReactionType.LIKE) -> Any:
        """좋아요 취소 [실측 2026-11-12]"""
        return await self._react(ref, reaction, "DELETE")

    async def _react(self, ref: ArticleRef | str, reaction: ReactionType, method: str) -> Any:
        self._require_login()  # 비로그인 좋아요는 gw 조회 단계(401 0004)에서 막히므로 미리 막는다
        r = await self._full_ref(ref)
        cid = content_id(r)
        token, issued_at = await self._guest_token(r)
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

    async def _guest_token(self, r: ArticleRef) -> tuple[str, int]:
        """like 위젯 토큰 -> (guestToken, timestamp)

        [실측] 등록/취소 요청의 timestamp 는 현재 시각이 아니라 이 search 응답의 timestamp 여야 한다.
        토큰이 발급 시각에 묶여 있어, 다른 값을 보내면 4013 이 온다.
        """
        data = await self.session.get_json(
            endpoints.LIKE_ROUTE_SEARCH,
            params={
                "suppress_response_codes": "true",
                "q": f"CAFE[{content_id(r)}]",
                "isDuplication": "false",
                "cssIds": "BASIC_PC,CAFE_PC",
                "pool": "cafe",
            },
            referer=endpoints.article_page(r.cafe_id, r.article_id),
        )
        token = str(dig(data, "guestToken") or "")
        issued_at = dig(data, "timestamp")
        if not token or not isinstance(issued_at, int):
            raise ParseError(f"like 토큰 응답 형식이 다름: {str(data)[:200]}")
        return token, issued_at

