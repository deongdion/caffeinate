"""브라우저 지문 관련 열거형"""
from enum import StrEnum


class BrowserBrand(StrEnum):
    """sec-ch-ua 에 들어가는 브랜드명"""

    CHROME = "Google Chrome"
    EDGE = "Microsoft Edge"


class Platform(StrEnum):
    """sec-ch-ua-platform 값 (따옴표 포함 형식은 Fingerprint 에서 처리)"""

    WINDOWS = "Windows"
    MACOS = "macOS"
    LINUX = "Linux"


class LoginBrowser(StrEnum):
    """로그인용으로 띄울 수 있는 크로미움 계열 브라우저"""

    CHROME = "chrome"
    EDGE = "edge"
    WHALE = "whale"
