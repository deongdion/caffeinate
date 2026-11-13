"""게시판: 메뉴 목록, 게시글 목록(페이지 / 비동기 반복자), 공지 목록"""
from collections.abc import AsyncIterator

from ..core import endpoints
from ..enums import SortBy, ViewType
from ..models import ArticlePage, ArticleSummary, Board, PageInfo
from ..utils.parsing import as_list, dig
from .base import BaseService, CafeLike


class BoardService(BaseService):
    """게시판 기능 (`cafe.boards`). cafe_id 인자는 숫자 ID / slug / 카페 URL 모두 받는다."""

    async def all(self, cafe_id: CafeLike, *, include_separators: bool = False) -> list[Board]:
        """게시판(메뉴) 목록 -> list[Board] - cafe-cafemain-api (x-cafe-product: pc 필수)

        - cafe_id: 카페 ID / slug / 카페 URL (CafeLike)
        - include_separators: True 면 글이 없는 구조용 메뉴(폴더 F / 구분선 S)도 포함
          [실측 2026-11-13: 폴더 메뉴의 글 목록은 빈 목록이라 기본은 뺀다]

            boards = await cafe.boards.all("remonterace")
        """
        cid = await self._cafe_id(cafe_id)
        data = await self.session.get_json(
            endpoints.cafe_menus(cid),
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cid),
        )
        boards = [Board.from_api(m) for m in as_list(dig(data, "result", "menus"))]
        return boards if include_separators else [b for b in boards if not b.menu_type.is_container]

    async def articles(
        self,
        cafe_id: CafeLike,
        menu_id: int,
        *,
        page: int = 1,
        page_size: int = 15,
        sort_by: SortBy = SortBy.TIME,
        view_type: ViewType = ViewType.LIST,
    ) -> ArticlePage:
        """게시판 글 목록 한 페이지 -> ArticlePage (menu_id=0 이면 전체글보기)

        - page / page_size: 페이지 번호(1부터) / 페이지 크기
        - sort_by: SortBy.TIME(최신순) / SortBy.LIKE(좋아요순) - 서버가 실제로 적용하는 두 가지 [실측]

        다음 페이지 여부는 page_info.has_next 로 판단한다. 범위를 넘는 page 를 주면 서버가 첫 페이지를
        다시 돌려주므로 [실측 2026-11-13], 여러 페이지를 돌 때는 iter_articles() 를 쓰는 편이 안전하다.

            page = await cafe.boards.articles("remonterace", 2, page=1)
        """
        cid = await self._cafe_id(cafe_id)
        data = await self.session.get_json(
            endpoints.article_list(cid, menu_id),
            params={
                "page": page,
                "pageSize": page_size,
                "sortBy": sort_by.value,
                "viewType": view_type.value,
            },
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cid, menu_id),
        )
        return ArticlePage(
            items=[ArticleSummary.from_api(x) for x in as_list(dig(data, "result", "articleList"))],
            page=page,
            page_info=PageInfo.from_api(dig(data, "result", "pageInfo"), page=page),
        )

    async def iter_articles(
        self,
        cafe_id: CafeLike,
        menu_id: int,
        *,
        limit: int | None = None,
        page_size: int = 15,
        sort_by: SortBy = SortBy.TIME,
        view_type: ViewType = ViewType.LIST,
        start_page: int = 1,
        max_pages: int | None = None,
    ) -> AsyncIterator[ArticleSummary]:
        """게시판 글을 페이지를 넘기며 하나씩 -> AsyncIterator[ArticleSummary]

        - limit: 최대 개수 (None 이면 끝까지)
        - page_size: 요청 1회당 글 수 (클수록 요청 수가 준다)
        - max_pages: 최대 요청 페이지 수 (None 이면 제한 없음)

        PageInfo 가 다음 페이지 없음이라고 하거나, 새 글이 하나도 없는 페이지가 오면 멈춘다
        (범위를 넘는 페이지에 서버가 1페이지를 다시 주는 경우 [실측 2026-11-13] 의 무한 반복 방지).
        이미 받은 글 ID 는 다시 내보내지 않는다 (페이지 사이에 새 글이 올라와 밀린 글 포함).

            async for a in cafe.boards.iter_articles("remonterace", 2, limit=40):
                print(a.article_id, a.subject)
        """
        if limit is not None and limit <= 0:
            return
        cid = await self._cafe_id(cafe_id)
        seen: set[int] = set()
        count = 0
        page = max(1, start_page)
        fetched = 0
        while max_pages is None or fetched < max_pages:
            result = await self.articles(
                cid, menu_id, page=page, page_size=page_size, sort_by=sort_by, view_type=view_type
            )
            fetched += 1
            new = [a for a in result.items if a.article_id not in seen]
            for a in new:
                seen.add(a.article_id)
                yield a
                count += 1
                if limit is not None and count >= limit:
                    return
            if not new or not result.page_info.has_next:
                return
            page += 1

    async def notices(self, cafe_id: CafeLike, menu_id: int) -> list[ArticleSummary]:
        """게시판의 공지글 목록 -> list[ArticleSummary]

            notices = await cafe.boards.notices("remonterace", 2)
        """
        cid = await self._cafe_id(cafe_id)
        data = await self.session.get_json(
            endpoints.notice_list(cid, menu_id),
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.cafe_page(cid, menu_id),
        )
        return [ArticleSummary.from_api(x) for x in as_list(dig(data, "result", "articleList"))]
