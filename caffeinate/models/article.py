"""게시글 모델"""
import html
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from ..enums import ArticleListItemType
from ..utils.html import html_to_text
from ..utils.parsing import JSON, as_count, as_dict, as_int, ms_to_datetime, pick
from .board import Board
from .cafe import Cafe
from .member import Writer


@dataclass(frozen=True, slots=True, kw_only=True)
class ArticleRef:
    """게시글 식별자 (URL 파싱 결과)"""

    cafe_id: int
    article_id: int
    menu_id: int | None = None
    cafe_url: str | None = None   # slug (like 서비스 cid 에 필요)

    @property
    def link(self) -> str:
        return f"https://cafe.naver.com/f-e/cafes/{self.cafe_id}/articles/{self.article_id}"


@dataclass(slots=True, kw_only=True)
class PageInfo:
    """boardlist pageInfo

    [실측 2026-11-13] 서버 값은 "페이지 이동 막대(10페이지 단위)" 기준이다.
    lastNavigationPageNumber = 현재 10페이지 묶음의 마지막 번호 (11페이지를 요청하면 20),
    visibleNextButton = 다음 10페이지 묶음이 있는지. 그래서 has_next 는 요청한 페이지 번호를 함께
    넘겨야(page=) "다음 페이지가 있는지" 가 된다 (5페이지짜리 게시판의 3페이지: 묶음 다음은 없지만 4페이지는 있음).
    범위를 넘는 페이지 번호를 요청하면 서버는 오류 없이 첫 페이지를 돌려준다 -> has_next 로 멈출 것.
    """

    last_page: int = 0                 # 현재 10페이지 묶음의 마지막 페이지 번호
    has_next: bool = False             # 다음 페이지가 있는지 (page 를 알면 page < last_page 포함)
    has_next_block: bool = False       # 서버 visibleNextButton 원값 (다음 10페이지 묶음)
    total_count: int | None = None     # totalArticleCount (전체글보기 menuId=0 에서만 옴)

    @classmethod
    def from_api(cls, d: Any, *, page: int = 0) -> Self:
        d = as_dict(d)
        last_page = as_int(d.get("lastNavigationPageNumber"))
        next_block = bool(d.get("visibleNextButton", False))
        total = d.get("totalArticleCount")
        return cls(
            last_page=last_page,
            has_next=next_block or (0 < page < last_page),
            has_next_block=next_block,
            total_count=as_int(total) if total is not None else None,
        )


@dataclass(slots=True, kw_only=True)
class ArticleSummary:
    """게시글 목록 항목 (boardlist articleList[].item)"""

    article_id: int
    cafe_id: int
    menu_id: int
    subject: str = ""
    writer_nick: str = ""
    writer_key: str = ""
    written_at: datetime | None = None
    read_count: int = 0
    comment_count: int = 0
    like_count: int = 0
    has_image: bool = False
    item_type: ArticleListItemType = ArticleListItemType.ARTICLE
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @property
    def ref(self) -> ArticleRef:
        return ArticleRef(cafe_id=self.cafe_id, article_id=self.article_id, menu_id=self.menu_id)

    @classmethod
    def from_api(cls, entry: Any) -> Self:
        entry = as_dict(entry)
        it = as_dict(entry.get("item")) or entry
        writer = as_dict(it.get("writerInfo"))
        return cls(
            article_id=as_int(it.get("articleId")),
            cafe_id=as_int(it.get("cafeId")),
            menu_id=as_int(it.get("menuId")),
            subject=str(it.get("subject") or ""),
            writer_nick=str(pick(writer, "nickName", "nick", default=it.get("nickName") or "")),
            writer_key=str(writer.get("memberKey") or ""),
            written_at=ms_to_datetime(it.get("writeDateTimestamp")),
            read_count=as_int(it.get("readCount")),
            comment_count=as_int(it.get("commentCount")),
            like_count=as_int(it.get("likeCount")),
            has_image=bool(it.get("hasImage", False)),
            item_type=ArticleListItemType(entry.get("type") or "ARTICLE"),
            raw=entry,
        )


@dataclass(slots=True, kw_only=True)
class ArticlePage:
    """게시글 목록 한 페이지"""

    items: list[ArticleSummary] = field(default_factory=list)
    page: int = 1
    page_info: PageInfo = field(default_factory=PageInfo)

    def __iter__(self) -> Iterator[ArticleSummary]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


@dataclass(slots=True, kw_only=True)
class ArticleAuthority:
    """내 권한 (gw v4 result.authority)"""

    can_write_comment: bool = False
    can_write_reply: bool = False
    can_modify: bool = False
    can_remove: bool = False
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Any) -> Self:
        d = as_dict(d)
        return cls(
            can_write_comment=bool(d.get("isWriteComment", False)),
            can_write_reply=bool(d.get("isWriteReply", False)),
            can_modify=bool(d.get("isModify", False)),
            can_remove=bool(d.get("isRemove", False)),
            raw=d,
        )


@dataclass(slots=True, kw_only=True)
class Article:
    """게시글 상세 (gw v4 result)"""

    cafe: Cafe
    article_id: int
    menu: Board
    subject: str = ""
    head: str = ""                 # 말머리
    writer: Writer = field(default_factory=Writer)
    written_at: datetime | None = None
    read_count: int = 0
    comment_count: int = 0
    content_html: str = ""
    is_notice: bool = False
    authority: ArticleAuthority = field(default_factory=ArticleAuthority)
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @property
    def content_text(self) -> str:
        return html_to_text(self.content_html)

    @property
    def ref(self) -> ArticleRef:
        return ArticleRef(
            cafe_id=self.cafe.cafe_id,
            article_id=self.article_id,
            menu_id=self.menu.menu_id or None,
            cafe_url=self.cafe.url or None,
        )

    @property
    def is_snippet(self) -> bool:
        """비회원 공개 범위 밖 글: 본문 대신 요약(summary)만 온 응답"""
        return "article" not in self.raw and "summary" in self.raw

    @classmethod
    def from_api(cls, result: Any) -> Self:
        result = as_dict(result)
        if "article" not in result and "cafeViewModel" in result:
            return cls._from_snippet(result)
        a = as_dict(result.get("article"))
        cafe = Cafe.from_api(result.get("cafe"))
        if not cafe.cafe_id:
            cafe.cafe_id = as_int(result.get("cafeId"))
        return cls(
            cafe=cafe,
            article_id=as_int(pick(a, "id", default=result.get("articleId"))),
            menu=Board.from_api(a.get("menu")),
            subject=str(a.get("subject") or ""),
            head=str(a.get("head") or ""),
            writer=Writer.from_api(a.get("writer")),
            written_at=ms_to_datetime(a.get("writeDate")),
            read_count=as_int(a.get("readCount")),
            comment_count=as_int(a.get("commentCount")),
            content_html=str(a.get("contentHtml") or ""),
            is_notice=bool(a.get("isNotice", False)),
            authority=ArticleAuthority.from_api(result.get("authority")),
            raw=result,
        )

    @classmethod
    def _from_snippet(cls, result: JSON) -> Self:
        """[실측 2026-11-13] 비회원 요약 응답 (responseViewType=snippet-non-member)

        cafeViewModel/menuViewModel/subject/summary/writer/writeDate 가 최상위에 온다.
        """
        cafe = Cafe.from_api(result.get("cafeViewModel"))
        cafe.cafe_id = cafe.cafe_id or as_int(result.get("cafeId"))
        menu = Board.from_api({**as_dict(result.get("menuViewModel")), "menuId": result.get("menuId")})
        writer = as_dict(result.get("writer"))
        return cls(
            cafe=cafe,
            article_id=as_int(result.get("articleId")),
            menu=menu,
            subject=str(result.get("subject") or ""),
            writer=Writer.from_api(writer, level_src={"memberLevelName": writer.get("memberLevelName")}),
            written_at=ms_to_datetime(result.get("writeDate")),
            read_count=as_count(result.get("readCount")),  # [실측] 요약 응답은 "4만" 같은 표시 문자열
            comment_count=as_count(result.get("commentCount")),
            content_html=html.escape(str(result.get("summary") or "")),
            authority=ArticleAuthority.from_api(result.get("authority")),
            raw=result,
        )
