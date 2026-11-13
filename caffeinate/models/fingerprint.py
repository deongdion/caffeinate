"""브라우저 지문 모델"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Self

from ..enums import BrowserBrand, Platform

DEFAULT_ACCEPT_LANGUAGE = "ko-KR,ko;q=0.9"   # [실측 2026-11-13] Camoufox locale=ko-KR


def firefox_user_agent(major: int) -> str:
    """윈도우 파이어폭스 UA (Camoufox 158 실측 형식)"""
    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{major}.0) Gecko/20100101 Firefox/{major}.0"


@dataclass(frozen=True, slots=True, kw_only=True)
class Fingerprint:
    """
    패킷 요청이 흉내 낼 브라우저 지문. 로그인 브라우저(Camoufox)와 같아야 한다.

    - impersonate : curl_cffi 기반 타겟 (HTTP2 SETTINGS/헤더 프레임 등). 예: firefox147
    - ja3         : 로그인 브라우저의 실제 TLS ClientHello. impersonate 의 TLS 를 덮어쓴다
                    (curl_cffi 에 같은 버전 타겟이 없어도 TLS 를 정확히 맞추기 위함)
    - user_agent / accept_language : 로그인 때 브라우저가 실제로 보낸 값
    - source      : "login" (로그인 브라우저에서 유도) / "builtin" (내장 기본값)
    """

    impersonate: str
    ja3: str
    major: int
    user_agent: str
    accept_language: str = DEFAULT_ACCEPT_LANGUAGE
    brand: BrowserBrand = BrowserBrand.FIREFOX
    platform: Platform = Platform.WINDOWS
    source: str = "builtin"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def from_login(self) -> bool:
        return self.source == "login"

    # ---- 직렬화 ----
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["brand"] = self.brand.value
        d["platform"] = self.platform.value
        d["created_at"] = self.created_at.isoformat(timespec="seconds")
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """크롬 시절 형식(ja3 없음)은 ValueError -> 호출 측에서 새로 만든다"""
        if not d.get("ja3") or not d.get("impersonate") or not d.get("user_agent"):
            raise ValueError("지문 파일에 ja3/impersonate/user_agent 가 없습니다 (구버전 형식)")
        created = d.get("created_at")
        return cls(
            impersonate=str(d["impersonate"]),
            ja3=str(d["ja3"]),
            major=int(d.get("major") or 0),
            user_agent=str(d["user_agent"]),
            accept_language=str(d.get("accept_language") or DEFAULT_ACCEPT_LANGUAGE),
            brand=BrowserBrand(d.get("brand", BrowserBrand.FIREFOX.value)),
            platform=Platform(d.get("platform", Platform.WINDOWS.value)),
            source=str(d.get("source") or "builtin"),
            created_at=datetime.fromisoformat(created) if created else datetime.now(timezone.utc),
        )

    def describe(self) -> str:
        return (
            f"브라우저   : {self.brand.value} {self.major} (출처: {self.source})\n"
            f"TLS        : {self.impersonate} + ja3 덮어쓰기\n"
            f"User-Agent : {self.user_agent}\n"
            f"언어       : {self.accept_language}"
        )
