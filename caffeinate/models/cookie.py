"""쿠키 모델"""
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from http.cookiejar import Cookie as JarCookie
from typing import Any, Self
from urllib.parse import urlparse


def _parse_expires(value: str) -> float | None:
    try:
        return parsedate_to_datetime(value.strip()).timestamp()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def default_path(url: str) -> str:
    """RFC 6265 5.1.4 기본 path: 요청 경로의 마지막 '/' 앞까지 (Path 속성이 없을 때)"""
    path = urlparse(url).path or "/"
    if not path.startswith("/") or path.count("/") == 1:
        return "/"
    return path[: path.rfind("/")]


@dataclass(slots=True, kw_only=True)
class Cookie:
    name: str
    value: str
    domain: str = ".naver.com"
    path: str = "/"
    expires: float = 0          # epoch 초, 0/음수 = 세션 쿠키
    http_only: bool = False
    secure: bool = False

    @property
    def is_session(self) -> bool:
        return self.expires <= 0

    @property
    def is_expired(self) -> bool:
        return not self.is_session and self.expires < time.time()

    def matches(self, url: str) -> bool:
        """브라우저 규칙(도메인/경로/secure)으로 이 URL 에 보낼 쿠키인지"""
        u = urlparse(url)
        host = (u.hostname or "").lower()
        dom = self.domain.lower()
        if dom.startswith("."):
            ok = host == dom[1:] or host.endswith(dom)
        else:
            ok = host == dom
        if not ok or self.is_expired:
            return False
        if self.secure and u.scheme != "https":
            return False
        req_path = u.path or "/"
        cp = self.path or "/"
        return req_path == cp or req_path.startswith(cp.rstrip("/") + "/") or cp == "/"

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.name, self.domain.lower(), self.path)

    # ---- 변환 ----
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "expires": self.expires,
            "httpOnly": self.http_only,
            "secure": self.secure,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """cookies.json / CDP Storage.getCookies 형식 모두 지원"""
        return cls(
            name=str(d["name"]),
            value=str(d["value"]),
            domain=str(d.get("domain") or ".naver.com"),
            path=str(d.get("path") or "/"),
            expires=float(d.get("expires") or 0),
            http_only=bool(d.get("httpOnly", d.get("http_only", False))),
            secure=bool(d.get("secure", False)),
        )

    @classmethod
    def from_set_cookie(cls, header: str, request_url: str) -> Self | None:
        """Set-Cookie 헤더 한 줄 -> Cookie (브라우저가 거부할 쿠키면 None). RFC 6265 5.2 / 5.3

        curl_cffi 의 Response.cookies 는 SimpleCookie 로 파싱해서 Expires/Max-Age/HttpOnly 를 버리고
        Path 기본값을 '/' 로 둔다 [실측 2026-11-13 curl_cffi 0.16.3 소스]. 그래서 원본 헤더를 직접 파싱한다.
        만료 시각이 과거인 쿠키도 그대로 돌려준다 (CookieStore.set 이 삭제로 처리).
        """
        u = urlparse(request_url)
        host = (u.hostname or "").lower()
        pair, *attrs = header.split(";")
        if "=" not in pair:
            return None  # 이름 없는 쿠키는 파이어폭스도 사실상 쓰지 않는다
        name, value = (x.strip() for x in pair.split("=", 1))
        if not name:
            return None
        domain_attr = ""
        path = ""
        expires: float | None = None
        max_age: float | None = None
        secure = http_only = False
        for a in attrs:
            k, _, v = a.partition("=")
            k, v = k.strip().lower(), v.strip()
            if k == "expires":
                expires = _parse_expires(v)
            elif k == "max-age":
                try:
                    max_age = float(int(v))
                except ValueError:
                    pass
            elif k == "domain":
                domain_attr = v.lstrip(".").lower()
            elif k == "path":
                path = v if v.startswith("/") else ""
            elif k == "secure":
                secure = True
            elif k == "httponly":
                http_only = True
        if domain_attr:
            # 요청 호스트가 Domain 에 속하지 않으면 거부 (브라우저 규칙)
            if host != domain_attr and not host.endswith("." + domain_attr):
                return None
            domain = "." + domain_attr
        else:
            domain = host  # host-only
        if secure and u.scheme != "https":
            return None
        if max_age is not None:  # Max-Age 가 Expires 보다 우선
            exp = time.time() + max_age if max_age > 0 else 1.0  # 0/음수 = 즉시 만료(삭제)
        elif expires is not None:
            exp = expires if expires > 0 else 1.0
        else:
            exp = 0.0  # 세션 쿠키
        return cls(
            name=name, value=value, domain=domain, path=path or default_path(request_url),
            expires=exp, http_only=http_only, secure=secure,
        )

    @classmethod
    def from_jar(cls, c: JarCookie, *, request_host: str = "") -> Self:
        domain = c.domain or ""
        if not domain:
            # 실측: curl_cffi 는 host-only 쿠키(Domain 속성 없음)의 domain 을 빈 값으로 준다
            domain = request_host.lower()
        elif c.domain_specified and not domain.startswith("."):
            domain = "." + domain  # Domain 속성 지정 -> 하위 도메인 공유
        return cls(
            name=c.name,
            value=c.value or "",
            domain=domain,
            path=c.path or "/",
            expires=float(c.expires or 0),
            http_only=bool(c.has_nonstandard_attr("HttpOnly")),
            secure=bool(c.secure),
        )
