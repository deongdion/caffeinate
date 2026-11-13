"""
curl_cffi AsyncSession 기반 네이버 세션

브라우저 동일 인식 전략 (2026-11-12 실측):
  1) TLS/HTTP2 : curl_cffi 파이어폭스 타겟 + 로그인 브라우저(Camoufox)의 ja3 덮어쓰기
                 [실측 2026-11-13] ja3/ja4/peetprint/akamai 모두 Camoufox 158 과 동일
  2) 헤더      : default_headers=False 로 curl 기본 헤더를 끄고 headers.build_headers 가
                 실제 파이어폭스 wire 순서대로 구성 (accept-encoding 도 curl 이 앞에 끼워넣지 않도록 직접 지정)
  3) 쿠키      : curl jar 를 쓰지 않고(discard_cookies) CookieStore 가 파이어폭스 위치에 Cookie 헤더 생성
  4) 리다이렉트: 직접 따라가며 hop 마다 쿠키/Fetch Metadata 재계산
"""
import asyncio
import json
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlencode, urljoin

from curl_cffi import AsyncSession, Response
from curl_cffi.requests.exceptions import RequestException

from ..enums import HttpMethod, RequestKind
from ..models.fingerprint import Fingerprint
from . import fingerprint as fp_mod
from .config import Settings
from .cookies import CookieStore
from .errors import NaverAPIError, NetworkError, NotLoggedInError
from .headers import ACCEPT_ENCODING, RequestContext, build_headers

_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_LOGIN_ERROR_CODES = frozenset({"0004", "10004"})  # gw/like: 0004 로그인하지 않음, editor: 10004 NaverUser 인증 실패


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
        self._session: AsyncSession | None = None

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
        if self._session is None:
            self._session = AsyncSession(
                impersonate=self.fingerprint.impersonate,  # type: ignore[arg-type]
                ja3=self.fingerprint.ja3,                  # TLS 를 로그인 브라우저와 정확히 일치
                timeout=self.settings.timeout,
                default_headers=False,
                proxy=self.settings.proxy,
                max_clients=self.settings.max_clients,
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            finally:
                self._session = None
        # 서버가 갱신한 쿠키 저장 - 로그인 쿠키가 있을 때만 (비로그인 추적 쿠키로 파일을 만들지 않음)
        if (
            self.settings.autosave_cookies
            and self._cookies_from_file
            and self.cookies.dirty
            and self.cookies.has_login
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
    ) -> Response:
        """credentials=False: fetch(credentials: 'omit') 처럼 쿠키를 보내지도 저장하지도 않는다"""
        method = HttpMethod(str(method).upper())
        session = self._ensure_session()

        content_type: str | None = None
        body: bytes | None = None
        if json_body is not None:
            content_type = "application/json"
            body = json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        elif isinstance(data, dict):
            content_type = "application/x-www-form-urlencoded"
            body = urlencode(data).encode("ascii")
        elif data is not None:
            body = data.encode("utf-8") if isinstance(data, str) else data
        extra = dict(headers or {})
        if "content-type" in {k.lower() for k in extra}:
            content_type = None

        current_url, current_method, current_params = url, method, params
        for _hop in range(self.settings.max_redirects + 1):
            full_url = _with_params(current_url, current_params)
            ctx = RequestContext(
                url=full_url,
                method=current_method,
                kind=kind,
                referer=referer,
                origin=origin,
                content_type=content_type if body is not None else None,
                content_length=len(body) if body is not None else None,
                extra=extra,
                cookie=self.cookies.header_for(full_url) if credentials else None,
            )
            resp = await self._send_with_retry(
                session,
                current_method,
                full_url,
                body,
                build_headers(self.fingerprint, ctx),
                timeout,
            )
            if credentials:
                self.cookies.update_from_jar(resp.cookies.jar, full_url)

            location = resp.headers.get("location")
            if resp.status_code not in _REDIRECT_CODES or not location:
                return resp
            # 리다이렉트: 303 및 301/302 POST 는 GET 으로 (브라우저 동작)
            next_url = urljoin(full_url, location)
            if resp.status_code == 303 or (resp.status_code in (301, 302) and current_method is HttpMethod.POST):
                current_method, body, content_type = HttpMethod.GET, None, None
            current_url, current_params = next_url, None
        raise NaverAPIError(f"리다이렉트 과다: {url}")

    async def _send_with_retry(
        self,
        session: AsyncSession,
        method: HttpMethod,
        url: str,
        body: bytes | None,
        headers: dict[str, str],
        timeout: float | None,
    ) -> Response:
        delay = 1.0
        attempts = max(1, self.settings.max_retries)
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = await session.request(
                    method.value,  # type: ignore[arg-type]
                    url,
                    data=body,
                    headers=headers,
                    timeout=timeout or self.settings.timeout,
                    allow_redirects=False,
                    accept_encoding=ACCEPT_ENCODING,  # 디코딩 활성화 (헤더 위치는 headers 쪽이 우선)
                    discard_cookies=True,
                )
            except RequestException as e:
                last_exc = e
            else:
                if resp.status_code != 429 or attempt == attempts - 1:
                    return resp
            if attempt < attempts - 1:
                await asyncio.sleep(delay)
                delay *= self.settings.retry_backoff
        raise NetworkError(f"네트워크 오류: {last_exc}") from last_exc

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


def _with_params(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    return f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"


def parse_json(resp: Response, url: str) -> Any:
    """상태코드/에러코드 검사 후 JSON 반환"""
    try:
        data = resp.json()
    except (ValueError, json.JSONDecodeError):
        data = None
    if resp.status_code >= 400:
        code, reason = _error_info(data)
        msg = f"API 오류 {resp.status_code}: {url}" + (f" ({code} {reason})" if code or reason else "")
        exc_type = NotLoggedInError if resp.status_code == 401 or code in _LOGIN_ERROR_CODES else NaverAPIError
        raise exc_type(msg, resp.status_code, resp.text[:500], code)
    if data is None:
        raise NaverAPIError(f"JSON 파싱 실패: {url} ({resp.status_code})", resp.status_code, resp.text[:500])
    return data


def _error_info(data: Any) -> tuple[str | None, str | None]:
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
