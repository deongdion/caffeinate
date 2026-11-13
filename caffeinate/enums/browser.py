"""브라우저 지문 관련 열거형"""
from enum import StrEnum


class BrowserBrand(StrEnum):
    """로그인 브라우저 계열 (패킷 지문도 같은 계열로 맞춘다)"""

    FIREFOX = "Firefox"   # Camoufox (파이어폭스 기반)


class Platform(StrEnum):
    """UA 의 OS"""

    WINDOWS = "Windows"
    MACOS = "macOS"
    LINUX = "Linux"
