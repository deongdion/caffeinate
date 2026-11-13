"""게시글: 식별자 해석, 상세 조회, 글쓰기/수정/삭제

글쓰기 [실측 2026-11-12]: apis.cafe.naver.com/editor/v2.0 스택, 본문은 SmartEditor contentJson.
이미지는 photos.upload() 결과(UploadedImage)를 images 로 넘긴다.
삭제 [실측 2026-11-13]: cafe-mobile/ArticleDelete.json (브라우저 캡처).
"""
from typing import Any

from ..core import endpoints
from ..core.errors import ParseError
from ..models import Article, ArticleRef, UploadedImage
from ..utils.editor import build_content_json
from ..utils.parsing import as_int, dig, parse_cafe_url
from .base import BaseService, gw_params


class ArticleService(BaseService):
    async def resolve(self, value: str | ArticleRef) -> ArticleRef:
        """게시글 URL -> ArticleRef (slug 만 있는 URL 이면 cafeId 를 조회해서 채움)"""
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

    async def get_raw(self, cafe_id: int, article_id: int) -> dict[str, Any]:
        """gw v4 상세 원본 result (글 + 첫 댓글 페이지 + 내 권한 + 카페 정보)"""
        data = await self.session.get_json(
            endpoints.gw_article(cafe_id, article_id),
            params=gw_params(cafe_id, requestFrom="A"),
            headers=dict(endpoints.PRODUCT_HEADERS),  # [실측 2026-11-13] 프론트는 apis/gw XHR 전부에 붙인다
            referer=endpoints.article_frame_page(cafe_id, article_id),  # [실측 2026-11-13] iframe URL
        )
        return dig(data, "result", default={})

    async def get(self, ref: ArticleRef | str) -> Article:
        """게시글 상세 [실측]"""
        r = await self.resolve(ref)
        return Article.from_api(await self.get_raw(r.cafe_id, r.article_id))

    async def write(
        self,
        cafe_id: int,
        menu_id: int,
        title: str,
        body: str,
        *,
        images: list[UploadedImage] | None = None,
    ) -> ArticleRef:
        """게시글 작성 [실측 2026-11-12: E2E 성공]. 이미지는 본문 뒤에 순서대로 붙는다."""
        self._require_login()
        data = await self.session.post_json(
            endpoints.editor_write_article(cafe_id, menu_id),
            json_body=_article_payload(cafe_id, menu_id, title, build_content_json(body, images)),
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
        images: list[UploadedImage] | None = None,
    ) -> Any:
        """게시글 수정 [실측 2026-11-12: 성공] 작성과 같은 페이로드 + headId, 본문 전체를 교체한다"""
        self._require_login()
        r = await self.resolve(ref)
        return await self.session.post_json(
            endpoints.editor_update_article(r.cafe_id, r.article_id),
            json_body=_article_payload(
                r.cafe_id, menu_id, title, build_content_json(body, images), with_head_id=True
            ),
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.article_page(r.cafe_id, r.article_id, menu_id),
        )

    async def delete(self, ref: ArticleRef | str) -> Any:
        """게시글 삭제 [실측 2026-11-13]

        브라우저 흐름: 글 화면 '삭제'(BaseButton--skinGray) -> JS confirm ->
        cafe-mobile/ArticleDelete.json (form-urlencoded, HTTP 200).
        본문은 캡처되지 않아 댓글과 같은 cafe-mobile 폼 규약으로 구성했고, 서버 Success 로 검증했다.
        """
        self._require_login()
        r = await self.resolve(ref)
        return await self.session.post_form(
            endpoints.ARTICLE_DELETE,
            data={"cafeId": r.cafe_id, "articleId": r.article_id, "requestFrom": "A"},
            # [추정] 댓글 계열(cafe-mobile *.json)과 같은 헤더/Referer - ArticleDelete 는 UI 캡처하지 않음
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.article_frame_page(r.cafe_id, r.article_id),
        )


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
