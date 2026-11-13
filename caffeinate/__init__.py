"""
caffeinate - 네이버 카페 자동화 (curl_cffi AsyncSession 기반)

    from caffeinate import Caffeinate
    async with Caffeinate() as cafe:
        print(await cafe.cafes.my_cafes())
"""
from .core import (
    CafeSession,
    CaffeinateError,
    CookieStore,
    LoginError,
    NaverAPIError,
    NetworkError,
    NotLoggedInError,
    ParseError,
    Settings,
    endpoints,
)
from .enums import BoardType, BrowserBrand, MenuType, ReactionType, SortBy, ViewType
from .lib import Caffeinate, load_fingerprint
from .models import (
    Article,
    ArticlePage,
    ArticleRef,
    ArticleSummary,
    Board,
    Cafe,
    Comment,
    CommentPage,
    Cookie,
    Fingerprint,
    Identifier,
    LikeStatus,
    Membership,
    MyInfo,
    UploadedImage,
    Writer,
    build_tree,
)

__version__ = "0.2.0"

__all__ = [
    "Article",
    "ArticlePage",
    "ArticleRef",
    "ArticleSummary",
    "Board",
    "BoardType",
    "BrowserBrand",
    "Cafe",
    "CafeSession",
    "Caffeinate",
    "CaffeinateError",
    "Comment",
    "CommentPage",
    "Cookie",
    "CookieStore",
    "Fingerprint",
    "Identifier",
    "LikeStatus",
    "LoginError",
    "Membership",
    "MenuType",
    "MyInfo",
    "NaverAPIError",
    "NetworkError",
    "NotLoggedInError",
    "ParseError",
    "ReactionType",
    "Settings",
    "SortBy",
    "UploadedImage",
    "ViewType",
    "Writer",
    "build_tree",
    "endpoints",
    "load_fingerprint",
]
