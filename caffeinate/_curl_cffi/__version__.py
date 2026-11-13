# caffeinate 내장본: 배포 메타데이터(curl_cffi 패키지)가 없으므로 버전을 고정한다.
__title__ = "curl_cffi"
__description__ = "libcurl ffi bindings for Python, with impersonation support."
__version__ = "0.16.3+caffeinate.1"


def _resolve_curl_version() -> str:
    """Read libcurl version without creating a curl easy handle at import time."""
    from ._wrapper import ffi, lib

    return ffi.string(lib.curl_version()).decode()


__curl_version__ = _resolve_curl_version()
