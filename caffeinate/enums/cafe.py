"""네이버 카페 API 값 열거형 (2026-11 실측 응답 기준)"""
from enum import StrEnum


class _Lenient(StrEnum):
    """API 가 모르는 값을 내려줘도 죽지 않도록 UNKNOWN 으로 받는 StrEnum"""

    @classmethod
    def _missing_(cls, value: object) -> "_Lenient":
        del value
        return cls["UNKNOWN"]  # type: ignore[return-value]


class MenuType(_Lenient):
    """cafe-cafemain-api menus[].menuType"""

    BOARD = "B"       # 일반 게시판 (앨범형도 B + boardType I)
    SEPARATOR = "S"   # 구분선 (name 없음)
    MEMO = "M"        # 가입인사 등 메모 게시판
    ATTENDANCE = "A"  # 출석체크
    UNKNOWN = "?"     # 실측에 없던 값


class BoardType(_Lenient):
    """menus[].boardType - 목록 표시 형태"""

    LIST = "L"
    IMAGE = "I"
    MEMO = "M"
    UNKNOWN = "?"


class SortBy(StrEnum):
    """게시글 목록 정렬 [실측 2026-11-13]

    서버가 받는 값은 TIME / LIKE / COMMENT / READ 이고, 그 외 값은 400.
    COMMENT, READ 는 받기만 하고 결과는 최신순과 같아서 넣지 않았다.
    """

    TIME = "TIME"   # 최신순
    LIKE = "LIKE"   # 좋아요순


class ViewType(StrEnum):
    """게시글 목록 보기 형태 (boardlist API viewType, L 실측 확인)"""

    LIST = "L"
    IMAGE = "I"
    CARD = "C"


class ReactionType(StrEnum):
    """like 서비스 반응 종류"""

    LIKE = "like"


class ArticleListItemType(_Lenient):
    """boardlist articleList[].type"""

    ARTICLE = "ARTICLE"
    AD = "AD"
    UNKNOWN = "?"
