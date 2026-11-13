"""curl_cffi 선택: 내장 caffeinate._curl_cffi 우선, 없으면 설치된 curl_cffi 로 폴백

내장본은 curl_cffi 0.16.3 + 파이어폭스 h2 패치(첫 스트림 ID / 스트림 WINDOW_UPDATE)를 넣은 libcurl-impersonate 를
링크한 cffi 확장이다. 플랫폼 휠(GitHub Releases)에는 들어 있고, 소스 체크아웃이나 순수 파이썬 설치에는 확장
(_wrapper)이 없어 ImportError 가 난다. 그때는 공식 curl_cffi (`pip install caffeinate[fallback]`) 를 쓰고,
h2 패리티 옵션은 session.firefox_h2_options() 가 감지해 끈다 (경고 1회).
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # 타입 검사는 항상 내장본 기준 (폴백 curl_cffi 와 API 동일)
    from .._curl_cffi import AsyncSession, Curl, CurlError, CurlOpt, Response
    from .._curl_cffi.requests.exceptions import RequestException
    from .._curl_cffi.requests.impersonate import BrowserType

    BUNDLED: bool
else:
    try:
        from .._curl_cffi import AsyncSession, Curl, CurlError, CurlOpt, Response
        from .._curl_cffi.requests.exceptions import RequestException
        from .._curl_cffi.requests.impersonate import BrowserType

        BUNDLED = True
    except ImportError:
        try:
            from curl_cffi import AsyncSession, Curl, CurlError, CurlOpt, Response
            from curl_cffi.requests.exceptions import RequestException
            from curl_cffi.requests.impersonate import BrowserType
        except ImportError as e:
            raise ImportError(
                "caffeinate 의 내장 curl_cffi 확장이 없고 curl_cffi 도 설치돼 있지 않습니다. "
                "GitHub Releases 의 플랫폼 휠을 설치하거나 `pip install caffeinate[fallback]` 로 curl_cffi 를 설치하세요."
            ) from e
        BUNDLED = False

__all__ = ["BUNDLED", "AsyncSession", "BrowserType", "Curl", "CurlError", "CurlOpt", "RequestException", "Response"]
