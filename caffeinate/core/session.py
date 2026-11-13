"""
curl_cffi AsyncSession 기반 네이버 세션

브라우저 동일 인식 전략 ([실측 2026-11-13] Camoufox 158 vs 이 세션, tls.peet.ws 필드 단위 비교):
  1) TLS       : curl_cffi 파이어폭스 타겟 + 로그인 브라우저(Camoufox)의 ja3 덮어쓰기
                 -> 전체 핸드셰이크 ClientHello 의 ja3/ja4/peetprint/확장 내용(GREASE 없음, record_size_limit,
                    delegated_credentials, compress_certificate zlib/brotli/zstd, ECH, X25519MLKEM768 키 공유)이 동일.
                 TLS 세션 재개는 끈다(SSL_SESSIONID_CACHE=0): 재개 시 파이어폭스는 session_ticket(35)을 빼고
                 pre_shared_key(41)만 보내지만(17개), BoringSSL 은 35 와 41 을 함께 보내(18개) 파이어폭스에
                 없는 ja4 가 된다. 재개를 끄면 항상 브라우저의 전체 핸드셰이크와 같은 ClientHello.
  2) HTTP/2    : SETTINGS/WINDOW_UPDATE/의사헤더 순서(m,p,a,s) 동일. HEADERS 프레임 PRIORITY weight 는
                 요청 종류별(문서 42, XHR/fetch 22)로 extra_fp 에 지정.
                 내장 caffeinate._curl_cffi (패치한 libcurl-impersonate, core/curl.py) 가 있으면
                 스트림 ID 와 스트림 WINDOW_UPDATE 도 맞춘다 (firefox_h2_options). [실측 2026-11-13]
                 Camoufox 158 -> 로컬 h2 서버(모든 수신 프레임 기록):
                 - 연결의 첫 요청 스트림은 3, 같은 연결의 다음 요청은 5, 7, ... (스트림 1 은 안 씀)
                 - 모든 요청(GET 포함)에서 HEADERS 바로 뒤, DATA 앞에 스트림 WINDOW_UPDATE(12451840
                   = 12 MiB - SETTINGS INITIAL_WINDOW_SIZE 128 KiB). tls.peet.ws 는 GET 이면 HEADERS(END_STREAM)
                   에서 기록을 끝내서 POST 에서만 보인다.
                 - PRIORITY 프레임은 없음
  3) 헤더      : default_headers=False 로 curl 기본 헤더를 끄고 headers.build_headers 가
                 실제 파이어폭스 wire 순서대로 구성 (accept-encoding 도 curl 이 앞에 끼워넣지 않도록 직접 지정)
  4) 쿠키      : curl jar 를 쓰지 않고(discard_cookies) CookieStore 가 파이어폭스 위치에 쿠키별 cookie 헤더 생성.
                 Set-Cookie 는 원본 헤더를 직접 파싱(Expires/Max-Age/기본 Path 보존)
  5) 리다이렉트: 직접 따라가며 hop 마다 쿠키/Fetch Metadata 재계산. [실측 2026-11-13] Camoufox 158 로
                 루프백 페이지 -> hb.cran.dev/redirect-to(301/302/303/307) -> 루프백 에코/tls.peet.ws 측정:
                 - Sec-Fetch-Site 는 체인 누적 (같은 출처로 돌아와도 cross-site)
                 - 교차 출처 hop 을 거치면 Origin 은 "null" (XHR/fetch 는 GET 으로 바뀌어도 보냄,
                   폼 POST 307 문서 이동도 null, 문서 GET 은 Origin 없음) - Fetch 규격 tainted origin
                 - 301/302 POST, 303 은 GET 으로 바뀌고 본문과 content-type/content-length 가 빠짐, 307 은 유지
                 - Referer: 기본 정책이면 같은 출처로 돌아와도 출처만, unsafe-url 이면 마지막 hop 기준
                 - hop 헤더 순서가 첫 요청과 다름 (headers.py 모듈 설명)

  남은 차이:
  - 공식 curl_cffi 로는 첫 스트림 ID(브라우저 3, curl 1)와 스트림 WINDOW_UPDATE 를 못 맞춘다 (내장 확장 필요, 위 2)
  - TLS 세션 재개(PSK)를 안 한다 (위 1 참고)
"""
import asyncio
import functools
import json
import logging
import time
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote, urlencode, urljoin, urlsplit

from ..enums import HttpMethod, ReferrerPolicy, RequestKind, SecFetchSite
from ..models.fingerprint import Fingerprint
from . import fingerprint as fp_mod
from .config import Settings
from .cookies import CookieStore
from .curl import AsyncSession, Curl, CurlError, CurlOpt, RequestException, Response
from .errors import NaverAPIError, NetworkError, api_error_class
from .headers import (
    ACCEPT_ENCODING,
    H2_WEIGHT,
    RequestContext,
    build_headers,
    origin_of,
    sec_fetch_site,
    wire_headers,
    worst_site,
)

logger = logging.getLogger("caffeinate")

_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
# 메서드가 GET 으로 바뀌는 리다이렉트에서 브라우저가 지우는 본문 헤더 (Fetch 규격 request-body-header)
_BODY_HEADERS = frozenset({"content-type", "content-encoding", "content-language", "content-location"})


# 파이어폭스(necko) h2 동작 [실측 2026-11-13] (모듈 설명 2)
FIREFOX_H2_FIRST_STREAM_ID = 3
FIREFOX_H2_STREAM_WINDOW_UPDATE = 12_451_840  # 12 MiB - 128 KiB (SETTINGS INITIAL_WINDOW_SIZE)
_h2_parity_warned = False


@functools.cache
def firefox_h2_options() -> dict[CurlOpt, int]:
    """패치한 libcurl 의 파이어폭스 h2 옵션 (지원 안 하면 빈 dict)

    내장 caffeinate._curl_cffi (native/patches/curl-caffeinate.patch) 는 CurlOpt.HTTP2_INITIAL_STREAM_ID(1900),
    CurlOpt.HTTP2_STREAM_WINDOW_UPDATE(1901) 를 추가한다. 상수가 있어도 libcurl 이 패치 안 된 빌드일 수 있으므로
    (예: 폴백한 공식 curl_cffi) 실제로 setopt 해 보고 쓴다.
    """
    stream_id: CurlOpt | None = getattr(CurlOpt, "HTTP2_INITIAL_STREAM_ID", None)
    window_update: CurlOpt | None = getattr(CurlOpt, "HTTP2_STREAM_WINDOW_UPDATE", None)
    if stream_id is None or window_update is None:
        return {}
    opts = {stream_id: FIREFOX_H2_FIRST_STREAM_ID, window_update: FIREFOX_H2_STREAM_WINDOW_UPDATE}
    try:
        curl = Curl()
        try:
            for opt, value in opts.items():
                curl.setopt(opt, value)
        finally:
            curl.close()
    except CurlError:
        return {}
    return opts


def _log_url(url: str) -> str:
    """로그용 URL (쿼리 제외 - 토큰/식별자 노출 방지)"""
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}{u.path}"


class CafeSession:
    """
    async with CafeSession() as s:
        data = await s.get_json(url, referer=...)
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        fingerprint: Fingerprint | None = None,
        cookies: CookieStore | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.fingerprint = fingerprint or fp_mod.load_or_create(self.settings.fingerprint_file)
        self._cookies_from_file = cookies is None
        self.cookies = cookies if cookies is not None else CookieStore.load(self.settings.cookies_file)
        self._loaded_with_login = self._cookies_from_file and self.cookies.has_login
        self._session: AsyncSession | None = None
        # 요청 간격 (Settings.min_request_interval): 다음 요청을 시작해도 되는 시각(monotonic)
        self._pace_lock: asyncio.Lock | None = None
        self._pace_loop: asyncio.AbstractEventLoop | None = None
        self._next_request_at = 0.0

    # ---------------------------------------------------------------- 수명주기
    async def __aenter__(self) -> Self:
        self._ensure_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    def _ensure_session(self) -> AsyncSession:
        global _h2_parity_warned
        if self._session is None:
            h2_options = firefox_h2_options()
            if not h2_options and not _h2_parity_warned:
                _h2_parity_warned = True
                logger.warning(
                    "내장 curl_cffi 확장이 없어 공식 curl_cffi 로 폴백했습니다. 첫 h2 스트림 ID(3)와 스트림 WINDOW_UPDATE 를 "
                    "브라우저와 맞추지 못합니다. README 의 설치 방법(GitHub Releases 플랫폼 휠)을 참고하세요."
                )
            self._session = AsyncSession(
                impersonate=self.fingerprint.impersonate,  # type: ignore[arg-type]
                ja3=self.fingerprint.ja3,                  # TLS 를 로그인 브라우저와 정확히 일치
                timeout=self.settings.timeout,
                default_headers=False,
                proxy=self.settings.proxy,
                max_clients=self.settings.max_clients,
                # TLS 세션 재개 끔 - 재개 ClientHello 가 파이어폭스와 달라짐 (모듈 설명 1) [실측 2026-11-13]
                # + 내장 확장이면 첫 h2 스트림 ID 3, 요청마다 스트림 WINDOW_UPDATE (모듈 설명 2)
                curl_options={CurlOpt.SSL_SESSIONID_CACHE: 0, **h2_options},
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            finally:
                self._session = None
        # 서버가 갱신한 쿠키 저장. 로그인 쿠키가 있거나, 파일에 있던 로그인 쿠키를 서버가 지운 경우
        # (로그아웃/만료 -> 지난 토큰을 파일에 남기지 않음)에만 저장한다.
        # 처음부터 비로그인이었으면 추적 쿠키만으로 파일을 만들지 않는다.
        if (
            self.settings.autosave_cookies
            and self._cookies_from_file
            and self.cookies.dirty
            and (self.cookies.has_login or self._loaded_with_login)
        ):
            self.cookies.save(self.settings.cookies_file)

    # ---------------------------------------------------------------- 저수준 요청
    async def request(
        self,
        method: HttpMethod | str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: dict[str, Any] | str | bytes | None = None,
        headers: dict[str, str] | None = None,
        referer: str | None = None,
        origin: str | None = None,
        kind: RequestKind = RequestKind.XHR,
        timeout: float | None = None,
        credentials: bool = True,
        referrer_policy: ReferrerPolicy | None = None,
    ) -> Response:
        """브라우저와 같은 모양으로 요청 1회 (리다이렉트는 직접 따라감)

        - referer         : 요청을 일으킨 페이지 URL (전체). Referer 값은 그 페이지 정책으로 계산
        - referrer_policy : 그 페이지의 Referrer-Policy (None: 네이버 페이지 unsafe-url, 그 외 파이어폭스 기본)
        - credentials=False: fetch(credentials: 'omit') 처럼 쿠키를 보내지도 저장하지도 않는다
        """
        method = HttpMethod(str(method).upper())
        session = self._ensure_session()

        content_type: str | None = None
        body: bytes | None = None
        if json_body is not None:
            content_type = "application/json"
            body = json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        elif isinstance(data, dict):
            content_type = "application/x-www-form-urlencoded"
            body = form_encode(data, kind).encode("ascii")
        elif data is not None:
            body = data.encode("utf-8") if isinstance(data, str) else data
        extra = dict(headers or {})
        if "content-type" in {k.lower() for k in extra}:
            content_type = None

        current_url, current_method, current_params = url, method, params
        site: SecFetchSite | None = None
        tainted = False       # Fetch 규격 tainted origin -> Origin: null [실측 2026-11-13]
        cross_chain = False   # referer 와 다른 출처 hop 을 거쳤음 -> Referer 계산에 영향 [실측 2026-11-13]
        for hop in range(self.settings.max_redirects + 1):
            full_url = _with_params(current_url, current_params)
            hop_site = sec_fetch_site(full_url, referer)
            site = hop_site if site is None else worst_site(site, hop_site)
            ctx = RequestContext(
                url=full_url,
                method=current_method,
                kind=kind,
                referer=referer,
                referrer_policy=referrer_policy,
                origin="null" if tainted and origin is None else origin,
                redirected=hop > 0,
                cross_origin_chain=cross_chain,
                content_type=content_type if body is not None else None,
                content_length=len(body) if body is not None else None,
                extra=extra,
                cookie=self.cookies.header_for(full_url) if credentials else None,
                site=site,
            )
            started = time.perf_counter()
            wire: list[tuple[str, str | None]] = list(wire_headers(build_headers(self.fingerprint, ctx)))
            if body == b"" and not any(k == "content-type" for k, _ in wire):
                # [실측 2026-11-13 tls.peet.ws] 본문 없는 POST 에 libcurl 이 content-type 을 덧붙이는 것을 막는다
                # (값 None -> curl 에 "Content-Type:" 로 넘어가 내부 헤더 비활성). 브라우저는 보내지 않는다.
                wire.append(("content-type", None))
            resp = await self._send_with_retry(
                session,
                current_method,
                full_url,
                body,
                wire,
                timeout,
                H2_WEIGHT[kind],
            )
            logger.debug(
                "%s %s -> %s (%.0fms%s)", current_method.value, _log_url(full_url), resp.status_code,
                (time.perf_counter() - started) * 1000, f", 리다이렉트 hop {hop}" if hop else "",
            )
            if credentials:
                self.cookies.update_from_headers(
                    [v for v in resp.headers.get_list("set-cookie") if v], full_url
                )

            location = resp.headers.get("location")
            if resp.status_code not in _REDIRECT_CODES or not location:
                return resp
            next_url = urljoin(full_url, location)
            # Fetch 규격 4.4 HTTP-redirect fetch: 현재 URL 과 다음 URL 의 출처가 다르고, 요청 출처(referer 페이지)가
            # 현재 URL 과 다르면 tainted. 예: 페이지 A -> B(리다이렉트) -> A 는 tainted [실측 2026-11-13]
            if referer and origin_of(next_url) != origin_of(full_url) and origin_of(referer) != origin_of(full_url):
                tainted = True
            if referer and origin_of(full_url) != origin_of(referer):
                cross_chain = True
            # 리다이렉트: 303(HEAD 제외) 및 301/302 POST 는 GET 으로, 본문/본문 헤더 제거 (브라우저 동작)
            if (resp.status_code == 303 and current_method is not HttpMethod.HEAD) or (
                resp.status_code in (301, 302) and current_method is HttpMethod.POST
            ):
                current_method, body, content_type = HttpMethod.GET, None, None
                extra = {k: v for k, v in extra.items() if k.lower() not in _BODY_HEADERS}
            current_url, current_params = next_url, None
        raise NaverAPIError(f"리다이렉트 과다 ({self.settings.max_redirects}회 초과): {url} -> 마지막 {current_url}")

    async def _send_with_retry(
        self,
        session: AsyncSession,
        method: HttpMethod,
        url: str,
        body: bytes | None,
        headers: list[tuple[str, str | None]],
        timeout: float | None,
        h2_weight: int,
    ) -> Response:
        delay = 1.0
        attempts = max(1, self.settings.max_retries)
        last_exc: Exception | None = None
        for attempt in range(attempts):
            await self._pace()
            try:
                resp = await session.request(
                    method.value,  # type: ignore[arg-type]
                    url,
                    data=body,
                    headers=headers,  # type: ignore[arg-type]  # 중복 이름(cookie) 허용 목록
                    timeout=timeout or self.settings.timeout,
                    allow_redirects=False,
                    accept_encoding=ACCEPT_ENCODING,  # 디코딩 활성화 (헤더 위치는 headers 쪽이 우선)
                    discard_cookies=True,
                    extra_fp={"http2_stream_weight": h2_weight},  # HEADERS 프레임 weight [실측 2026-11-13]
                )
            except RequestException as e:
                last_exc = e
                cause = f"{type(e).__name__}: {e}"
            else:
                if resp.status_code != 429 or attempt == attempts - 1:
                    return resp
                cause = "429 Too Many Requests"
            if attempt < attempts - 1:
                logger.debug(
                    "재시도 %d/%d %s %s (%s) - %.1f초 대기", attempt + 1, attempts - 1, method.value,
                    _log_url(url), cause, delay,
                )
                await asyncio.sleep(delay)
                delay *= self.settings.retry_backoff
        raise NetworkError(f"네트워크 오류: {last_exc}") from last_exc

    async def _pace(self) -> None:
        """Settings.min_request_interval 만큼 요청 시작 시각을 벌린다 (0 이면 아무것도 안 함)

        동시 요청(asyncio.gather)도 lock 으로 줄을 세워 시작 시각이 interval 이상 떨어지게 한다.
        요청이 끝나기를 기다리지는 않는다 (응답 대기는 겹칠 수 있음).
        """
        interval = self.settings.min_request_interval
        if interval <= 0:
            return
        loop = asyncio.get_running_loop()
        if self._pace_lock is None or self._pace_loop is not loop:  # 이벤트 루프마다 lock 하나
            self._pace_lock, self._pace_loop = asyncio.Lock(), loop
        async with self._pace_lock:
            # 이벤트 루프 타이머는 시계 해상도만큼 일찍 깰 수 있어 (Windows ~15ms) 남은 시간이 없을 때까지 잔다
            while (wait := self._next_request_at - time.monotonic()) > 0:
                await asyncio.sleep(wait)
            self._next_request_at = time.monotonic() + interval

    # ---------------------------------------------------------------- 편의 메서드
    async def get(self, url: str, **kw: Any) -> Response:
        return await self.request(HttpMethod.GET, url, **kw)

    async def post(self, url: str, **kw: Any) -> Response:
        return await self.request(HttpMethod.POST, url, **kw)

    async def get_json(self, url: str, **kw: Any) -> Any:
        return parse_json(await self.get(url, **kw), url)

    async def post_json(self, url: str, json_body: Any = None, **kw: Any) -> Any:
        return parse_json(await self.post(url, json_body=json_body, **kw), url)

    async def post_form(self, url: str, data: dict[str, Any] | str | None = None, **kw: Any) -> Any:
        """form-urlencoded POST -> JSON"""
        return parse_json(await self.post(url, data=data, **kw), url)

    async def get_html(self, url: str, **kw: Any) -> str:
        kw.setdefault("kind", RequestKind.DOCUMENT)
        resp = await self.get(url, **kw)
        if resp.status_code != 200:
            raise NaverAPIError(f"HTML 요청 실패 ({resp.status_code}) {url}", resp.status_code, resp.text[:500])
        return resp.text


def form_encode(data: dict[str, Any], kind: RequestKind = RequestKind.XHR) -> str:
    """form-urlencoded 본문.

    XHR/fetch: 카페 프론트(axios)는 encodeURIComponent 규칙(공백 %20, !~*'() 비인코딩)으로 만든다
    [실측 2026-11-13 CommentPost/CommentReply UI 캡처: content=hdr%20test%20c2]. 같은 값이라도 공백이
    `+` 면 본문과 content-length 가 달라진다. 문서 이동(HTML 폼 제출)은 공백 `+` (WHATWG 폼 인코딩).
    """
    if kind is RequestKind.DOCUMENT:
        return urlencode(data)
    return urlencode(data, quote_via=quote, safe="!~*'()")


def _with_params(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    return f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"


def parse_json(resp: Response, url: str) -> Any:
    """상태코드/에러코드 검사 후 JSON 반환

    HTTP 400 이상이면 (상태, 본문 에러 코드)로 errors.api_error_class 가 고른 NaverAPIError 하위 클래스
    (NotLoggedInError / ArticleNotFoundError / CafeNotFoundError / PermissionDeniedError / RateLimitedError)를 낸다.
    """
    try:
        data = resp.json()
    except (ValueError, json.JSONDecodeError):
        data = None
    if resp.status_code >= 400:
        code, reason = error_info(data)
        msg = f"API 오류 {resp.status_code}: {url}" + (f" ({code} {reason})" if code or reason else "")
        raise api_error_class(resp.status_code, code)(msg, resp.status_code, resp.text[:500], code)
    if data is None:
        raise NaverAPIError(f"JSON 파싱 실패: {url} ({resp.status_code})", resp.status_code, resp.text[:500])
    return data


def error_info(data: Any) -> tuple[str | None, str | None]:
    """응답 본문 -> (에러 코드, 사유). 스택마다 위치가 다르다 (result / message.error / 최상위 error)"""
    if not isinstance(data, dict):
        return None, None
    res: dict[str, Any] = data["result"] if isinstance(data.get("result"), dict) else data
    msg: dict[str, Any] = data["message"] if isinstance(data.get("message"), dict) else {}
    err: dict[str, Any] = msg["error"] if isinstance(msg.get("error"), dict) else {}
    # editor 스택(apis.cafe.naver.com/editor)은 최상위 error 로 온다 [실측 2026-11-13]
    top_err: dict[str, Any] = data["error"] if isinstance(data.get("error"), dict) else {}
    code = res.get("errorCode") or err.get("code") or top_err.get("errorCode") or res.get("code")
    reason = (
        res.get("reason") or err.get("msg") or top_err.get("message") or res.get("message")
    )
    return (str(code) if code else None), (str(reason) if reason else None)


def ensure_success(data: Any, what: str, url: str = "") -> None:
    """HTTP 200 이지만 본문으로 성공 여부를 알리는 쓰기 응답 검사 (실패면 NaverAPIError 하위 클래스)

    [실측 2026-11-13] 성공 응답: 글 삭제 {"message": {"status": "200", ..., "result": {"msg": "Success"}}},
    댓글 삭제 {"msg": "Success"}.
    """
    if isinstance(data, dict):
        msg = data.get("msg")
        message: dict[str, Any] = data["message"] if isinstance(data.get("message"), dict) else {}
        result = message.get("result")
        if msg is None and isinstance(result, dict):
            msg = result.get("msg")
        if isinstance(msg, str) and msg.lower() == "success":
            return
        code, reason = error_info(data)
        if msg is None and str(message.get("status")) == "200" and not code:
            return
    else:
        code, reason = None, None
    raise api_error_class(None, code)(
        f"{what} 실패{f' ({code} {reason})' if code or reason else ''}: {url}".rstrip(": "),
        200, str(data)[:500], code,
    )
