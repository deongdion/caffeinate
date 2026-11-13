"""게시글: 식별자 해석, 상세 조회, 글쓰기/수정/삭제

글쓰기 [실측 2026-11-12]: apis.cafe.naver.com/editor/v2.0 스택, 본문은 SmartEditor contentJson.
images 에는 UploadedImage / bytes / 파일 경로 / (bytes, 파일명) 을 섞어 넘길 수 있다 (photos.upload_many 로 자동 업로드).
삭제 [실측 2026-11-13]: cafe-mobile/ArticleDelete.json (브라우저 캡처).
"""
from collections.abc import Sequence
from typing import Any

from ..core import endpoints
from ..core.errors import ParseError
from ..core.session import ensure_success
from ..models import Article, ArticleRef, UploadedImage
from ..utils.editor import build_content_json
from ..utils.parsing import as_int, dig, parse_cafe_url
from .base import BaseService, CafeLike, ImageLike, gw_params


class ArticleService(BaseService):
    """게시글 기능 (`cafe.articles`). ref 인자는 게시글 URL 문자열 또는 ArticleRef."""

    async def resolve(self, value: str | ArticleRef) -> ArticleRef:
        """게시글 URL -> ArticleRef (slug 만 있는 URL 이면 cafeId 를 조회해서 채움, 캐시 사용)

        f-e/cafes/{id}/articles/{id}, cafe.naver.com/{slug}/{articleId}, ArticleRead.nhn?clubid=.. 등을 받는다.

            ref = await cafe.articles.resolve("https://cafe.naver.com/deongdion/197")
        """
        if isinstance(value, ArticleRef):
            return value
        p = parse_cafe_url(str(value))
        article_id, cafe_id, slug = p["article_id"], p["cafe_id"], p["cafe_url"]
        menu_id = p["menu_id"]
        if not isinstance(article_id, int):
            raise ParseError(f"게시글 URL을 해석할 수 없습니다: {value}")
        if not isinstance(cafe_id, int):
            if not isinstance(slug, str):
                raise ParseError(f"카페를 알 수 없는 게시글 URL 입니다: {value}")
            cafe_id = await self._client.cafes.id_from_slug(slug)
        return ArticleRef(
            cafe_id=cafe_id,
            article_id=article_id,
            menu_id=menu_id if isinstance(menu_id, int) else None,
            cafe_url=slug if isinstance(slug, str) else None,
        )

    async def get_raw(self, cafe_id: CafeLike, article_id: int, menu_id: int | None = None) -> dict[str, Any]:
        """gw v4 상세 원본 result (dict: 글 + 첫 댓글 페이지 + 내 권한 + 카페 정보). 보통은 get() 을 쓴다.

        [실측 2026-11-13 Camoufox UI 캡처] 프론트 쿼리: `?query=&menuId={m}&useCafeId=true&requestFrom=A`.
        게시판 번호를 모르면 menuId 를 뺀다 (서버는 없어도 응답한다).
        """
        cafe_id = await self._cafe_id(cafe_id)
        params: dict[str, str | int] = {"query": ""}
        if menu_id:
            params["menuId"] = menu_id
        params.update(gw_params(cafe_id, requestFrom="A"))
        data = await self.session.get_json(
            endpoints.gw_article(cafe_id, article_id),
            params=params,
            headers=dict(endpoints.PRODUCT_HEADERS),  # [실측 2026-11-13] 프론트는 apis/gw XHR 전부에 붙인다
            referer=endpoints.article_frame_page(cafe_id, article_id, menu_id),  # [실측 2026-11-13] iframe URL
        )
        return dig(data, "result", default={})

    async def get(self, ref: ArticleRef | str) -> Article:
        """게시글 상세 -> Article [실측]. 없거나 삭제된 글이면 ArticleNotFoundError

            article = await cafe.articles.get("https://cafe.naver.com/f-e/cafes/30857348/articles/368535")
            print(article.subject, article.content_text)
        """
        r = await self.resolve(ref)
        return Article.from_api(await self.get_raw(r.cafe_id, r.article_id, r.menu_id))

    async def write(
        self,
        cafe_id: CafeLike,
        menu_id: int,
        title: str,
        body: str,
        *,
        images: Sequence[ImageLike] | None = None,
    ) -> ArticleRef:
        """게시글 작성 -> 새 글의 ArticleRef [실측 2026-11-12: E2E 성공] (로그인 + 카페 멤버)

        - cafe_id: 카페 ID / slug / 카페 URL,  menu_id: 게시판 번호
        - body: 본문 텍스트 (줄바꿈/빈 줄 유지)
        - images: UploadedImage / bytes / 파일 경로 / (bytes, 파일명) - 올리지 않은 것은 자동 업로드,
          본문 뒤에 입력 순서대로 붙는다 (첫 장이 대표 이미지)

            ref = await cafe.articles.write("deongdion", 1, "제목", "본문", images=["a.png", (png, "b.png")])
        """
        self._require_login()
        cafe_id = await self._cafe_id(cafe_id)
        uploaded = await self._images(cafe_id, menu_id, images)
        data = await self.session.post_json(
            endpoints.editor_write_article(cafe_id, menu_id),
            json_body=_article_payload(cafe_id, menu_id, title, build_content_json(body, uploaded)),
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.write_page(cafe_id, menu_id),
        )
        article_id = as_int(dig(data, "result", "articleId"))
        if not article_id:
            raise ParseError(f"글쓰기 응답에 articleId 가 없습니다: {str(data)[:300]}")
        return ArticleRef(cafe_id=cafe_id, article_id=article_id, menu_id=menu_id)

    async def update(
        self,
        ref: ArticleRef | str,
        menu_id: int,
        title: str,
        body: str,
        *,
        images: Sequence[ImageLike] | None = None,
    ) -> ArticleRef:
        """게시글 수정 -> ArticleRef [실측 2026-11-12: 성공] 제목/본문/이미지 전체를 교체한다

        작성과 같은 페이로드 + headId. images 는 write() 와 같다 (기존 이미지를 유지하려면 다시 넘겨야 함).
        수정된 내용이 필요하면 `await cafe.articles.get(ref)`.

            await cafe.articles.update(ref, 1, "새 제목", "새 본문")
        """
        self._require_login()
        r = await self.resolve(ref)
        uploaded = await self._images(r.cafe_id, menu_id, images)
        data = await self.session.post_json(
            endpoints.editor_update_article(r.cafe_id, r.article_id),
            json_body=_article_payload(
                r.cafe_id, menu_id, title, build_content_json(body, uploaded), with_head_id=True
            ),
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.article_page(r.cafe_id, r.article_id, menu_id),
        )
        article_id = as_int(dig(data, "result", "articleId")) or r.article_id
        return ArticleRef(cafe_id=r.cafe_id, article_id=article_id, menu_id=menu_id, cafe_url=r.cafe_url)

    async def _images(
        self, cafe_id: int, menu_id: int, images: Sequence[ImageLike] | None
    ) -> list[UploadedImage] | None:
        """images 입력 -> UploadedImage 목록 (필요한 것만 업로드, 순서 유지)"""
        if not images:
            return None
        if isinstance(images, str | bytes):  # images="a.png" 실수 방지 (글자/바이트 단위로 쪼개지 않게)
            images = [images]
        return await self._client.photos.upload_many(cafe_id, menu_id, images)

    async def delete(self, ref: ArticleRef | str) -> None:
        """게시글 삭제 -> None [실측 2026-11-13]. 서버가 성공을 알리지 않으면 NaverAPIError

            await cafe.articles.delete(ref)

        브라우저 흐름: 글 화면 '삭제'(BaseButton--skinGray) -> JS confirm ->
        cafe-mobile/ArticleDelete.json (form-urlencoded, HTTP 200).
        본문은 캡처되지 않아 댓글과 같은 cafe-mobile 폼 규약으로 구성했고, 서버 Success 로 검증했다.
        """
        self._require_login()
        r = await self.resolve(ref)
        data = await self.session.post_form(
            endpoints.ARTICLE_DELETE,
            data={"cafeId": r.cafe_id, "articleId": r.article_id, "requestFrom": "A"},
            # [실측 2026-11-13 Aside 캡처] 폼 cafeId, articleId, requestFrom=A (menuId 없음) + X-Cafe-Product
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.article_frame_page(r.cafe_id, r.article_id, r.menu_id),
        )
        # [실측 2026-11-13] 성공: {"message": {"status": "200", ..., "result": {"msg": "Success"}}}
        ensure_success(data, "게시글 삭제", endpoints.ARTICLE_DELETE)


def _article_payload(
    cafe_id: int, menu_id: int, title: str, content_json: str, *, with_head_id: bool = False
) -> dict[str, Any]:
    """등록/수정 페이로드 (2026-11-12 브라우저 캡처값). 생성은 headId 없음, 수정은 headId 포함"""
    article: dict[str, Any] = {
        "cafeId": str(cafe_id),  # [실측 2026-11-13 UI 캡처] 프론트는 문자열
        "contentJson": content_json,
        "from": "pc",
        "menuId": menu_id,
        "subject": title,
        "tagList": [],
        "editorVersion": 4,
        "parentId": 0,
        "open": False,
        "naverOpen": True,
        "externalOpen": True,
        "enableComment": True,
        "enableScrap": True,
        "enableCopy": True,
        "useAutoSource": False,
        "cclTypes": [],
        "useCcl": False,
    }
    if with_head_id:
        article["headId"] = 0
    return {"article": article}
