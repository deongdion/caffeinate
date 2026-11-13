"""
caffeinate

    import asyncio
    from caffeinate import Caffeinate

    async def main():
        async with Caffeinate() as cafe:
            async for a in cafe.boards.iter_articles("remonterace", 2, limit=20):
                print(a.article_id, a.subject)

    asyncio.run(main())

동기 코드에서는 `caffeinate.run(lambda cafe: cafe.cafes.my_cafes())`.
디버그 로그는 `caffeinate.enable_logging()` (로거 이름 "caffeinate").
"""
import logging as _logging

from .auth.login import LoginOptions, LoginResult
from .core import (
    ArticleNotFoundError,
    CafeNotFoundError,
    CafeSession,
    CaffeinateError,
    CookieStore,
    LoginError,
    NaverAPIError,
    NetworkError,
    NotLoggedInError,
    ParseError,
    PermissionDeniedError,
    RateLimitedError,
    Settings,
    endpoints,
)
from .enums import (
    ArticleListItemType,
    BoardType,
    BrowserBrand,
    MenuType,
    Platform,
    ReactionType,
    RequestKind,
    SortBy,
    ViewType,
)
from .lib import Caffeinate, enable_logging, load_fingerprint, run
from .models import (
    Article,
    ArticleAuthority,
    ArticlePage,
    ArticleRef,
    ArticleSummary,
    Board,
    Cafe,
    CafeGrade,
    Comment,
    CommentPage,
    Cookie,
    Fingerprint,
    Identifier,
    LikeMembers,
    LikeStatus,
    LikeUser,
    Membership,
    MyInfo,
    PageInfo,
    Reaction,
    UploadedImage,
    Writer,
    build_tree,
)
from .services.base import CafeLike, ImageLike
from .utils import html_to_text, parse_cafe_url

# 라이브러리 관례: 기본으로는 아무것도 출력하지 않는다 (enable_logging() 또는 앱의 logging 설정으로 켠다)
_logging.getLogger("caffeinate").addHandler(_logging.NullHandler())

__version__ = "0.4.0"

__all__ = [
    "Article",
    "ArticleAuthority",
    "ArticleListItemType",
    "ArticleNotFoundError",
    "ArticlePage",
    "ArticleRef",
    "ArticleSummary",
    "Board",
    "BoardType",
    "BrowserBrand",
    "Cafe",
    "CafeGrade",
    "CafeLike",
    "CafeNotFoundError",
    "CafeSession",
    "Caffeinate",
    "CaffeinateError",
    "Comment",
    "CommentPage",
    "Cookie",
    "CookieStore",
    "Fingerprint",
    "Identifier",
    "ImageLike",
    "LikeMembers",
    "LikeStatus",
    "LikeUser",
    "LoginError",
    "LoginOptions",
    "LoginResult",
    "Membership",
    "MenuType",
    "MyInfo",
    "NaverAPIError",
    "NetworkError",
    "NotLoggedInError",
    "PageInfo",
    "ParseError",
    "PermissionDeniedError",
    "Platform",
    "RateLimitedError",
    "Reaction",
    "ReactionType",
    "RequestKind",
    "Settings",
    "SortBy",
    "UploadedImage",
    "ViewType",
    "Writer",
    "__version__",
    "build_tree",
    "enable_logging",
    "endpoints",
    "html_to_text",
    "load_fingerprint",
    "parse_cafe_url",
    "run",
]
