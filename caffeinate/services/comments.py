"""댓글/대댓글: 조회, 작성"""
from typing import Any

from ..core import endpoints
from ..models import ArticleRef, Comment, CommentPage
from ..utils.parsing import dig
from .base import BaseService, gw_params


class CommentService(BaseService):
    async def page(self, ref: ArticleRef | str, *, page: int = 1, size: int = 100) -> CommentPage:
        """댓글 한 페이지 [실측: result.comments.items, hasNext/hasPrev]"""
        r = await self._client.articles.resolve(ref)
        data = await self.session.get_json(
            endpoints.gw_comments(r.cafe_id, r.article_id),
            params=gw_params(r.cafe_id, page=page, size=size),
            referer=endpoints.article_page(r.cafe_id, r.article_id),
        )
        return CommentPage.from_api(dig(data, "result", default={}))

    async def all(self, ref: ArticleRef | str, *, max_pages: int = 20, size: int = 100) -> list[Comment]:
        """모든 댓글 (평탄화 목록, hasNext 따라 페이지 순회). 트리는 models.build_tree()"""
        r = await self._client.articles.resolve(ref)
        out: list[Comment] = []
        seen: set[int] = set()
        for n in range(1, max_pages + 1):
            p = await self.page(r, page=n, size=size)
            new = [c for c in p.items if c.comment_id not in seen]
            seen.update(c.comment_id for c in new)
            out.extend(new)
            if not p.has_next or not new:
                break
        return out

    async def add(self, ref: ArticleRef | str, text: str, *, sticker_id: str = "") -> Any:
        """댓글 작성 [실측 2026-11-12: E2E 성공] cafe-mobile/CommentPost.json (form)"""
        r = await self._client.articles.resolve(ref)
        return await self._post(endpoints.COMMENT_POST, r, {"content": text, "stickerId": sticker_id})

    async def reply(self, ref: ArticleRef | str, comment_id: int, text: str, *, sticker_id: str = "") -> Any:
        """대댓글 작성 [실측 2026-11-12: E2E 성공] cafe-mobile/CommentReply.json (refCommentId=부모 댓글)"""
        r = await self._client.articles.resolve(ref)
        return await self._post(
            endpoints.COMMENT_REPLY, r, {"content": text, "stickerId": sticker_id, "refCommentId": comment_id}
        )

    async def _post(self, url: str, r: ArticleRef, fields: dict[str, Any]) -> Any:
        return await self.session.post_form(
            url,
            data={**fields, "cafeId": r.cafe_id, "articleId": r.article_id, "requestFrom": "A"},
            referer=endpoints.article_page(r.cafe_id, r.article_id),
        )
