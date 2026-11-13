"""
브라우저 로그인 (Camoufox) -> 쿠키 + 지문 수집

두 가지 모드:

- 수동 모드(기본): 전용 Camoufox 창(영구 프로필, PC별 고정 기기 프리셋)에 네이버
  로그인 페이지를 띄우고, 사용자가 로그인하면 쿠키를 모은다. 비밀번호는 다루지 않는다.

- 자동 모드(LoginOptions.username/password 지정): 사람처럼 타이핑해서 직접 로그인한다.
  네이버 로그인 페이지는 id/pw 필드의 keydown(keyCode) 타이밍과 값 변화를 감시하고,
  submit 때 행동 기반 토큰(wtoken)을 계산해 붙인다 [2026-11 login.js 실측].
  page.fill() 처럼 값이 한 번에 바뀌면 이 감시에 걸리므로, 실제 키 이벤트로 한 글자씩
  랜덤 지연을 두고 입력한다.

  "로그인 상태 유지"를 항상 체크해서 제출한다 (nvlong=on -> NID_AUT 만료 연장).

  자동 모드에서는 클릭 이후 화면 변화(URL/제목/본문 시그니처)를 계속 추적해서 분류/보고한다
  (2차 인증/캡차/기기 등록/보호모드/이용정지 등 - 서버가 별도 템플릿을 렌더링하므로,
   알려진 마커는 분류하고 모르는 화면은 URL/제목/본문을 그대로 보고한다):

    - ncaptcha 챌린지    : headed 면 창에서 풀 때까지 대기(풀면 자동 이어짐), headless 면 오류
    - 2차 인증(QR/SMS/앱): 안내 후 계속 대기 - 인증을 완료하면 로그인이 자동으로 이어진다
    - 기기 등록/새 기기  : 안내 후 중단 (수동 로그인 한 번이면 영구 프로필에 기억됨)
    - 보호모드/이용정지  : 화면 내용과 함께 즉시 오류
    - 자격증명 오류      : 서버 오류 메시지를 읽어 즉시 오류
    - 그 외 화면        : URL/제목/본문 일부를 보고 (타임아웃 시 마지막 화면 표시)

  debug=True 면 폴링마다 페이지 상태를 [D] 라인으로 전부 덤프한다 (미지 화면 실측용).

같은 브라우저가 실제로 보낸 요청에서 UA / Accept-Language 를 읽고, TLS(ja3)는
버전별 실측값(core.fingerprint.FIREFOX_JA3)을 쓴다. 표에 없는 버전이면 tls.peet.ws 로 실측한다.
이 값으로 만든 지문을 쿠키와 함께 저장해서, 이후 패킷 요청이 로그인한 브라우저와 같게 보이게 한다.

필요: pip install camoufox && python -m camoufox fetch
"""
import asyncio
import json
import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core import fingerprint as fp_mod
from ..core.config import Settings
from ..core.cookies import CookieStore
from ..core.errors import LoginError
from ..models.cookie import Cookie
from ..models.fingerprint import Fingerprint

LOGIN_URL = "https://nid.naver.com/nidlogin.login"
TLS_PROBE_URL = "https://tls.peet.ws/api/clean"
_FIREFOX_MAJOR = re.compile(r"Firefox/(\d+)")

# 로그인 페이지 DOM [2026-11 실측, V3_DESKTOP_DEFAULT 템플릿]
_ID_FIELD = "#id"
_PW_FIELD = "#pw"
_LOGIN_BUTTON_VISIBLE = "#loginBtn_row:visible, #loginBtn_column:visible"
_STAY_CHECKBOX = "#loginStay"
_STAY_LABEL_TEXT = "로그인 상태 유지"

# nid.naver.com 에서 나올 수 있는 화면 분류 마커 [2026-11 실측].
# 2차 인증류: 계속 대기 (인증 완료 -> 로그인 자동 이어짐) [실측: 알림 승인형 화면]
_AUTH_MARKERS = ("2단계", "인증번호", "QR", "OTP", "휴대폰", "알림 발송", "설정한 기기", "본인 확인", "본인확인")
# 자격증명 오류 [2026-11 실측: 존재하지 않는 아이디/틀린 비밀번호 모두 동일 문구,
#   .form_message.error = "아이디 또는 비밀번호가 올바르지 않습니다. 입력한 정보를 다시 확인해 주세요."]
# 계정 상태 화면 URL [2026-11 실측: 익명 접근 200 - 경로 실존 확인]
_PROTECTION_PATH = "/user2/help/idSafetyRelease"   # 보호모드(아이디 보호) 화면
_RESTRICTION_PATH = "/user2/help/idRelease"        # 로그인 제한(본인 확인 필요) 화면
# 아래 본문 마커는 레퍼런스 프로젝트 기준 [미검증] - URL 이 1차 판정, 본문은 보조
_PROTECTION_TEXT = "회원님의 아이디를 보호하고 있습니다."
_BANNED_TEXT = "영구제한"
_RESTRICTION_TEXT = "로그인 제한 해제"
# 구버전 V2 캡차(#captchaimg/#chptcha)는 기본 템플릿에 없음 [실측] - 실패 반복 시 등장 가능성, 감지만 함
# 기본 로그인 폼 판별용: 2FA 화면도 frmNIDLogin 을 재사용하므로 폼 존재만으론 판단 불가 [실측]
_FORM_BODY_MARKER = "아이디 또는 전화번호"


@dataclass(slots=True, kw_only=True)
class LoginOptions:
    timeout: float = 300.0             # 로그인 대기 최대 시간(초, 2차 인증 대기 포함)
    poll_interval: float = 2.0
    headless: bool = False             # 사람이 보려면 False
    locale: str = "ko-KR"
    probe_tls: bool = True             # ja3 실측값이 없는 버전이면 tls.peet.ws 로 실측
    debug: bool = False                # 폴링마다 페이지 상태 [D] 덤프 (미지 화면 실측용)
    # ---- 자동 입력 (둘 다 지정해야 자동 모드) ----
    username: str | None = None
    password: str | None = None
    type_delay_ms: tuple[float, float] = (35.0, 150.0)  # 글자 사이 랜덤 지연 범위
    humanize: bool = True              # Camoufox 커서 이동 humanize (마우스 궤적)


@dataclass(slots=True, kw_only=True)
class LoginResult:
    cookies: CookieStore
    fingerprint: Fingerprint


def naver_cookies(raw: list[Any]) -> list[Cookie]:
    return [Cookie.from_dict(dict(c)) for c in raw if "naver.com" in (c.get("domain") or "")]


def load_preset(path: Path) -> dict[str, Any]:
    """PC별 고정 기기 프리셋 (없으면 윈도우 실기기 프리셋을 하나 골라 저장)"""
    if path.exists():
        try:
            preset = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(preset, dict) and preset:
                return preset
        except (ValueError, OSError):
            pass
    from camoufox.fingerprints import get_random_preset

    preset = get_random_preset(os="windows")
    if not preset:
        raise LoginError("Camoufox 기기 프리셋을 찾지 못했습니다. camoufox 를 업데이트하세요.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preset, ensure_ascii=False, indent=2), encoding="utf-8")
    return preset


async def _probe_ja3(page: Any) -> str:
    resp = await page.goto(TLS_PROBE_URL)
    data = json.loads(await resp.text()) if resp else {}
    ja3 = str(data.get("ja3") or "")
    if not ja3:
        raise LoginError("TLS 지문(ja3) 실측 실패")
    return ja3


# ---------------------------------------------------------------- 자동 입력

async def _type_like_human(page: Any, field: str, text: str, opt: LoginOptions) -> None:
    """클릭 후 실제 키 이벤트로 한 글자씩, 랜덤 지연으로 입력.

    page.fill()/JS 값 설정은 값이 한 번에 바뀌어 행동 수집기(키 타이밍 + 값 변화 감시)에
    걸리고, wtoken 행동 점수를 낮춘다. Playwright 키 이벤트는 브라우저 입력 파이프라인을
    거치는 trusted 이벤트라서 isTrusted 체크도 통과한다.
    """
    loc = page.locator(field)
    await loc.click()
    await asyncio.sleep(random.uniform(0.15, 0.4))
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Delete")
    lo, hi = opt.type_delay_ms
    for ch in text:
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(lo, hi) / 1000.0)


async def _check_stay_signed_in(page: Any, on_status: Callable[[str], None]) -> None:
    """"로그인 상태 유지" 체크 (nvlong=on 으로 제출 -> NID_AUT 만료 연장). 필수 옵션."""
    from playwright.async_api import Error as PlaywrightError

    try:
        stay = page.locator(_STAY_CHECKBOX)
        if await stay.count() == 0:
            on_status("[참고] 로그인 상태 유지 체크박스를 찾지 못했습니다 (템플릿 확인 필요)")
            return
        if await stay.is_checked():
            return
        label = page.get_by_text(_STAY_LABEL_TEXT, exact=True).first
        await label.click()
        if not await stay.is_checked():
            await stay.evaluate("el => el.click()")   # 라벨 클릭이 안 먹는 템플릿 폴백
        on_status("[참고] 로그인 상태 유지: ON")
    except PlaywrightError as e:
        on_status(f"[참고] 로그인 상태 유지 체크 실패(계속 진행): {type(e).__name__}: {e}")


async def _auto_fill_and_submit(page: Any, opt: LoginOptions, on_status: Callable[[str], None]) -> None:
    """자격증명 입력 -> 로그인 상태 유지 체크 -> 클릭. 결과 판정은 폴링 루프에서 한다."""
    on_status("[1-2] 자격증명을 입력합니다 ...")
    await page.wait_for_selector(_ID_FIELD, timeout=15000)   # 로그인 폼 준비 (버튼은 row/column 이 하나만 보임)
    await asyncio.sleep(random.uniform(0.5, 1.2))
    assert opt.username and opt.password  # 호출 측에서 보장
    await _type_like_human(page, _ID_FIELD, opt.username, opt)
    await asyncio.sleep(random.uniform(0.6, 1.4))
    await _type_like_human(page, _PW_FIELD, opt.password, opt)
    await asyncio.sleep(random.uniform(0.3, 0.8))

    await _check_stay_signed_in(page, on_status)
    await asyncio.sleep(random.uniform(0.3, 0.8))

    on_status("[1-3] 로그인 버튼을 클릭합니다 ...")
    btn = page.locator(_LOGIN_BUTTON_VISIBLE).first   # 보이는 쪽(row 또는 column)
    await btn.click()


# ---------------------------------------------------------------- 화면 상태 분류

_PAGE_STATE_JS = """
() => {
  const vis = (el) => !!el && el.getClientRects().length > 0;
  const errors = Array.from(document.querySelectorAll('.form_message.error'))
    .filter(vis).map((el) => (el.textContent || '').trim()).filter(Boolean);
  const challenge = Array.from(
    document.querySelectorAll('[id^="ncaptcha-iframe"], [class*="captcha" i], #captchaimg, #chptcha')
  ).some(vis) || location.href.indexOf('rcaptcha') !== -1;
  const inputs = Array.from(document.querySelectorAll('input'))
    .filter(vis).map((el) => el.type + ':' + (el.id || el.name || '?')).slice(0, 12);
  return {
    url: location.href,
    path: location.pathname,
    onNid: location.hostname === 'nid.naver.com',
    hasForm: !!document.getElementById('frmNIDLogin'),
    error: errors.join(' / '),
    challenge,
    inputs,
    title: document.title || '',
    bodyText: (document.body ? document.body.innerText : '').slice(0, 1500),
  };
}
"""


async def _page_state(page: Any) -> dict[str, Any]:
    """페이지 현재 상태 (네비게이션 도중 등 evaluate 실패 시 빈 dict)"""
    from playwright.async_api import Error as PlaywrightError

    try:
        return dict(await page.evaluate(_PAGE_STATE_JS))
    except PlaywrightError:
        return {}


def _screen_text(state: dict[str, Any]) -> str:
    """상태 보고용 한 줄 (URL | 제목 | 본문 첫 줄)"""
    body = " ".join(str(state.get("bodyText", "")).split())
    title = str(state.get("title", "")).strip()
    parts = [str(state.get("url", "")).strip(), title, body[:120]]
    return " | ".join(p for p in parts if p)


def _classify_state(state: dict[str, Any]) -> str:
    """화면 분류: challenge / protected / restricted / banned / auth / form / other

    2FA 화면도 frmNIDLogin 을 재사용하므로 hasForm 만으론 폼을 판단하지 않는다.
    본문에 로그인 폼 고유 문구("아이디 또는 전화번호")가 있을 때만 form 으로 본다.
    """
    if state.get("challenge"):
        return "challenge"
    path = str(state.get("path", ""))
    if _PROTECTION_PATH in path:
        return "protected"
    if _RESTRICTION_PATH in path:
        return "restricted"
    text = f"{state.get('title', '')} {state.get('bodyText', '')}"
    if _BANNED_TEXT in text:
        return "banned"
    if _PROTECTION_TEXT in text:
        return "protected"
    if _RESTRICTION_TEXT in text:
        return "restricted"
    if state.get("hasForm") and _FORM_BODY_MARKER in str(state.get("bodyText", "")):
        return "form"
    if any(m in text for m in _AUTH_MARKERS):
        return "auth"
    return "other"


# ---------------------------------------------------------------- 로그인

async def browser_login(
    settings: Settings | None = None,
    options: LoginOptions | None = None,
    *,
    on_status: Callable[[str], None] = print,
) -> LoginResult:
    """로그인 창을 띄우고 로그인 쿠키가 생길 때까지 대기 -> 쿠키 + 지문

    options.username/password 가 둘 다 있으면 자동 입력 모드로 동작한다.
    """
    try:
        from camoufox.async_api import AsyncCamoufox
        from playwright.async_api import BrowserContext
    except ImportError as e:
        raise LoginError("camoufox 가 없습니다: pip install camoufox && python -m camoufox fetch") from e

    settings = settings or Settings()
    opt = options or LoginOptions()
    auto = bool(opt.username) and bool(opt.password)
    launch: dict[str, Any] = {
        "persistent_context": True,
        "user_data_dir": str(settings.login_profile_dir),
        "headless": opt.headless,
        "os": "windows",
        "locale": opt.locale,
        "fingerprint_preset": load_preset(settings.browser_preset_file),
    }
    if opt.humanize:
        launch["humanize"] = True
    if settings.proxy:
        launch["proxy"] = {"server": settings.proxy}   # 패킷 요청과 같은 출구 IP

    on_status("[1] Camoufox 로그인 창을 띄웁니다 ...")
    phase = "Camoufox 런치"
    try:
        async with AsyncCamoufox(**launch) as ctx:
            if not isinstance(ctx, BrowserContext):
                raise LoginError("Camoufox 영구 컨텍스트가 아닙니다")
            phase = "로그인 페이지 로드"
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()

            resp = await page.goto(LOGIN_URL)
            if resp is None:
                raise LoginError("로그인 페이지를 열지 못했습니다")
            sent = await resp.request.all_headers()   # 브라우저가 실제로 보낸 헤더
            user_agent = sent.get("user-agent", "")
            m = _FIREFOX_MAJOR.search(user_agent)
            if not m:
                raise LoginError(f"파이어폭스 UA 가 아닙니다: {user_agent}")
            major = int(m.group(1))
            ja3 = fp_mod.ja3_for(major)
            if ja3 is None:
                if not opt.probe_tls:
                    raise LoginError(f"Firefox {major} 의 ja3 실측값이 없습니다 (probe_tls=True 로 실측)")
                on_status(f"[1-1] Firefox {major} TLS 지문을 실측합니다 ...")
                ja3 = await _probe_ja3(page)
                await page.goto(LOGIN_URL)
            fp = fp_mod.from_browser(
                user_agent=user_agent,
                accept_language=sent.get("accept-language", "ko-KR,ko;q=0.9"),
                major=major,
                ja3=ja3,
            )

            if auto:
                phase = "자동 입력"
                await _auto_fill_and_submit(page, opt, on_status)

            phase = "로그인 결과 대기"
            on_status(f"[2] 로그인 결과를 확인합니다 (최대 {int(opt.timeout)}초)" + (" [debug]" if opt.debug else ""))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + opt.timeout
            last_seen: dict[str, Any] = {}
            reported_sig: tuple[Any, ...] | None = None
            next_beat = loop.time() + 45.0
            while loop.time() < deadline:
                try:
                    store = CookieStore(naver_cookies(list(await ctx.cookies())))
                except Exception as e:
                    raise LoginError("로그인 창이 닫혔습니다") from e
                if store.has_login:
                    on_status("[3] 로그인 쿠키 확인 완료 (로그인 상태 유지로 저장됨)")
                    return LoginResult(cookies=store, fingerprint=fp)

                if auto:
                    state = await _page_state(page)
                    if opt.debug:
                        if state:
                            on_status(
                                "[D] "
                                f"form={state.get('hasForm')} err={bool(state.get('error'))} "
                                f"cap={state.get('challenge')} inputs={state.get('inputs')} "
                                f"url={str(state.get('url'))[:80]} title={str(state.get('title'))[:40]}"
                            )
                        else:
                            on_status("[D] 상태 evaluate 실패 (네비게이션 중)")
                    if state:
                        last_seen = state
                        if state.get("error"):
                            raise LoginError(f"로그인 실패: {state['error']} ({_screen_text(state)})")
                        kind = _classify_state(state)
                        # 시그니처에 본문 앞부분 포함: URL/제목이 같아도 내용이 바뀌면 보고한다
                        sig = (state.get("url"), state.get("title"), str(state.get("bodyText", ""))[:80])
                        if sig != reported_sig:
                            reported_sig = sig
                            if kind == "challenge":
                                if opt.headless:
                                    raise LoginError(
                                        "ncaptcha 챌린지가 떴습니다. headless 로는 풀 수 없습니다."
                                        " headless=False 로 다시 실행해 창에서 풀어주세요."
                                    )
                                on_status(f"[캡차] 챌린지 감지: {_screen_text(state)}")
                                on_status("       창에서 풀어주세요 - 풀면 자동으로 이어집니다.")
                            elif kind == "auth":
                                on_status(f"[2차 인증] 화면 감지: {_screen_text(state)}")
                                if "알림 발송" in str(state.get("bodyText", "")) or "설정한 기기" in str(state.get("bodyText", "")):
                                    on_status("       휴대폰 네이버 앱에서 인증 알림을 승인하면 자동으로 이어집니다.")
                                    on_status("       (승인한 브라우저는 다음부터 2단계 인증 없이 로그인됩니다. 안 오면 창에서 '알림 다시 보내기' 또는 OTP 이용)")
                                else:
                                    on_status("       휴대폰/앱에서 인증을 완료하면 자동으로 이어집니다.")
                            elif kind in ("protected", "restricted", "banned"):
                                label = {"protected": "보호모드(아이디 보호)", "restricted": "로그인 제한(본인 확인 필요)",
                                         "banned": "영구제한"}[kind]
                                raise LoginError(
                                    f"[{label}] 로그인할 수 없는 상태입니다. 본인 인증/해제 후 다시 시도하세요.\n"
                                    f"  화면: {_screen_text(state)}"
                                )
                            else:
                                on_status(f"[상태] {_screen_text(state)}")
                    if loop.time() >= next_beat:
                        next_beat = loop.time() + 45.0
                        cur = _screen_text(last_seen) if last_seen else "로그인 폼"
                        on_status(f"[대기] 남은 시간 {int(deadline - loop.time())}초 - 현재 화면: {cur}")

                await asyncio.sleep(opt.poll_interval)
            detail = _screen_text(last_seen) if last_seen else "로그인 폼에서 진행 없음"
            raise LoginError(f"로그인 대기 시간 초과 - 마지막 화면: {detail}")
    except LoginError:
        raise
    except Exception as e:
        if phase == "Camoufox 런치":
            # 브라우저/자식 프로세스가 아예 뜨지 못하는 환경 (보안 소프트웨어, 샌드박스 등)
            raise LoginError(
                f"Camoufox 를 띄우지 못했습니다: {type(e).__name__}: {e}\n"
                "  - python -m camoufox fetch 로 브라우저가 받아져 있는지 확인\n"
                "  - 백신/샌드박스가 camoufox.exe 자식 프로세스 생성을 막지 않는지 확인"
            ) from e
        raise LoginError(f"자동 로그인 실패 [{phase}]: {type(e).__name__}: {e}") from e
