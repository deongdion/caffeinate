"""core/cookies.py + models/cookie.py - Set-Cookie 파싱 / 브라우저 순서 / 삭제"""
import time

from caffeinate.core.cookies import CookieStore
from caffeinate.models.cookie import Cookie

URL = "https://cafe.naver.com/ca-fe/cafes/1/articles/2"


def test_set_cookie_attributes() -> None:
    c = Cookie.from_set_cookie("a=1; Domain=.naver.com; Path=/; Max-Age=60; Secure; HttpOnly", URL)
    assert c is not None
    assert c.domain == ".naver.com" and c.path == "/" and c.secure and c.http_only
    assert time.time() < c.expires <= time.time() + 61
    host_only = Cookie.from_set_cookie("b=2", URL)
    assert host_only is not None
    assert host_only.domain == "cafe.naver.com" and host_only.is_session
    assert host_only.path == "/ca-fe/cafes/1/articles"  # RFC 6265 기본 path
    exp = Cookie.from_set_cookie("c=3; expires=Wed, 01 Jan 2031 00:00:00 GMT", URL)
    assert exp is not None and exp.expires > time.time()


def test_set_cookie_rejected() -> None:
    assert Cookie.from_set_cookie("a=1; Domain=evil.com", URL) is None
    assert Cookie.from_set_cookie("a=1; Secure", "http://cafe.naver.com/") is None


def test_store_delete_and_order() -> None:
    s = CookieStore()
    s.update_from_headers(["zz=1; Path=/", "aa=2; Path=/", "pp=3; Path=/api", "zz=9; Path=/"],
                          "https://tls.example/x")
    # [실측] 파이어폭스: path 긴 것 먼저, 같으면 생성 순 (재설정해도 위치 유지)
    assert s.header_for("https://tls.example/api/all") == "pp=3; zz=9; aa=2"
    s.update_from_headers(["zz=; Path=/; Max-Age=0"], "https://tls.example/x")
    assert s.header_for("https://tls.example/api/all") == "pp=3; aa=2"
    s.update_from_headers(["e=; Path=/"], "https://tls.example/x")  # 빈 값 쿠키는 보관
    assert s.get("e") is not None
    assert s.header_for("https://other.example/") is None


def _login_store() -> CookieStore:
    store = CookieStore()
    for name in ("NID_AUT", "NID_SES"):
        c = Cookie.from_set_cookie(f"{name}=v; Domain=.naver.com; Path=/", URL)
        assert c is not None
        store.set(c)
    return store


def test_close_saves_when_server_clears_login(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """파일에 있던 로그인 쿠키를 서버가 지우면 지난 토큰을 남기지 않도록 저장한다"""
    import asyncio

    from caffeinate.core.config import Settings
    from caffeinate.core.session import CafeSession

    settings = Settings(profile_dir=tmp_path)
    _login_store().save(settings.cookies_file)
    s = CafeSession(settings)
    assert s.cookies.has_login
    s.cookies.update_from_headers(["NID_SES=; Domain=.naver.com; Path=/; Max-Age=0"], URL)
    assert not s.cookies.has_login
    asyncio.run(s.close())
    assert not CookieStore.load(settings.cookies_file).has_login


def test_close_does_not_create_file_without_login(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import asyncio

    from caffeinate.core.config import Settings
    from caffeinate.core.session import CafeSession

    settings = Settings(profile_dir=tmp_path)
    s = CafeSession(settings)
    s.cookies.update_from_headers(["track=1; Domain=.naver.com; Path=/"], URL)
    asyncio.run(s.close())
    assert not settings.cookies_file.exists()
