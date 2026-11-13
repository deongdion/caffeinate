"""
전역 설정

경로/타임아웃/재시도 같은 값은 `Settings` 데이터클래스 하나로 묶어서 세션에 주입한다.
기본값은 `Settings()` 그대로 쓰면 되고, 필요한 값만 바꿔서 넘기면 된다.

프로필 폴더(쿠키 = 네이버 세션 토큰, 지문, 로그인 브라우저 프로필) 위치 결정 순서:
  1) `Settings(profile_dir=...)` 로 직접 지정
  2) 환경변수 `CAFFEINATE_PROFILE_DIR`
  3) 패키지 폴더 안 `profile/` 가 이미 있거나, 소스 체크아웃(편집 가능 설치 포함)에서 실행 중이면 그 폴더
     (기존 동작 그대로 - 하위 호환)
  4) pip 로 site-packages 에 설치된 경우 사용자 데이터 폴더
     (Windows: %LOCALAPPDATA%\\caffeinate, macOS: ~/Library/Application Support/caffeinate,
      그 밖: $XDG_DATA_HOME/caffeinate 또는 ~/.local/share/caffeinate)
     site-packages 에 세션 토큰을 두면 패키지 재설치/업그레이드 때 지워지고, 쓰기 권한이 없을 수도 있다.
"""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

PACKAGE_DIR: Final[Path] = Path(__file__).resolve().parent.parent
# 패키지 폴더 안 프로필 (소스 체크아웃의 기존 위치). 실제 기본값은 default_profile_dir() 참고.
DEFAULT_PROFILE_DIR: Final[Path] = PACKAGE_DIR / "profile"  # PC별 지문/쿠키 (git 커밋 금지!)
PROFILE_DIR_ENV: Final = "CAFFEINATE_PROFILE_DIR"

# 카페 웹 페이지 (Referer 기본값)
CAFE_SECTION_HOME: Final = "https://section.cafe.naver.com/ca-fe/home"
CAFE_WEB_ORIGIN: Final = "https://cafe.naver.com"


def user_data_dir(app: str = "caffeinate") -> Path:
    """OS 관례에 맞는 사용자 데이터 폴더 (platformdirs 의존 없이 단순 구현)"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return Path(base) / app if base else Path.home() / "AppData" / "Local" / app
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / app


def _installed_as_package() -> bool:
    """site-packages / dist-packages 안에 설치된 패키지로 실행 중인지"""
    return any(part in ("site-packages", "dist-packages") for part in PACKAGE_DIR.parts)


def default_profile_dir() -> Path:
    """Settings.profile_dir 기본값 (모듈 설명의 결정 순서 2~4)"""
    if env := os.environ.get(PROFILE_DIR_ENV, "").strip():
        return Path(env).expanduser()
    if DEFAULT_PROFILE_DIR.exists() or not _installed_as_package():
        return DEFAULT_PROFILE_DIR
    return user_data_dir()


@dataclass(slots=True, kw_only=True)
class Settings:
    """클라이언트 설정. 모든 인자는 키워드 전용: `Settings(timeout=30, proxy="http://...")`"""

    profile_dir: Path = field(default_factory=default_profile_dir)  # str 도 받는다 (Path 로 변환)
    timeout: float = 15.0            # 요청 1회 타임아웃(초)
    max_retries: int = 3             # 429/네트워크 오류 재시도 횟수(총 시도 수)
    retry_backoff: float = 1.5       # 대기 배수 (1초 -> 1.5초 -> 2.25초 ...)
    max_redirects: int = 10
    max_clients: int = 10            # AsyncSession 동시 연결 수
    proxy: str | None = None
    autosave_cookies: bool = True    # 서버가 갱신한 쿠키를 종료 시 cookies.json 에 반영

    # 댓글 2001 ("많은 댓글을 연달아 등록할 수 없어요") 자동 재시도 [실측 2026-11-13]
    comment_retry_max: int = 2                     # 2001 재시도 횟수 (총 시도 = 1 + max)
    comment_retry_delays: tuple[float, ...] = (12.0, 20.0)  # 재시도 직전 대기(초), 부족하면 마지막 값 반복

    def __post_init__(self) -> None:
        # Settings(profile_dir="...") 처럼 문자열을 넘겨도 동작하게 (경로 연산자 / 사용)
        self.profile_dir = Path(self.profile_dir).expanduser()
        if self.timeout <= 0:
            raise ValueError(f"timeout 은 0보다 커야 합니다: {self.timeout}")
        if self.max_retries < 0 or self.max_redirects < 0 or self.comment_retry_max < 0:
            raise ValueError("max_retries / max_redirects / comment_retry_max 는 음수일 수 없습니다")
        if self.max_clients < 1:
            raise ValueError(f"max_clients 는 1 이상이어야 합니다: {self.max_clients}")
        self.comment_retry_delays = tuple(self.comment_retry_delays)

    @property
    def fingerprint_file(self) -> Path:
        return self.profile_dir / "fingerprint.json"

    @property
    def cookies_file(self) -> Path:
        return self.profile_dir / "cookies.json"

    @property
    def login_profile_dir(self) -> Path:
        """로그인 전용 Camoufox 사용자 데이터 폴더 (영구 프로필)"""
        return self.profile_dir / "login_firefox"

    @property
    def browser_preset_file(self) -> Path:
        """PC별로 한 번 고른 Camoufox 기기 프리셋 (로그인 때마다 같은 기기로 보이게)"""
        return self.profile_dir / "camoufox_preset.json"
