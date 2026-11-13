"""API 응답(JSON) 방어적 파싱 + 네이버 카페 URL 파싱"""
import re
from datetime import datetime, timezone
from typing import Any, TypeAlias
from urllib.parse import parse_qs, unquote, urlparse

from ..core.errors import ParseError

JSON: TypeAlias = dict[str, Any]


# ---------------------------------------------------------------- JSON 헬퍼
def pick(d: Any, *keys: str, default: Any = None) -> Any:
    """dict 에서 처음으로 존재하는(None 아님) 키 값"""
    if isinstance(d, dict):
        for k in keys:
            v = d.get(k)
            if v is not None:
                return v
    return default


def dig(d: Any, *path: str | int, default: Any = None) -> Any:
    """중첩 경로 안전 접근: dig(data, "result", "myCafe", "cafes")"""
    cur: Any = d
    for key in path:
        if isinstance(key, int):
            if not isinstance(cur, list) or not -len(cur) <= key < len(cur):
                return default
            cur = cur[key]
        else:
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
    return default if cur is None else cur


def as_dict(v: Any) -> JSON:
    return v if isinstance(v, dict) else {}


def as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def is_ascii_digits(s: str) -> bool:
    """"123" 처럼 ASCII 숫자로만 된 문자열인지 (str.isdigit 은 "²" 같은 문자도 True 라 int() 가 깨진다)"""
    return s.isascii() and s.isdigit()


_COUNT_UNITS: dict[str, int] = {"천": 1_000, "만": 10_000, "억": 100_000_000}
_RE_COUNT = re.compile(r"^\s*([\d,]+(?:\.\d+)?)\s*([천만억]?)\s*\+?\s*$")


def as_count(v: Any, default: int = 0) -> int:
    """조회수 등 개수 값 -> int. 숫자 외에 "1,234", "4만", "3.4만", "1.2천" 형식도 받는다

    [실측 2026-11-13] 비회원 요약(snippet) 게시글 응답은 readCount 를 "4만" 같은 표시 문자열로 준다
    (이 경우 값은 근사치).
    """
    if isinstance(v, bool):
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str) and (m := _RE_COUNT.match(v)):
        num = float(m.group(1).replace(",", ""))
        return round(num * _COUNT_UNITS.get(m.group(2), 1))
    return default


def ms_to_datetime(v: Any) -> datetime | None:
    """밀리초 epoch -> aware datetime(UTC)"""
    if v in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


# ---------------------------------------------------------------- URL 파싱
_RE_FE_ARTICLE = re.compile(r"^(?:f-e|ca-fe)/(?:web/)?cafes/([^/]+)/articles/(\d+)")
_RE_FE_MENU = re.compile(r"^(?:f-e|ca-fe)/(?:web/)?cafes/([^/]+)/menus/(\d+)")
_RE_FE_CAFE = re.compile(r"^(?:f-e|ca-fe)/(?:web/)?cafes/([^/]+)")
_RE_CAFE_FE_ARTICLE = re.compile(r"^cafe-fe/articles/(\d+)/(\d+)")
_RE_SLUG = re.compile(r"^[A-Za-z0-9_-]+$")
# 경로 첫 부분이 카페 slug 가 아니라 서비스 경로인 것들 (ca-fe/{slug}/{articleId} 같은 모바일 링크는 한 칸 건너뜀)
_PATH_PREFIXES = frozenset({"f-e", "ca-fe", "cafe-fe"})
# 구형 링크의 쿼리 키 별칭 (ArticleList.nhn 은 search.clubid / search.menuid)
_QS_CAFE_KEYS = ("cafeid", "clubid", "search.clubid")
_QS_MENU_KEYS = ("menuid", "search.menuid")


def _is_naver_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return host == "naver.com" or host.endswith(".naver.com")


def _inner_query(value: str) -> dict[str, list[str]]:
    """iframe_url(_utf8) 값 안의 쿼리. iframe_url_utf8 은 한 번 더 인코딩돼 있어 '?' 가 보일 때까지 푼다"""
    for _ in range(3):
        if "?" in value:
            break
        value = unquote(value)
    return parse_qs(urlparse(value).query)


def parse_cafe_url(url: str) -> dict[str, int | str | None]:
    """
    네이버 카페 URL 에서 cafe_id / cafe_url(slug) / menu_id / article_id 추출.

    지원 형식 (실측 URL 기준):
      - https://cafe.naver.com/f-e/cafes/{cafeId}/articles/{articleId}?menuid=
      - https://cafe.naver.com/f-e/cafes/{cafeId}/menus/{menuId}
      - https://m.cafe.naver.com/ca-fe/web/cafes/{cafeId|slug}/articles/{articleId}
      - https://m.cafe.naver.com/ca-fe/{slug}/{articleId}, https://m.cafe.naver.com/{slug}/{articleId}
      - https://cafe.naver.com/{slug}/{articleId}
      - https://cafe.naver.com/{slug}?iframe_url=...clubid=..&articleid=..
        (iframe_url_utf8 처럼 두 번 인코딩된 값도 지원)
      - https://cafe.naver.com/ArticleRead.nhn?clubid=..&menuid=..&articleid=..
      - https://cafe.naver.com/ArticleList.nhn?search.clubid=..&search.menuid=..
      - https://section.cafe.naver.com/cafe-fe/articles/{cafeId}/{articleId}
      - 숫자 문자열 (cafeId)
    """
    out: dict[str, int | str | None] = {
        "cafe_id": None, "cafe_url": None, "menu_id": None, "article_id": None,
    }
    s = url.strip()
    if is_ascii_digits(s):
        out["cafe_id"] = int(s)
        return out

    if "://" not in s and s.lower().startswith(("cafe.naver.com", "m.cafe.naver.com")):
        s = "https://" + s
    parsed = urlparse(s)
    if parsed.hostname and not _is_naver_host(parsed.hostname):
        raise ParseError(f"네이버 URL이 아닙니다: {url}")

    qs = {k.lower(): v[-1] for k, v in parse_qs(parsed.query).items()}
    # iframe_url / iframe_url_utf8 안에 진짜 파라미터가 들어있는 구형 링크
    for inner_key in ("iframe_url_utf8", "iframe_url"):
        if inner_key in qs:
            for k, v in _inner_query(qs[inner_key]).items():
                qs.setdefault(k.lower(), v[-1])

    cafe: str | None = next((qs[k] for k in _QS_CAFE_KEYS if qs.get(k)), None)
    menu: str | None = next((qs[k] for k in _QS_MENU_KEYS if qs.get(k)), None)
    article: str | None = qs.get("articleid")
    slug: str | None = None

    path = parsed.path.strip("/")
    if parsed.hostname is None and path and _RE_SLUG.match(path):
        # 그냥 slug 문자열
        slug = path
        path = ""

    def split_cafe(part: str) -> None:
        nonlocal cafe, slug
        if is_ascii_digits(part):
            cafe = cafe or part
        else:
            slug = part

    if m := _RE_FE_ARTICLE.match(path):
        split_cafe(m.group(1))
        article = article or m.group(2)
    elif m := _RE_FE_MENU.match(path):
        split_cafe(m.group(1))
        menu = menu or m.group(2)
    elif m := _RE_CAFE_FE_ARTICLE.match(path):
        cafe, article = cafe or m.group(1), article or m.group(2)
    elif m := _RE_FE_CAFE.match(path):
        split_cafe(m.group(1))
    elif path:
        parts = path.split("/")
        if parts[0] in _PATH_PREFIXES:
            parts = parts[1:]
        if parts and is_ascii_digits(parts[0]):
            if len(parts) >= 2:
                cafe = cafe or parts[0]  # [추정] cafe.naver.com/{cafeId}/{articleId}
        elif parts and _RE_SLUG.match(parts[0]):
            slug = parts[0]
        if len(parts) >= 2 and is_ascii_digits(parts[-1]):
            article = article or parts[-1]

    out["cafe_id"] = int(cafe) if cafe and is_ascii_digits(cafe) else None
    out["cafe_url"] = slug
    out["menu_id"] = int(menu) if menu and is_ascii_digits(menu) else None
    out["article_id"] = int(article) if article and is_ascii_digits(article) else None
    return out
