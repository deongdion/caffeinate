"""API 응답(JSON) 방어적 파싱 + 네이버 카페 URL 파싱"""
import re
from datetime import datetime, timezone
from typing import Any, TypeAlias
from urllib.parse import parse_qs, urlparse

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
_RESERVED_SLUGS = frozenset({"f-e", "ca-fe", "cafe-fe", "ArticleRead.nhn", "ArticleList.nhn"})


def parse_cafe_url(url: str) -> dict[str, int | str | None]:
    """
    네이버 카페 URL 에서 cafe_id / cafe_url(slug) / menu_id / article_id 추출.

    지원 형식 (실측 URL 기준):
      - https://cafe.naver.com/f-e/cafes/{cafeId}/articles/{articleId}?menuid=
      - https://cafe.naver.com/f-e/cafes/{cafeId}/menus/{menuId}
      - https://m.cafe.naver.com/ca-fe/web/cafes/{cafeId|slug}/articles/{articleId}
      - https://cafe.naver.com/{slug}/{articleId}
      - https://cafe.naver.com/{slug}?iframe_url=...clubid=..&articleid=..
      - https://cafe.naver.com/ArticleRead.nhn?clubid=..&menuid=..&articleid=..
      - https://section.cafe.naver.com/cafe-fe/articles/{cafeId}/{articleId}
      - 숫자 문자열 (cafeId)
    """
    out: dict[str, int | str | None] = {
        "cafe_id": None, "cafe_url": None, "menu_id": None, "article_id": None,
    }
    s = url.strip()
    if s.isdigit():
        out["cafe_id"] = int(s)
        return out

    if "://" not in s and s.startswith(("cafe.naver.com", "m.cafe.naver.com")):
        s = "https://" + s
    parsed = urlparse(s)
    if parsed.hostname and not parsed.hostname.endswith("naver.com"):
        raise ParseError(f"네이버 URL이 아닙니다: {url}")

    qs = {k.lower(): v[-1] for k, v in parse_qs(parsed.query).items()}
    # iframe_url / iframe_url_utf8 안에 진짜 파라미터가 들어있는 구형 링크
    for inner_key in ("iframe_url_utf8", "iframe_url"):
        if inner_key in qs:
            inner = urlparse(qs[inner_key])
            for k, v in parse_qs(inner.query).items():
                qs.setdefault(k.lower(), v[-1])

    cafe: str | None = qs.get("cafeid") or qs.get("clubid")
    menu: str | None = qs.get("menuid")
    article: str | None = qs.get("articleid")
    slug: str | None = None

    path = parsed.path.strip("/")
    if parsed.hostname is None and path and _RE_SLUG.match(path):
        # 그냥 slug 문자열
        slug = path
        path = ""

    if m := _RE_FE_ARTICLE.match(path):
        cafe_part, article = m.group(1), article or m.group(2)
        cafe, slug = (cafe or cafe_part, slug) if cafe_part.isdigit() else (cafe, cafe_part)
    elif m := _RE_FE_MENU.match(path):
        cafe_part, menu = m.group(1), menu or m.group(2)
        cafe, slug = (cafe or cafe_part, slug) if cafe_part.isdigit() else (cafe, cafe_part)
    elif m := _RE_CAFE_FE_ARTICLE.match(path):
        cafe, article = cafe or m.group(1), article or m.group(2)
    elif m := _RE_FE_CAFE.match(path):
        cafe_part = m.group(1)
        cafe, slug = (cafe or cafe_part, slug) if cafe_part.isdigit() else (cafe, cafe_part)
    elif path:
        parts = path.split("/")
        if parts[0] not in _RESERVED_SLUGS and _RE_SLUG.match(parts[0]):
            slug = parts[0]
        if len(parts) >= 2 and parts[-1].isdigit():
            article = article or parts[-1]

    out["cafe_id"] = int(cafe) if cafe and cafe.isdigit() else None
    out["cafe_url"] = slug
    out["menu_id"] = int(menu) if menu and menu.isdigit() else None
    out["article_id"] = int(article) if article and article.isdigit() else None
    return out
