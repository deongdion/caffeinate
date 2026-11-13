"""
브라우저 지문 생성/로드

로그인은 Camoufox(파이어폭스 기반)로 하고, 패킷 요청은 그 브라우저와 같은 지문을 쓴다.
- TLS   : curl_cffi 파이어폭스 타겟 + 로그인 브라우저의 ja3 로 덮어쓰기
- HTTP2 : curl_cffi 파이어폭스 타겟 (SETTINGS/WINDOW_UPDATE/우선순위가 파이어폭스와 같음)
- UA/언어: 로그인 때 브라우저가 실제로 보낸 값

[실측 2026-11-13 tls.peet.ws] Camoufox 158 vs curl_cffi firefox147:
  akamai(h2) 같음, ja4/peetprint 다름 (158 은 c009/c00a 암호와 ffdhe 256/257 그룹을 뺐다).
  firefox147 + ja3=158 실측값 -> 전체 핸드셰이크의 ja3/ja4/peetprint 와 확장 내용(키 공유 그룹, 서명 알고리즘,
  delegated_credentials, compress_certificate, ALPN h2/http1.1) 모두 같음. Camoufox headless/headed 차이 없음.
  세션 재개 ClientHello 는 다르므로 세션에서 재개를 끈다 (core/session.py 설명 참고).
  Accept-Language 는 Camoufox locale=ko-KR 일 때 "ko-KR,ko;q=0.9" (navigator.languages = [ko-KR, ko]) 실측.
"""
import json
import logging
from pathlib import Path
from typing import Final

from ..models.fingerprint import Fingerprint, firefox_user_agent

# curl_cffi 파이어폭스 타겟 (메이저 버전 순)
IMPERSONATE_TARGETS: Final[tuple[tuple[str, int], ...]] = (
    ("firefox133", 133),
    ("firefox135", 135),
    ("firefox144", 144),
    ("firefox147", 147),
)

# 파이어폭스 메이저 버전별 실제 TLS ClientHello (ja3 문자열) [실측: Camoufox -> tls.peet.ws]
FIREFOX_JA3: Final[dict[int, str]] = {
    158: (
        "771,4865-4867-4866-49195-49199-52393-52392-49196-49200-49171-49172-156-157-47-53,"
        "0-23-65281-10-11-35-16-5-34-18-51-43-13-45-28-27-65037,4588-29-23-24-25,0"
    ),
}
DEFAULT_MAJOR: Final = 158
logger = logging.getLogger("caffeinate")


def available_targets() -> set[str]:
    """설치된 curl_cffi 가 지원하는 impersonate 타겟"""
    try:
        from curl_cffi.requests.impersonate import BrowserType
    except ImportError:
        return set()
    return {m.value for m in BrowserType}


def base_target(major: int) -> str:
    """major 이하에서 가장 가까운 curl_cffi 파이어폭스 타겟 (없으면 가장 오래된 것)"""
    usable = [(t, m) for t, m in IMPERSONATE_TARGETS if t in available_targets()]
    if not usable:
        raise RuntimeError("curl_cffi 에 파이어폭스 impersonate 타겟이 없습니다. curl_cffi 를 업데이트하세요.")
    below = [t for t, m in usable if m <= major]
    return below[-1] if below else usable[0][0]


def ja3_for(major: int) -> str | None:
    return FIREFOX_JA3.get(major)


def from_browser(
    *, user_agent: str, accept_language: str, major: int, ja3: str, source: str = "login"
) -> Fingerprint:
    """로그인 브라우저에서 읽은 값으로 지문 생성"""
    return Fingerprint(
        impersonate=base_target(major),
        ja3=ja3,
        major=major,
        user_agent=user_agent,
        accept_language=accept_language,
        source=source,
    )


def builtin() -> Fingerprint:
    """로그인 전 기본 지문 (내장 실측값의 최신 파이어폭스)"""
    return from_browser(
        user_agent=firefox_user_agent(DEFAULT_MAJOR),
        accept_language="ko-KR,ko;q=0.9",
        major=DEFAULT_MAJOR,
        ja3=FIREFOX_JA3[DEFAULT_MAJOR],
        source="builtin",
    )


def save(fp: Fingerprint, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fp.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_or_create(path: Path, *, force_new: bool = False) -> Fingerprint:
    """지문 로드. 없거나 / 구버전(크롬) 형식이거나 / 미지원 타겟이면 내장 기본값으로 만들어 저장."""
    if not force_new and path.exists():
        try:
            fp = Fingerprint.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if fp.impersonate in available_targets():
                return fp
        except (ValueError, KeyError, OSError):
            pass
    fp = builtin()
    try:
        save(fp, path)
    except OSError as e:  # 읽기 전용 위치 등 - 메모리 지문으로 계속 진행
        logger.warning("지문 파일을 저장하지 못했습니다 (%s): %s - 내장 기본 지문으로 계속합니다", path, e)
    return fp
