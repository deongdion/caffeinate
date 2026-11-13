"""게시판: 메뉴 목록, 게시글 목록, 공지 목록"""
from ..core import endpoints
from ..enums import SortBy, ViewType
from ..models import ArticlePage, ArticleSummary, Board, PageInfo
from ..utils.parsing import as_list, dig
from .base import BaseService


class BoardService(BaseService):
    async def all(self, cafe_id: int, *, include_separators: bool = False) -> list[Board]:
        """게시판(메뉴) 목록 - cafe-cafemain-api (x-cafe-product: pc 필수)

        기본은 글이 없는 구조용 메뉴(폴더 F / 구분선 S)를 뺀다 [실측 2026-11-13: 폴더 메뉴의 글 목록은 빈 목록].
        include_separators=True 면 모든 메뉴를 그대로 돌려준다.
        """
        data = await self.session.get_json(
            endpoints.cafe_menus(cafe_id),
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cafe_id),
        )
        boards = [Board.from_api(m) for m in as_list(dig(data, "result", "menus"))]
        return boards if include_separators else [b for b in boards if not b.menu_type.is_container]

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
        """특정 게시판의 게시글 목록 (menu_id=0 이면 전체글보기)

        다음 페이지 여부는 page_info.has_next 로 판단한다. 범위를 넘는 page 를 주면 서버가 첫 페이지를
        다시 돌려주므로 [실측 2026-11-13], 페이지 번호만 올리며 돌면 같은 글이 반복된다.
        """
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
            page_info=PageInfo.from_api(dig(data, "result", "pageInfo"), page=page),
        )

    async def notices(self, cafe_id: int, menu_id: int) -> list[ArticleSummary]:
        """특정 게시판의 공지글 목록"""
        data = await self.session.get_json(
            endpoints.notice_list(cafe_id, menu_id),
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cafe_id, menu_id),
        )
        return [ArticleSummary.from_api(x) for x in as_list(dig(data, "result", "articleList"))]
