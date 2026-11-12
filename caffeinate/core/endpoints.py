"""
네이버 카페 API 엔드포인트 (2026-11-12 실측 기준)

레거시 .nhn/.json AJAX 는 폐지됨 -> 신규 REST 스택 사용.
cafemain/cafeinfo/boardlist API 는 `x-cafe-product: pc` 헤더가 필요하다.
"""
from typing import Final

APIS: Final = "https://apis.naver.com"
GW: Final = "https://article.cafe.naver.com/gw"
LIKE: Final = "https://cafe.like.naver.com"
LIKE_ROUTE: Final = "https://route-like.naver.com"

PRODUCT_HEADERS: Final[dict[str, str]] = {"x-cafe-product": "pc"}

# ---- 인증/사용자 [실측] ----
# message.result: {loggedIn, userId, nickname, memberKey, ...}
MEMBER_IDENTIFIER: Final = f"{APIS}/cafe-home-web/cafe-home/v1/member/identifier"  # ?cafeId=
MEMBER_IDENTIFIER_M: Final = "https://apis.cafe.naver.com/home/v1/member/identifier"  # ?cafeUrl=

# ---- 내 카페 목록 [실측] result.myCafe.cafes[] ----
CAFE_HOME_PC: Final = f"{APIS}/cafe-home-web/cafe-home/v3/homepc"
BADGE_COUNTS: Final = f"{APIS}/cafe-home-web/cafe-home/v3/badge-counts"

_CAFEMAIN: Final = f"{APIS}/cafe-web/cafe-cafemain-api/v1.0/cafes"
_CAFEINFO: Final = f"{APIS}/cafe-web/cafe-cafeinfo-api/v1.0/cafes"
_BOARDLIST: Final = f"{APIS}/cafe-web/cafe-boardlist-api/v1/cafes"

# ---- like 서비스 ----
# [실측] 조회: /v1/search/contents?q=CAFE[{cafeId}_{cafeUrl}_{articleId}]  (/v1/search 는 500)
LIKE_SEARCH: Final = f"{LIKE}/v1/search/contents"
# [실측] 등록/취소 브라우저 요청: GET route-like /v1/services/CAFE/contents/{cid}?_method=POST|DELETE
#   guestToken 과 timestamp 는 route-like /v1/search/contents 응답 값을 그대로 쓴다 (timestamp 가 다르면 4013)
LIKE_ROUTE_SEARCH: Final = f"{LIKE_ROUTE}/v1/search/contents"

# ---- 내 카페 목록 폴백 [실측] 레거시 GNB (cp949 HTML) ----
MY_CAFE_GNB: Final = "https://cafe.naver.com/MyCafeListGNBView.nhn"

# ---- 에디터/사진 [실측 2026-11-12] ----
EDITOR: Final = "https://apis.cafe.naver.com/editor"
PHOTO_SESSION_KEY: Final = "https://platform.editor.naver.com/api/cafepc001/v1/photo-uploader/session-key"
UPPHOTO: Final = "https://cafe.upphoto.naver.com"
PHINF_DOMAIN: Final = "https://cafeptthumb-phinf.pstatic.net"

# ---- 댓글 작성 [실측] form-urlencoded ----
COMMENT_POST: Final = f"{APIS}/cafe-web/cafe-mobile/CommentPost.json"
COMMENT_REPLY: Final = f"{APIS}/cafe-web/cafe-mobile/CommentReply.json"


# ---------------------------------------------------------------- 카페/게시판 [실측]
def cafe_menus(cafe_id: int) -> str:
    """result.menus[] + linkMenus[]"""
    return f"{_CAFEMAIN}/{cafe_id}/menus"


def cafe_members(cafe_id: int) -> str:
    """내 가입 여부 {cafeMember, cafeApply} (로그인 필요, 비로그인 401)"""
    return f"{_CAFEINFO}/{cafe_id}/members"


def cafe_grade_candidates(cafe_id: int) -> tuple[str, ...]:
    """[미확정] 카페 내 등급 API 후보 - 멤버 상태에서 확정 필요"""
    return (
        f"{_CAFEINFO}/{cafe_id}/members/me/grade",
        f"{_CAFEMAIN}/{cafe_id}/member",
        f"{_CAFEINFO}/{cafe_id}/members/me",
    )


def article_list(cafe_id: int, menu_id: int) -> str:
    """result.articleList[] + pageInfo"""
    return f"{_BOARDLIST}/{cafe_id}/menus/{menu_id}/articles"


def notice_list(cafe_id: int, menu_id: int) -> str:
    return f"{_BOARDLIST}/{cafe_id}/notices/menus/{menu_id}"


# ---------------------------------------------------------------- 게시글/댓글 gw [실측]
# 경로의 카페 부분이 숫자 ID 면 useCafeId=true, 카페 URL(slug)이면 false (반대로 주면 400)
def gw_article(cafe: int | str, article_id: int) -> str:
    return f"{GW}/v4/cafes/{cafe}/articles/{article_id}"


def gw_comments(cafe: int | str, article_id: int) -> str:
    """result.comments.items[] (대댓글은 평탄화: refId/isRef)"""
    return f"{GW}/v4/cafes/{cafe}/articles/{article_id}/comments"


# ---------------------------------------------------------------- 쓰기 [실측 2026-11-12]
def editor_init(cafe_id: int) -> str:
    """?menuId=&from=pc -> result.token (에디터 JWT, 사진 세션키 발급용)"""
    return f"{EDITOR}/v2/cafes/{cafe_id}/editor"


def editor_write_article(cafe_id: int, menu_id: int) -> str:
    """POST {article: {...contentJson}} -> result.articleId"""
    return f"{EDITOR}/v2.0/cafes/{cafe_id}/menus/{menu_id}/articles"


def editor_update_article(cafe_id: int, article_id: int) -> str:
    """POST 작성과 같은 페이로드 + headId"""
    return f"{EDITOR}/v2.0/cafes/{cafe_id}/articles/{article_id}"


def photo_upload(session_key: str) -> str:
    """POST multipart(image) ?userId=&extractExif=... (쿠키 없이) -> XML <item>"""
    return f"{UPPHOTO}/{session_key}/simpleUpload/0"


def like_content(cid: str) -> str:
    return f"{LIKE_ROUTE}/v1/services/CAFE/contents/{cid}"


# ---------------------------------------------------------------- 웹 페이지 URL (Referer)
def cafe_page(cafe_id: int, menu_id: int | None = None) -> str:
    base = f"https://cafe.naver.com/f-e/cafes/{cafe_id}"
    return f"{base}/menus/{menu_id}" if menu_id else base


def article_page(cafe_id: int, article_id: int, menu_id: int | None = None) -> str:
    url = f"https://cafe.naver.com/f-e/cafes/{cafe_id}/articles/{article_id}"
    return f"{url}?menuid={menu_id}" if menu_id else url


def write_page(cafe_id: int, menu_id: int) -> str:
    return f"https://cafe.naver.com/ca-fe/cafes/{cafe_id}/menus/{menu_id}/articles/write?boardType=L"
