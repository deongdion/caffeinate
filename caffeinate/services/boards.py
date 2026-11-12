"""게시판: 메뉴 목록, 게시글 목록, 공지 목록"""
from ..core import endpoints
from ..enums import SortBy, ViewType
from ..models import ArticlePage, ArticleSummary, Board, PageInfo
from ..utils.parsing import as_list, dig
from .base import BaseService


class BoardService(BaseService):
    async def all(self, cafe_id: int, *, include_separators: bool = False) -> list[Board]:
        """게시판(메뉴) 목록 - cafe-cafemain-api (x-cafe-product: pc 필수)"""
        data = await self.session.get_json(
            endpoints.cafe_menus(cafe_id),
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cafe_id),
        )
        boards = [Board.from_api(m) for m in as_list(dig(data, "result", "menus"))]
        return boards if include_separators else [b for b in boards if not b.is_separator]

    async def articles(
        self,
        cafe_id: int,
        menu_id: int,
        *,
        page: int = 1,
        page_size: int = 15,
        sort_by: SortBy = SortBy.TIME,
        view_type: ViewType = ViewType.LIST,
    ) -> ArticlePage:
        """특정 게시판의 게시글 목록"""
        data = await self.session.get_json(
            endpoints.article_list(cafe_id, menu_id),
            params={
                "page": page,
                "pageSize": page_size,
                "sortBy": sort_by.value,
                "viewType": view_type.value,
            },
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cafe_id, menu_id),
        )
        return ArticlePage(
            items=[ArticleSummary.from_api(x) for x in as_list(dig(data, "result", "articleList"))],
            page=page,
            page_info=PageInfo.from_api(dig(data, "result", "pageInfo")),
        )

    async def notices(self, cafe_id: int, menu_id: int) -> list[ArticleSummary]:
        """특정 게시판의 공지글 목록"""
        data = await self.session.get_json(
            endpoints.notice_list(cafe_id, menu_id),
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cafe_id, menu_id),
        )
        return [ArticleSummary.from_api(x) for x in as_list(dig(data, "result", "articleList"))]
