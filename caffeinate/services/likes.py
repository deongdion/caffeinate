"""좋아요(공감)

[실측 2026-11-13 Camoufox UI 캡처] 게시글 화면의 like 위젯(jQuery 3.3.1 JSONP)이 보내는 요청 그대로:
  1) 페이지 로드: GET route-like.naver.com/v1/search/contents (<script>) -> 반응 수/내 반응 + guestToken/timestamp
  2) 하트 클릭: GET route-like.naver.com/v1/services/CAFE/contents/{cid}?_method=POST (<script>)
     다시 클릭: 같은 경로 ?_method=DELETE (isPostTimeline 파라미터 없음)
  모두 Referer 는 게시글 iframe URL, Accept */*, sec-fetch-dest script / mode no-cors, Origin 없음.
Aside(인페이지 fetch/XHR 훅) 보고의 apis.naver.com/cafe-web/like/v1/... 경로는 UI 캡처에서 나오지 않았다
(<script> JSONP 를 못 보는 도구라 번들 문자열로 추정한 것).
"""
import json
import random
import re
import time
from typing import Any

from ..core import endpoints
from ..core.errors import ParseError, api_error_class
from ..enums import ReactionType, RequestKind
from ..models import ArticleRef, LikeMembers, LikeStatus, LikeUser
from ..utils.parsing import JSON, as_dict, as_list, dig
from .base import BaseService

_JSONP = re.compile(r"^\s*(?:/\*\*/)?\s*[\w$.]+\s*\((.*)\)\s*;?\s*$", re.DOTALL)


def content_ids(ref: ArticleRef) -> tuple[str, ...]:
    """like 서비스 cid 후보: {cafeId}_{slug}_{articleId} (slug 를 모르면 빈 튜플)

    [실측 2026-11-13] 브라우저는 {cafeId}_{slug}_{articleId} 로 요청하고, slug 는 카페의 참 slug
    (gw 게시글 응답 cafe.url) 여야 한다. 틀린 slug(대소문자만 달라도)로 조회하면 빈 결과가 아니라
    reactions=[] 인 콘텐츠와 guestToken 이 와서, 그대로 등록하면 엉뚱한 cid 에 좋아요가 쌓인다.
    예전에는 30857348 카페의 참 slug 인 "loyaltylife" 를 모든 카페의 폴백 후보로 넣었는데,
    다른 카페에서는 존재하지 않는 cid 라 제거했다 (참 slug 는 LikeService 가 게시글 상세에서 얻는다).
    """
    return (f"{ref.cafe_id}_{ref.cafe_url}_{ref.article_id}",) if ref.cafe_url else ()


def parse_jsonp(text: str, url: str = "") -> Any:
    """`/**/cb({...});` -> {...}. 콜백 없이 순수 JSON 이 와도 받는다."""
    m = _JSONP.match(text)
    try:
        return json.loads(m.group(1) if m else text)
    except ValueError as e:
        raise ParseError(f"like 위젯 JSONP 파싱 실패: {url} {text[:200]}") from e


class JsonpState:
    """한 게시글 화면에 로드된 jQuery 3.3.1 의 JSONP 상태 (콜백 이름 / 캐시 무력화 `_` 값)

    [실측 2026-11-13 UI 캡처] jQuery.expando = "jQuery" + ("3.3.1" + Math.random()).replace(/\\D/g, ""),
    nonce = 스크립트 로드 시각(ms). 첫 JSONP 는 새 콜백 `{expando}_{nonce++}` 를 만들고 `_={nonce++}`,
    이후 요청은 끝난 콜백 이름을 재사용하고 `_` 만 증가한다. 캡처: search callback=..._151 `_`=152,
    좋아요 callback=..._151 `_`=153, 취소 callback=..._151 `_`=154.
    """

    __slots__ = ("callback", "expando", "nonce")

    def __init__(self, now_ms: int | None = None, rand: float | None = None) -> None:
        r = random.random() if rand is None else rand
        self.expando = "jQuery" + re.sub(r"\D", "", "3.3.1" + repr(r))
        self.nonce = int(time.time() * 1000) if now_ms is None else now_ms
        self.callback = ""

    def next(self) -> tuple[str, int]:
        """-> (callback, _) 한 번의 $.ajax({dataType: 'jsonp'}) 호출분"""
        if not self.callback:
            self.callback = f"{self.expando}_{self.nonce}"
            self.nonce += 1
        bust = self.nonce
        self.nonce += 1
        return self.callback, bust


def search_params(cid: str, jq: JsonpState) -> dict[str, Any]:
    """route-like search 쿼리 - 순서까지 UI 캡처값 그대로 [실측 2026-11-13]"""
    callback, bust = jq.next()
    return {
        "suppress_response_codes": "true",
        "callback": callback,
        "q": f"CAFE[{cid}]",
        "isDuplication": "false",
        "cssIds": "BASIC_PC,CAFE_PC",
        "pool": "cafe",
        "_": bust,
    }


def react_params(
    method: str, reaction: ReactionType, category_id: int, token: str, issued_at: int, jq: JsonpState
) -> dict[str, Any]:
    """등록(POST)/취소(DELETE) 쿼리 - 순서까지 UI 캡처값 그대로 [실측 2026-11-13]

    취소에는 isPostTimeline 이 없다 (캡처).
    """
    callback, bust = jq.next()
    params: dict[str, Any] = {
        "suppress_response_codes": "true",
        "_method": method,
        "callback": callback,
        "displayId": "CAFE",
        "reactionType": reaction.value,
        "categoryId": category_id,
        "guestToken": token,
        "timestamp": issued_at,
        "_ch": "pcw",
        "isDuplication": "false",
        "lang": "ko",
        "countType": "default",
        "count": 1,
        "history": "",
        "runtimeStatus": "",
    }
    if method == "POST":
        params["isPostTimeline"] = "false"
    params["_"] = bust
    return params


class LikeService(BaseService):
    """좋아요 기능 (`cafe.likes`). ref 인자는 게시글 URL 문자열 또는 ArticleRef."""

    async def _true_ref(self, ref: ArticleRef) -> ArticleRef:
        """게시글 상세의 cafe.url(참 slug)로 cafe_url 을 채운 ref"""
        article = await self._client.articles.get(ref)
        slug = article.cafe.url or None
        if not slug:
            raise ParseError(f"게시글 응답에 카페 slug(cafe.url)가 없습니다: {ref.link}")
        return ArticleRef(cafe_id=ref.cafe_id, article_id=ref.article_id, menu_id=ref.menu_id, cafe_url=slug)

    async def _jsonp(self, url: str, params: dict[str, Any], r: ArticleRef) -> Any:
        """like 위젯 <script> JSONP GET [실측 2026-11-13 UI 캡처: Referer 는 게시글 iframe URL]"""
        resp = await self.session.get(
            url,
            params=params,
            kind=RequestKind.SCRIPT,
            referer=endpoints.article_frame_page(r.cafe_id, r.article_id, r.menu_id),
        )
        if resp.status_code >= 400:
            raise api_error_class(resp.status_code, None)(
                f"like 위젯 오류 {resp.status_code}: {url}", resp.status_code, resp.text[:500]
            )
        return parse_jsonp(resp.text, url)

    async def _search(self, r: ArticleRef, cid: str, jq: JsonpState | None = None) -> JSON:
        """route-like search -> 응답 전체 (contents[], guestToken, timestamp)"""
        return as_dict(await self._jsonp(endpoints.LIKE_ROUTE_SEARCH, search_params(cid, jq or JsonpState()), r))

    async def status(self, ref: ArticleRef | str) -> LikeStatus:
        """좋아요 수 / 내가 눌렀는지 -> LikeStatus (.like_count, .liked) [실측 2026-11-13 Camoufox UI 캡처]

        페이지 로드 시 브라우저가 보내는 route-like search 와 같은 요청이다.

        응답 contents[0].reactions[] 에 count / isReacted 가 온다 (로그인 쿠키 기준, isLogin 값과 무관).
        URL 에서 얻은 slug 로 먼저 조회하고, 반응이 비어 있으면(틀린 slug 이거나 좋아요 0개)
        게시글 상세에서 참 slug 를 얻어 다시 조회한다.
        """
        r = await self._client.articles.resolve(ref)
        tried: dict[str, JSON] = {}
        for cid in content_ids(r):
            tried[cid] = content = _first_content(await self._search(r, cid))
            if as_list(content.get("reactions")):
                return LikeStatus.from_api(content, cid)
        true_ref = await self._true_ref(r)
        cid = content_ids(true_ref)[0]
        content = tried[cid] if cid in tried else _first_content(await self._search(true_ref, cid))
        return LikeStatus.from_api(content, cid)

    async def like(self, ref: ArticleRef | str, reaction: ReactionType = ReactionType.LIKE) -> LikeStatus:
        """좋아요 등록 -> 등록 후 LikeStatus (.like_count, .liked) (로그인 필요) [실측 2026-11-13 Camoufox UI 캡처]

        - reaction: 반응 종류 (기본 좋아요). 결과의 reactions 에는 이 반응 하나만 들어 있다.

            st = await cafe.likes.like(ref)
            print(st.like_count, st.liked)     # 1 True
        """
        return await self._react(ref, reaction, "POST")

    async def unlike(self, ref: ArticleRef | str, reaction: ReactionType = ReactionType.LIKE) -> LikeStatus:
        """좋아요 취소 -> 취소 후 LikeStatus (로그인 필요) [실측 2026-11-13 Camoufox UI 캡처]

            st = await cafe.likes.unlike(ref)  # st.liked == False
        """
        return await self._react(ref, reaction, "DELETE")

    async def like_raw(self, ref: ArticleRef | str, reaction: ReactionType = ReactionType.LIKE) -> JSON:
        """like() 와 같지만 서버 JSONP 응답 원본 dict 를 돌려준다 (0.3 의 like() 반환값)"""
        return (await self._react(ref, reaction, "POST")).raw

    async def unlike_raw(self, ref: ArticleRef | str, reaction: ReactionType = ReactionType.LIKE) -> JSON:
        """unlike() 와 같지만 서버 JSONP 응답 원본 dict 를 돌려준다 (0.3 의 unlike() 반환값)"""
        return (await self._react(ref, reaction, "DELETE")).raw

    async def members(
        self, ref: ArticleRef | str, *, per_page: int = 10, next_timestamp: int | None = None
    ) -> LikeMembers:
        """좋아요 누른 멤버 한 페이지 -> LikeMembers (.users, .total_count, .next_timestamp) (로그인 필요)

        [실측 2026-11-13 사람 세션 캡처 + Camoufox UI 캡처] 좋아요/취소 클릭 직후 브라우저가
        gw/v5 likeIt/members?perPage=10 을 호출한다 (XHR, X-Cafe-Product).
        result: {totalCount, nextTimestamp, users[{nick, memberKey, likeItTime, isCafeMember,...}],
                 article{isLikeIt}, cafe{id, name, url(진짜 slug)}}.
        like 서비스 cid 는 이 cafe.url(slug) 기준이다 - 별칭으로 resolve 했으면 여기서 참 slug 확인 가능.
        다음 페이지는 앞 결과의 next_timestamp 를 넘긴다 (전부 받으려면 all_members).
        """
        self._require_login()
        r = await self._client.articles.resolve(ref)
        data = await self.session.get_json(
            endpoints.like_members(r.cafe_id, r.article_id, per_page, next_timestamp),
            headers=dict(endpoints.PRODUCT_HEADERS),  # [실측 2026-11-13] 프론트는 apis/gw XHR 전부에 붙인다
            # [실측 2026-11-13 Camoufox UI 캡처] Referer 는 게시글 iframe URL (예전 f-e 바깥 URL 은 틀림)
            referer=endpoints.article_frame_page(r.cafe_id, r.article_id, r.menu_id),
        )
        return LikeMembers.from_api(dig(data, "result", default={}))

    async def all_members(self, ref: ArticleRef | str, *, per_page: int = 10, max_pages: int = 50) -> list[LikeUser]:
        """좋아요 누른 멤버 전부 -> list[LikeUser] (nextTimestamp 커서 순회, 중복 제거, 로그인 필요)"""
        r = await self._client.articles.resolve(ref)
        out: list[LikeUser] = []
        seen: set[str] = set()
        cursor: int | None = None
        for _ in range(max_pages):
            page = await self.members(r, per_page=per_page, next_timestamp=cursor)
            new = [u for u in page.users if (u.member_key or u.nick) not in seen]
            seen.update(u.member_key or u.nick for u in new)
            out.extend(new)
            if not new or not page.next_timestamp or page.next_timestamp == cursor:
                break
            if page.total_count and len(out) >= page.total_count:
                break
            cursor = page.next_timestamp
        return out

    async def _react(self, ref: ArticleRef | str, reaction: ReactionType, method: str) -> LikeStatus:
        """등록/취소. 틀린 slug 로도 토큰이 발급되므로(실측) 항상 게시글 상세의 참 slug 로 cid 를 만든다

        브라우저처럼 한 화면의 JSONP 상태(콜백 이름 재사용, `_` 증가)로 search -> 등록/취소 순서로 보낸다.
        """
        self._require_login()  # 비로그인 좋아요는 gw 조회 단계(401 0004)에서 막히므로 미리 막는다
        r = await self._true_ref(await self._client.articles.resolve(ref))
        for cid in content_ids(r):
            jq = JsonpState()
            got = await self._guest_token(r, cid, jq)
            if got is None:
                continue  # 토큰 발급 실패
            token, issued_at = got
            data = await self._jsonp(
                endpoints.like_content(cid), react_params(method, reaction, r.cafe_id, token, issued_at, jq), r
            )
            return react_status(data, cid, reaction)
        raise ParseError(f"like 위젯 토큰을 발급받지 못했습니다: {r.link}")

    async def _guest_token(self, r: ArticleRef, cid: str, jq: JsonpState) -> tuple[str, int] | None:
        """like 위젯 토큰 -> (guestToken, timestamp). 콘텐츠가 없으면 None.

        [실측] 등록/취소 요청의 timestamp 는 현재 시각이 아니라 이 search 응답의 timestamp 여야 한다.
        토큰이 발급 시각에 묶여 있어, 다른 값을 보내면 4013 이 온다.
        """
        data = await self._search(r, cid, jq)
        token = str(dig(data, "guestToken") or "")
        issued_at = dig(data, "timestamp")
        if not token or not isinstance(issued_at, int):
            return None
        return token, issued_at


def react_status(data: Any, cid: str, reaction: ReactionType | str = ReactionType.LIKE) -> LikeStatus:
    """등록/취소 JSONP 응답 -> LikeStatus (반응 1개)

    [실측 2026-11-13] 성공 응답 예: {"contentsId": "31547053_deongdion_197", "reactionType": "like",
    "count": 1, "isReacted": true, ...}. count / isReacted 가 없으면 실패로 보고 NaverAPIError [추정: 오류 형식 미확인].
    """
    d = as_dict(data)
    if "count" not in d and "isReacted" not in d:
        code = d.get("code") or d.get("errorCode") or dig(d, "error", "code")
        code_s = str(code) if code not in (None, "") else None
        raise api_error_class(None, code_s)(
            f"좋아요 처리 실패: {cid}" + (f" ({code_s})" if code_s else ""), 200, str(data)[:500], code_s
        )
    return LikeStatus.from_reaction(d, cid, reaction)


def _first_content(data: Any) -> JSON:
    return as_dict(next(iter(as_list(dig(data, "contents"))), None))
