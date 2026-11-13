"""
쿠키 저장소

curl 내부 쿠키 jar 를 쓰면 Cookie 헤더가 헤더 맨 앞에 붙고, 직접 넣은 Cookie 헤더와
중복 전송된다 (실측). 그래서 쿠키는 여기서 직접 관리하고 요청마다 Cookie 헤더를
파이어폭스 위치(referer/origin 다음, sec-fetch-* 앞)에 넣는다. 응답의 Set-Cookie 는
update_from_headers 로 원본 헤더를 직접 파싱해 반영한다 (Expires/Max-Age/Path 기본값 보존).

[실측 2026-11-13] 파이어폭스 Cookie 순서: path 긴 것 먼저, 같으면 생성 순. 기존 쿠키를 다시 설정해도
처음 생성 위치를 유지한다 -> dict 삽입 순서 + 교체 시 위치 유지로 같은 순서를 만든다.
"""
import json
import os
from collections.abc import Iterable, Iterator
from http.cookiejar import Cookie as JarCookie
from pathlib import Path
from urllib.parse import urlparse

from ..models.cookie import Cookie

LOGIN_COOKIE_NAMES = ("NID_AUT", "NID_SES")


class CookieStore:
    def __init__(self, cookies: Iterable[Cookie] = ()) -> None:
        self._items: dict[tuple[str, str, str], Cookie] = {}
        self.dirty = False
        for c in cookies:
            self._items[c.key] = c

    def __iter__(self) -> Iterator[Cookie]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def get(self, name: str) -> Cookie | None:
        return next((c for c in self._items.values() if c.name == name), None)

    def set(self, cookie: Cookie) -> None:
        old = self._items.get(cookie.key)
        if old is not None and old.value == cookie.value and old.expires == cookie.expires:
            return
        if cookie.is_expired:
            # 서버가 삭제 지시 (과거 Expires / Max-Age<=0). 빈 값 쿠키는 브라우저처럼 그대로 보관·전송한다.
            if self._items.pop(cookie.key, None) is None:
                return
        else:
            self._items[cookie.key] = cookie
        self.dirty = True

    def remove(self, name: str) -> None:
        for key in [k for k in self._items if k[0] == name]:
            del self._items[key]
            self.dirty = True

    def clear(self) -> None:
        if self._items:
            self._items.clear()
            self.dirty = True

    def header_for(self, url: str) -> str | None:
        """URL 에 보낼 Cookie 헤더 값 (긴 path 우선 - 브라우저 규칙)"""
        matched = [c for c in self._items.values() if c.matches(url)]
        if not matched:
            return None
        matched.sort(key=lambda c: len(c.path), reverse=True)
        return "; ".join(f"{c.name}={c.value}" for c in matched)

    def update_from_headers(self, set_cookies: Iterable[str], request_url: str) -> None:
        """응답의 Set-Cookie 헤더들 반영 (브라우저가 거부할 쿠키는 무시)"""
        for line in set_cookies:
            c = Cookie.from_set_cookie(line, request_url)
            if c is not None:
                self.set(c)

    def update_from_jar(self, jar: Iterable[JarCookie], request_url: str) -> None:
        """curl_cffi Response.cookies.jar (http.cookiejar.Cookie) 반영

        주의: curl_cffi 0.16 의 Response.cookies 는 Expires/Max-Age 를 잃는다 -> update_from_headers 권장.
        """
        host = urlparse(request_url).hostname or ""
        for jc in jar:
            self.set(Cookie.from_jar(jc, request_host=host))

    @property
    def has_login(self) -> bool:
        """로그인 쿠키(NID_AUT + NID_SES)가 있는지 (유효성은 서버 확인 필요)"""
        names = {c.name for c in self._items.values()}
        return all(n in names for n in LOGIN_COOKIE_NAMES)

    # ---- 파일 ----
    def to_list(self) -> list[dict]:
        return [c.to_dict() for c in self._items.values()]

    @classmethod
    def load(cls, path: Path) -> "CookieStore":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(Cookie.from_dict(d) for d in data if isinstance(d, dict))
        except (json.JSONDecodeError, KeyError, OSError):
            return cls()

    def save(self, path: Path) -> None:
        """cookies.json 저장 (세션 토큰이므로 POSIX 에서는 0600 권한)"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self.to_list(), ensure_ascii=False, indent=2)
        if os.name == "posix":
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.chmod(path, 0o600)  # 기존 파일 권한도 좁힌다
        else:
            path.write_text(data, encoding="utf-8")
        self.dirty = False
