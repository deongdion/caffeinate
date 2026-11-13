"""데이터 모델 (dataclass)"""
from .article import (
    Article,
    ArticleAuthority,
    ArticlePage,
    ArticleRef,
    ArticleSummary,
    PageInfo,
)
from .board import Board
from .cafe import Cafe
from .comment import Comment, CommentPage, build_tree
from .cookie import Cookie
from .fingerprint import Fingerprint, firefox_user_agent
from .like import LikeMembers, LikeStatus, LikeUser, Reaction
from .member import CafeGrade, Identifier, Membership, MyInfo, Writer
from .photo import UploadedImage

__all__ = [
    "Article",
    "ArticleAuthority",
    "ArticlePage",
    "ArticleRef",
    "ArticleSummary",
    "Board",
    "Cafe",
    "CafeGrade",
    "Comment",
    "CommentPage",
    "Cookie",
    "Fingerprint",
    "Identifier",
    "LikeMembers",
    "LikeStatus",
    "LikeUser",
    "Membership",
    "MyInfo",
    "PageInfo",
    "Reaction",
    "UploadedImage",
    "Writer",
    "build_tree",
    "firefox_user_agent",
]
