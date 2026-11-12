"""쿠키 모델"""
import time
from dataclasses import dataclass
from http.cookiejar import Cookie as JarCookie
from typing import Any, Self
from urllib.parse import urlparse


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
