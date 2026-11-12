"""
전역 설정

경로/타임아웃/재시도 같은 값은 `Settings` 데이터클래스 하나로 묶어서 세션에 주입한다.
기본값은 `Settings()` 그대로 쓰면 되고, 필요한 값만 바꿔서 넘기면 된다.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Final

PACKAGE_DIR: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_DIR: Final[Path] = PACKAGE_DIR / "profile"  # PC별 지문/쿠키 (git 커밋 금지!)

# 카페 웹 페이지 (Referer 기본값)
CAFE_SECTION_HOME: Final = "https://section.cafe.naver.com/ca-fe/home"
CAFE_WEB_ORIGIN: Final = "https://cafe.naver.com"


@dataclass(slots=True, kw_only=True)
class Settings:
    profile_dir: Path = DEFAULT_PROFILE_DIR
    timeout: float = 15.0            # 요청 1회 타임아웃(초)
    max_retries: int = 3             # 429/네트워크 오류 재시도 횟수(총 시도 수)
    retry_backoff: float = 1.5       # 대기 배수 (1초 -> 1.5초 -> 2.25초 ...)
    max_redirects: int = 10
    max_clients: int = 10            # AsyncSession 동시 연결 수
    proxy: str | None = None
    autosave_cookies: bool = True    # 서버가 갱신한 쿠키를 종료 시 cookies.json 에 반영

    @property
    def fingerprint_file(self) -> Path:
        return self.profile_dir / "fingerprint.json"

    @property
    def cookies_file(self) -> Path:
        return self.profile_dir / "cookies.json"

    @property
    def login_profile_dir(self) -> Path:
        """로그인 전용 크롬 사용자 데이터 폴더"""
        return self.profile_dir / "login_chrome"
