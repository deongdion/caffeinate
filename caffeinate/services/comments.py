"""댓글/대댓글: 조회, 작성, 삭제"""
import asyncio
from typing import Any

from ..core import endpoints
from ..core.errors import NaverAPIError, ParseError
from ..models import ArticleRef, Comment, CommentPage
from ..utils.parsing import dig
from .base import BaseService, gw_params


def comment_id_from(resp: Any) -> int:
    """CommentPost/Reply 응답 {"commentId": ..., "refCommentId": ...} -> commentId

    [실측 2026-11-13] 응답은 message.result 중첩 없이 플랫이다.
    """
    if isinstance(resp, dict):
        v = resp.get("commentId")
        if isinstance(v, int):
            return v
    raise ParseError(f"댓글 응답에서 commentId 를 찾지 못했습니다: {str(resp)[:200]}")


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

    async def add(self, ref: ArticleRef | str, text: str, *, sticker_id: str = "") -> int:
        """댓글 작성 -> comment_id

        [실측 2026-11-13: E2E 성공] cafe-mobile/CommentPost.json (form).
        응답은 플랫 {"commentId": ..., "refCommentId": ...} 이다.
        """
        r = await self._client.articles.resolve(ref)
        resp = await self._post(endpoints.COMMENT_POST, r, {"content": text, "stickerId": sticker_id})
        return comment_id_from(resp)

    async def reply(self, ref: ArticleRef | str, comment_id: int, text: str, *, sticker_id: str = "") -> int:
        """대댓글 작성 -> comment_id

        [실측 2026-11-12: E2E 성공] cafe-mobile/CommentReply.json (refCommentId=부모 댓글).
        """
        r = await self._client.articles.resolve(ref)
        resp = await self._post(
            endpoints.COMMENT_REPLY, r, {"content": text, "stickerId": sticker_id, "refCommentId": comment_id}
        )
        return comment_id_from(resp)

    async def delete(self, ref: ArticleRef | str, comment_id: int) -> Any:
        """댓글 삭제 -> 응답 {"msg": "Success"}

        [실측 2026-11-13: E2E 성공] cafe-mobile/CommentDelete.json,
        폼: commentId + cafeId/articleId/requestFrom=A (Post/Reply 동일 계열).
        삭제된 댓글은 gw 목록에서 완전히 사라진다 (톰스톤 없음).
        """
        r = await self._client.articles.resolve(ref)
        self._require_login()
        return await self.session.post_form(
            endpoints.COMMENT_DELETE,
            data={"commentId": comment_id, "cafeId": r.cafe_id, "articleId": r.article_id, "requestFrom": "A"},
            referer=endpoints.article_page(r.cafe_id, r.article_id),
        )

    async def best(self, ref: ArticleRef | str) -> list[Comment]:
        """베스트 댓글

        [실측 2026-11-13 사람 세션 캡처] 게시글 로드 시 브라우저가 gw/v1 best-comments 를 호출한다.
        응답 스키마는 미검증이라 result 아래 첫 목록을 Comment 로 파싱한다.
        """
        r = await self._client.articles.resolve(ref)
        data = await self.session.get_json(
            endpoints.best_comments(r.cafe_id, r.article_id),
            referer=endpoints.article_page(r.cafe_id, r.article_id),
        )
        result = dig(data, "result", default={})
        items: list[Any] = []
        if isinstance(result, dict):
            for key in ("bestComments", "bestCommentList", "comments", "items", "list"):
                v = result.get(key)
                if isinstance(v, list) and v:
                    items = v
                    break
        return [Comment.from_api(x) for x in items if isinstance(x, dict)]

    async def _post(self, url: str, r: ArticleRef, fields: dict[str, Any]) -> Any:
        """댓글 등록 POST. 2001("많은 댓글을 연달아 등록할 수 없어요", HTTP 403) 만 재시도한다.

        [실측 2026-11-13] 연속 등록 시 두 번째부터 2001 이 오고, 약 12초 뒤 같은 요청을 다시
        보내면 성공한다. 다른 에러 코드는 재시도 없이 그대로 올린다.
        횟수/대기는 Settings.comment_retry_max / comment_retry_delays.
        """
        self._require_login()  # 비로그인 0004 도 서버가 돌려주지만, 쿠키가 아예 없으면 미리 막는다
        s = self.session.settings
        attempts = 1 + max(0, s.comment_retry_max)
        delays = s.comment_retry_delays or (12.0,)
        for attempt in range(attempts):
            try:
                return await self.session.post_form(
                    url,
                    data={**fields, "cafeId": r.cafe_id, "articleId": r.article_id, "requestFrom": "A"},
                    referer=endpoints.article_page(r.cafe_id, r.article_id),
                )
            except NaverAPIError as e:
                if str(e.code) != "2001" or attempt >= attempts - 1:
                    raise
                delay = delays[attempt] if attempt < len(delays) else delays[-1]
                await asyncio.sleep(delay)
