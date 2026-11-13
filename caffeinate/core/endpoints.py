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
# [실측 2026-11-13 Camoufox UI 캡처] 게시글 화면의 like 위젯(jQuery 3.3.1, reaction.basic.js)은 전부
# route-like.naver.com 으로 <script> JSONP GET 을 보낸다 (XHR/fetch 아님 -> in-page 훅으로는 안 보인다):
#   조회/토큰: /v1/search/contents?suppress_response_codes=true&callback=&q=CAFE[cid]&isDuplication=false
#              &cssIds=BASIC_PC,CAFE_PC&pool=cafe&_=   (페이지 로드 시 1회, 응답에 guestToken/timestamp)
#   등록/취소: /v1/services/CAFE/contents/{cid}?suppress_response_codes=true&_method=POST|DELETE&callback=...
#   Referer 는 게시글 iframe URL (ca-fe/...&fromNext=true).
# 예전에 쓰던 cafe.like.naver.com /v1/search/contents (cssIds=MULTI_PC) 는 현재 프론트가 부르지 않는다.
# Aside 번들 분석이 주장한 apis.naver.com/cafe-web/like/v1/... 는 UI 캡처에서 한 번도 나오지 않았다.
# cid = {cafeId}_{cafeUrl}_{articleId}. cafeUrl 은 카페의 참 slug (gw 게시글 응답 cafe.url) 여야 한다. 틀린 slug 를
#   넣어도 빈 결과가 아니라 reactions=[] 인 콘텐츠가 오고 guestToken 도 발급된다 (그 cid 로 등록하면 엉뚱한 콘텐츠에 반영).
#   guestToken 과 timestamp 는 search 응답 값을 그대로 쓴다 (timestamp 가 다르면 4013) [실측]
LIKE_SEARCH: Final = f"{LIKE}/v1/search/contents"  # 구 조회 경로 (현재 프론트 미사용, 호환용으로만 남김)
LIKE_ROUTE_SEARCH: Final = f"{LIKE_ROUTE}/v1/search/contents"

# ---- 내 카페 목록 폴백 [실측] 레거시 GNB (cp949 HTML) ----
MY_CAFE_GNB: Final = "https://cafe.naver.com/MyCafeListGNBView.nhn"

# ---- 에디터/사진 [실측 2026-11-12] ----
EDITOR: Final = "https://apis.cafe.naver.com/editor"
PHOTO_SESSION_KEY: Final = "https://platform.editor.naver.com/api/cafepc001/v1/photo-uploader/session-key"
UPPHOTO: Final = "https://cafe.upphoto.naver.com"
PHINF_DOMAIN: Final = "https://cafeptthumb-phinf.pstatic.net"

# ---- 댓글 작성/삭제/게시글 삭제 [실측] form-urlencoded ----
COMMENT_POST: Final = f"{APIS}/cafe-web/cafe-mobile/CommentPost.json"
COMMENT_REPLY: Final = f"{APIS}/cafe-web/cafe-mobile/CommentReply.json"
COMMENT_DELETE: Final = f"{APIS}/cafe-web/cafe-mobile/CommentDelete.json"  # [2026-11-13] 규약은 Post/Reply 와 동일 계열, UI 실측은 미검증
# [실측 2026-11-13 Camoufox UI 캡처] 사진 댓글: 파일 선택 즉시 세션키(본문 없는 POST) -> upphoto 업로드,
#   등록 시 CommentPost/CommentReply 폼에 imagePath/imageFileName/imageWidth/imageHeight 를 넣는다.
COMMENT_PHOTO_SESSION_KEY: Final = f"{APIS}/cafe-web/cafe-mobile/PhotoInfraSessionKey.json"
ARTICLE_DELETE: Final = f"{APIS}/cafe-web/cafe-mobile/ArticleDelete.json"


# ---------------------------------------------------------------- 카페/게시판 [실측]
def cafe_menus(cafe_id: int) -> str:
    """result.menus[] + linkMenus[]"""
    return f"{_CAFEMAIN}/{cafe_id}/menus"


def cafe_members(cafe_id: int) -> str:
    """내 가입 여부 {cafeMember, cafeApply} (로그인 필요, 비로그인 401)"""
    return f"{_CAFEINFO}/{cafe_id}/members"


def cafe_my(cafe_id: int) -> str:
    """카페 내 내 등급/활동 ?memberDataOptions=NFLEA

    [실측 2026-11-13] result.memberLevel{level,levelName,config(다음 등급 조건)},
    result.memberStat{visitCount,articleCount,commentCount,likeCount}. 미멤버면 500(40003).
    """
    return f"{_CAFEMAIN}/{cafe_id}/my"


def article_list(cafe_id: int, menu_id: int) -> str:
    """result.articleList[] + pageInfo"""
    return f"{_BOARDLIST}/{cafe_id}/menus/{menu_id}/articles"


def notice_list(cafe_id: int, menu_id: int) -> str:
    return f"{_BOARDLIST}/{cafe_id}/notices/menus/{menu_id}"


# ---------------------------------------------------------------- 게시글/댓글 gw [실측]
# 경로의 카페 부분이 숫자 ID 면 useCafeId=true, 카페 URL(slug)이면 false (반대로 주면 400)
def gw_article(cafe: int | str, article_id: int) -> str:
    return f"{GW}/v4/cafes/{cafe}/articles/{article_id}"


def gw_comments(cafe: int | str, article_id: int, page: int | None = None) -> str:
    """result.comments.items[] (대댓글은 평탄화: refId/isRef)

    [실측 2026-11-13] 페이지는 경로 `/comments/pages/{page}` 로 지정한다 (쿼리 ?page= 는 무시되고
    항상 첫 페이지가 온다). 페이지 크기는 쿼리 size (기본 100, size=50 적용 확인).
    마지막 페이지를 넘는 번호는 마지막 페이지를 그대로 돌려준다 (hasNext=false).
    """
    base = f"{GW}/v4/cafes/{cafe}/articles/{article_id}/comments"
    return f"{base}/pages/{page}" if page is not None else base


def like_members(cafe_id: int | str, article_id: int, per_page: int = 10, next_timestamp: int | None = None) -> str:
    """좋아요 누른 멤버 목록 [실측 2026-11-13 사람 세션 캡처: 좋아요 클릭 후 브라우저가 호출, gw/v5]

    [실측 2026-11-13 Aside 캡처] 다음 페이지는 page 번호가 아니라 앞 응답의 result.nextTimestamp 커서:
    `?nextTimestamp={ts}&perPage=10` (쿼리 순서도 이대로).
    """
    url = f"{GW}/v5/cafes/{cafe_id}/articles/{article_id}/likeIt/members"
    if next_timestamp:
        return f"{url}?nextTimestamp={next_timestamp}&perPage={per_page}"
    return f"{url}?perPage={per_page}"


def best_comments(cafe_id: int | str, article_id: int) -> str:
    """베스트 댓글 [실측 2026-11-13 사람 세션 캡처: 게시글 로드 시 호출, gw/v1]"""
    return f"{GW}/v1/cafes/{cafe_id}/articles/{article_id}/best-comments"


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


def article_frame_page(cafe_id: int, article_id: int, menu_id: int | None = None) -> str:
    """게시글 iframe 화면 URL - 게시글/댓글 XHR(gw 조회, best-comments, Comment*/ArticleDelete)의 Referer

    [실측 2026-11-13 UI 캡처] 프론트는 f-e 바깥 화면이 아니라 iframe URL 을 Referer 로 보낸다.
    쿼리는 진입 경로에 따라 다르다: 글 URL 직접 진입 `?fromNext=true`,
    게시판 목록에서 클릭해 진입 `?menuid={m}&referrerAllArticles=false&fromNext=true`
    [실측 2026-11-13 Camoufox 캡처. Chromium(Aside) 캡처 한 건에는 boardtype=L 이 더 있었다 - 진입 화면 차이로 보고
    우리가 흉내 내는 파이어폭스 값을 따른다]. 게시판 번호를 알면 이 게시판 진입 형태를 쓴다.
    """
    base = f"https://cafe.naver.com/ca-fe/cafes/{cafe_id}/articles/{article_id}"
    if menu_id:
        return f"{base}?menuid={menu_id}&referrerAllArticles=false&fromNext=true"
    return f"{base}?fromNext=true"


def write_page(cafe_id: int, menu_id: int) -> str:
    """글쓰기 팝업 URL [실측 2026-11-13 Aside 캡처: 게시판 "글쓰기" 클릭 시 새 창, ?boardType=L 포함]"""
    return f"https://cafe.naver.com/ca-fe/cafes/{cafe_id}/menus/{menu_id}/articles/write?boardType=L"
