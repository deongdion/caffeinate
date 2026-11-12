"""
브라우저 로그인 -> 쿠키 수집

전용 크롬 창(디버그 포트, 전용 프로필)에 네이버 로그인 페이지를 띄우고,
사용자가 로그인하면 CDP Storage.getCookies 로 쿠키를 모아 CookieStore 로 돌려준다.
비밀번호는 다루지 않는다.
"""
import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from curl_cffi import AsyncSession

from ..core.config import Settings
from ..core.cookies import LOGIN_COOKIE_NAMES, CookieStore
from ..core.errors import LoginError
from ..models.cookie import Cookie
from .browser import BrowserExecutable, find_browsers, free_port, launch
from .cdp import CdpClient, wait_for_devtools

LOGIN_URL = "https://nid.naver.com/nidlogin.login"


@dataclass(slots=True, kw_only=True)
class LoginOptions:
    timeout: float = 300.0             # 로그인 대기 최대 시간(초)
    poll_interval: float = 2.0
    port: int | None = None            # 이미 띄운 디버그 브라우저 포트에 붙을 때
    browser: BrowserExecutable | None = None
    headless: bool = False             # 테스트용 (사람이 로그인하려면 False)


def naver_cookies(raw: list[dict]) -> list[Cookie]:
    return [Cookie.from_dict(c) for c in raw if "naver.com" in (c.get("domain") or "")]


def has_login_cookies(cookies: list[Cookie]) -> bool:
    names = {c.name for c in cookies}
    return all(n in names for n in LOGIN_COOKIE_NAMES)


async def collect_cookies(ws_url: str) -> list[Cookie]:
    async with CdpClient(ws_url) as cdp:
        return naver_cookies(await cdp.get_cookies())


async def browser_login(
    settings: Settings | None = None,
    options: LoginOptions | None = None,
    *,
    on_status: Callable[[str], None] = print,
) -> CookieStore:
    """로그인 창을 띄우고 로그인 쿠키가 생길 때까지 대기 -> CookieStore"""
    settings = settings or Settings()
    opt = options or LoginOptions()
    proc = None
    if opt.port:
        port = opt.port
        on_status(f"[1] 기존 브라우저(포트 {port})에 연결합니다 ...")
    else:
        exe = opt.browser or next(iter(find_browsers()), None)
        if exe is None:
            raise LoginError("크롬/엣지/웨일을 찾지 못했습니다. `set` 명령으로 쿠키를 수동 등록하세요.")
        port = free_port()
        on_status(f"[1] {exe.kind} 로그인 창을 띄웁니다 (포트 {port}) ...")
        proc = launch(
            exe, port=port, user_data_dir=settings.login_profile_dir, url=LOGIN_URL, headless=opt.headless
        )

    try:
        async with AsyncSession() as http:
            ws_url = await wait_for_devtools(http, port)
        on_status(f"[2] 로그인 대기 중... (창에서 네이버에 로그인해주세요. 최대 {int(opt.timeout)}초)")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + opt.timeout
        while loop.time() < deadline:
            try:
                cookies = await collect_cookies(ws_url)
            except Exception:  # noqa: BLE001 - 페이지 이동 중/창 닫힘 등 일시 오류는 재시도
                cookies = []
            if has_login_cookies(cookies):
                return CookieStore(cookies)
            await asyncio.sleep(opt.poll_interval)
        raise LoginError("로그인 대기 시간 초과")
    finally:
        if proc is not None:
            proc.terminate()
