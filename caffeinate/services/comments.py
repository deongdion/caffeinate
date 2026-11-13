"""댓글/대댓글: 조회(페이지 / 전체 / 비동기 반복자), 작성, 삭제"""
import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ..core import endpoints
from ..core.errors import NaverAPIError, ParseError
from ..core.session import ensure_success
from ..models import ArticleRef, Comment, CommentPage, UploadedImage
from ..utils.parsing import dig
from .base import BaseService, ImageLike, gw_params, image_source


def comment_id_from(resp: Any) -> int:
    """CommentPost/Reply 응답 {"commentId": ..., "refCommentId": ...} -> commentId

    [실측 2026-11-13] 응답은 message.result 중첩 없이 플랫이다.
    """
    if isinstance(resp, dict):
        v = resp.get("commentId")
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        if isinstance(v, str) and v.isascii() and v.isdigit():
            return int(v)
    raise ParseError(f"댓글 응답에서 commentId 를 찾지 못했습니다: {str(resp)[:200]}")


ImageInput = ImageLike  # 0.3 호환 이름


def image_fields(img: UploadedImage | None) -> dict[str, Any]:
    """사진 댓글 폼 필드 - stickerId 와 refCommentId 사이, 순서까지 캡처값 그대로 [실측 2026-11-13 Camoufox UI 캡처]

    imagePath 는 upphoto 응답 path(파일명 없는 해시 경로) 끝에 "/" 를 붙인 값이다
    (예: /MjAy.../MDAx...PNG/). imageFileName 은 응답 fileName.
    """
    if img is None:
        return {}
    path = img.path or img.url.rsplit("/", 1)[0]
    return {
        "imagePath": path if path.endswith("/") else f"{path}/",
        "imageFileName": img.file_name,
        "imageWidth": img.width,
        "imageHeight": img.height,
    }


def comment_fields(
    text: str, sticker_id: str = "", image: UploadedImage | None = None, ref_comment_id: int | None = None
) -> dict[str, Any]:
    """CommentPost/CommentReply 폼 앞부분 (뒤에 cafeId, articleId, requestFrom 이 붙는다)

    [실측 2026-11-13 Camoufox UI 캡처] 순서: content, stickerId, [imagePath, imageFileName, imageWidth, imageHeight],
    [refCommentId], cafeId, articleId, requestFrom=A
    """
    fields: dict[str, Any] = {"content": text, "stickerId": sticker_id, **image_fields(image)}
    if ref_comment_id is not None:
        fields["refCommentId"] = ref_comment_id
    return fields


class CommentService(BaseService):
    """댓글 기능 (`cafe.comments`). ref 인자는 게시글 URL 문자열 또는 ArticleRef."""

    async def page(self, ref: ArticleRef | str, *, page: int = 1, size: int = 100) -> CommentPage:
        """댓글 한 페이지 -> CommentPage [실측: result.comments.items, hasNext/hasPrev]

        [실측 2026-11-13] 페이지 번호는 경로 /comments/pages/{page} 로 보내야 적용된다.
        예전처럼 쿼리 ?page= 로 보내면 무시되고 항상 첫 페이지가 와서, 댓글 100개 초과 글은
        all() 이 첫 100개만 돌려주고 끝났다 (341개 글로 확인). size 는 쿼리로 적용된다.
        """
        r = await self._client.articles.resolve(ref)
        data = await self.session.get_json(
            endpoints.gw_comments(r.cafe_id, r.article_id, max(1, page)),
            # [실측 2026-11-13] 프론트: comments/pages/{n}?requestFrom=A&orderBy=asc
            params=gw_params(r.cafe_id, requestFrom="A", orderBy="asc", size=size),
            headers=dict(endpoints.PRODUCT_HEADERS),  # [실측 2026-11-13] 프론트는 apis/gw XHR 전부에 붙인다
            referer=endpoints.article_frame_page(r.cafe_id, r.article_id, r.menu_id),
        )
        return CommentPage.from_api(dig(data, "result", default={}))

    async def all(self, ref: ArticleRef | str, *, max_pages: int = 20, size: int = 100) -> list[Comment]:
        """모든 댓글 -> list[Comment] (평탄화 목록, 페이지 순회). 트리는 build_tree(comments)

        max_pages * size 개를 넘는 댓글은 잘린다 (기본 2000개). 순회 규칙은 iter() 와 같다.

            tree = build_tree(await cafe.comments.all(ref))
        """
        return [c async for c in self.iter(ref, size=size, max_pages=max_pages)]

    async def iter(
        self, ref: ArticleRef | str, *, size: int = 100, limit: int | None = None, max_pages: int | None = None
    ) -> AsyncIterator[Comment]:
        """댓글을 페이지를 넘기며 하나씩 -> AsyncIterator[Comment] (등록순, 대댓글 포함 평탄)

        - size: 요청 1회당 댓글 수,  limit: 최대 개수,  max_pages: 최대 요청 페이지 수 (None = 제한 없음)

        hasNext 가 없거나, 새 댓글이 없는 페이지가 오면 멈춘다 (마지막을 넘는 번호에 서버가 마지막 페이지를
        다시 주는 경우 [실측 2026-11-13] 의 무한 반복 방지). 같은 comment_id 는 한 번만 내보낸다.

            async for c in cafe.comments.iter(ref):
                print(c.writer.nick, c.content)
        """
        if limit is not None and limit <= 0:
            return
        r = await self._client.articles.resolve(ref)
        seen: set[int] = set()
        n = 0
        count = 0
        while max_pages is None or n < max_pages:
            n += 1
            p = await self.page(r, page=n, size=size)
            new = [c for c in p.items if c.comment_id not in seen]
            for c in new:
                seen.add(c.comment_id)
                yield c
                count += 1
                if limit is not None and count >= limit:
                    return
            if not p.has_next or not new:
                return

    async def add(
        self,
        ref: ArticleRef | str,
        text: str,
        *,
        sticker_id: str = "",
        image: ImageLike | None = None,
        filename: str | None = None,
    ) -> int:
        """댓글 작성 -> 새 댓글의 comment_id (로그인 필요)

        - text: 내용 (스티커만 보낼 때는 "")
        - sticker_id: 스티커 "{stickerCode}-{w}-{h}" - gfmarket proxyStickerList 항목 (예: motion3d_02-5-185-160)
        - image: 사진 댓글 (bytes / 파일 경로 / (bytes, 파일명) / 이미 올린 UploadedImage). 자동 업로드한다
        - filename: bytes 일 때 파일명 (기본 image.png)

        [실측 2026-11-13: E2E 성공] cafe-mobile/CommentPost.json (form). 응답은 플랫 {"commentId", "refCommentId"}.
        사진은 브라우저처럼 PhotoInfraSessionKey -> upphoto 업로드 후 image* 필드를 넣는다 [실측 2026-11-13 Camoufox UI 캡처].
        연속 등록 제한(2001)은 Settings.comment_retry_* 만큼 기다렸다 재시도하고, 그래도 막히면 RateLimitedError.

            cid = await cafe.comments.add(ref, "사진 댓글", image="a.png")
        """
        self._require_login()
        r = await self._client.articles.resolve(ref)
        img = await self._image(r, image, filename)
        resp = await self._post(endpoints.COMMENT_POST, r, comment_fields(text, sticker_id, img))
        return comment_id_from(resp)

    async def reply(
        self,
        ref: ArticleRef | str,
        comment_id: int,
        text: str,
        *,
        sticker_id: str = "",
        image: ImageLike | None = None,
        filename: str | None = None,
    ) -> int:
        """대댓글 작성 -> 새 댓글의 comment_id (comment_id = 부모 댓글, 나머지 인자는 add() 와 같다)

        [실측 2026-11-12: E2E 성공] cafe-mobile/CommentReply.json (refCommentId=부모 댓글).
        image 는 add() 와 같다 [실측 2026-11-13 Camoufox UI 캡처: 사진 대댓글].
        """
        self._require_login()
        r = await self._client.articles.resolve(ref)
        img = await self._image(r, image, filename)
        resp = await self._post(endpoints.COMMENT_REPLY, r, comment_fields(text, sticker_id, img, comment_id))
        return comment_id_from(resp)

    async def _image(self, r: ArticleRef, image: ImageLike | None, filename: str | None) -> UploadedImage | None:
        """댓글 사진 입력 -> UploadedImage (필요하면 업로드)"""
        if image is None or isinstance(image, UploadedImage):
            return image
        data, name = image_source(image, filename)
        return await self._client.photos.upload_comment_image(r.cafe_id, r.article_id, data, name, menu_id=r.menu_id)

    async def delete(self, ref: ArticleRef | str, comment_id: int) -> None:
        """댓글 삭제 -> None. 서버가 성공을 알리지 않으면 NaverAPIError (로그인 필요)

        [실측 2026-11-13: E2E 성공] cafe-mobile/CommentDelete.json,
        폼: cafeId, menuId, articleId, commentId, requestFrom=A (menu_id 를 모르면 게시글 상세로 확인).
        삭제된 댓글은 gw 목록에서 완전히 사라진다 (톰스톤 없음).
        """
        self._require_login()
        r = await self._client.articles.resolve(ref)
        menu_id = r.menu_id or (await self._client.articles.get(r)).ref.menu_id or 0
        data = await self.session.post_form(
            endpoints.COMMENT_DELETE,
            # [실측 2026-11-13 UI 캡처] 프론트 폼 순서: cafeId, menuId, articleId, commentId, requestFrom
            data={
                "cafeId": r.cafe_id,
                "menuId": menu_id,
                "articleId": r.article_id,
                "commentId": comment_id,
                "requestFrom": "A",
            },
            headers=dict(endpoints.PRODUCT_HEADERS),  # [실측 2026-11-13 UI 캡처] content-type 바로 뒤
            referer=endpoints.article_frame_page(r.cafe_id, r.article_id, r.menu_id),
        )
        ensure_success(data, "댓글 삭제", endpoints.COMMENT_DELETE)  # [실측 2026-11-13] 성공: {"msg": "Success"}

    async def best(self, ref: ArticleRef | str) -> list[Comment]:
        """베스트 댓글 -> list[Comment] (베스트 미선정이면 [])

        [실측 2026-11-13 사람 세션 캡처] 게시글 로드 시 브라우저가 gw/v1 best-comments 를 호출한다.
        응답은 result{cafeId, articleId, comments[], commentCount} (베스트 미선정 글은 빈 목록, 비로그인도 200).
        항목 스키마는 베스트가 있는 글로 아직 확인하지 못해 gw 댓글 항목과 같다고 보고 파싱한다 [추정].
        """
        r = await self._client.articles.resolve(ref)
        data = await self.session.get_json(
            endpoints.best_comments(r.cafe_id, r.article_id),
            headers=dict(endpoints.PRODUCT_HEADERS),  # [실측 2026-11-13] 프론트는 apis/gw XHR 전부에 붙인다
            referer=endpoints.article_frame_page(r.cafe_id, r.article_id, r.menu_id),
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
                    headers=dict(endpoints.PRODUCT_HEADERS),  # [실측 2026-11-13 UI 캡처] content-type 바로 뒤
                    referer=endpoints.article_frame_page(r.cafe_id, r.article_id, r.menu_id),
                )
            except NaverAPIError as e:  # 2001 은 RateLimitedError (NaverAPIError 하위)
                if str(e.code) != "2001" or attempt >= attempts - 1:
                    raise
                delay = delays[attempt] if attempt < len(delays) else delays[-1]
                await asyncio.sleep(delay)
