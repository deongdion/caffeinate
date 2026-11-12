"""브라우저 지문 모델"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Self

from ..enums import BrowserBrand, Platform

# Chromium GREASE 규칙 (components/embedder_support/user_agent_utils.cc)
# 메이저 버전을 시드로 브랜드 문자열/버전/순서가 결정된다. 랜덤으로 고르면 실제 크롬과 어긋남.
_GREASE_CHARS = (" ", "(", ":", "-", ".", "/", ")", ";", "=", "?", "_")
_GREASE_VERSIONS = ("8", "99", "24")
_ORDERS = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))

DEFAULT_ACCEPT_LANGUAGE = "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"


def greased_sec_ch_ua(major: int, brand: BrowserBrand) -> str:
    """
    실제 크롬과 동일한 sec-ch-ua 생성.
    실측 검증: 157 -> "Not-A.Brand";v="99", "Google Chrome";v="157", "Chromium";v="157"
              133 -> "Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"
              131 -> "Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"
    """
    grease = (
        f"Not{_GREASE_CHARS[major % len(_GREASE_CHARS)]}A"
        f"{_GREASE_CHARS[(major + 1) % len(_GREASE_CHARS)]}Brand"
    )
    brands = [
        (grease, _GREASE_VERSIONS[major % len(_GREASE_VERSIONS)]),
        ("Chromium", str(major)),
        (brand.value, str(major)),
    ]
    order = _ORDERS[major % len(_ORDERS)]
    shuffled: list[tuple[str, str]] = [("", "")] * 3
    for i, pos in enumerate(order):
        shuffled[pos] = brands[i]
    return ", ".join(f'"{b}";v="{v}"' for b, v in shuffled)


@dataclass(frozen=True, slots=True, kw_only=True)
class Fingerprint:
    """
    PC 별 고정 지문.
    - impersonate : curl_cffi TLS/HTTP2 지문 타겟 (예: chrome133a)
    - major       : UA / sec-ch-ua 에 쓰이는 크롬 메이저 버전 (impersonate 와 일치)
    UA / sec-ch-ua 는 저장값이 아니라 major 에서 매번 유도 -> 항상 일관성 유지
    """

    seed_hash: str
    impersonate: str
    major: int
    brand: BrowserBrand = BrowserBrand.CHROME
    platform: Platform = Platform.WINDOWS
    accept_language: str = DEFAULT_ACCEPT_LANGUAGE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ---- 유도 값 ----
    @property
    def user_agent(self) -> str:
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{self.major}.0.0.0 Safari/537.36"
        )
        if self.brand is BrowserBrand.EDGE:
            ua += f" Edg/{self.major}.0.0.0"
        return ua

    @property
    def sec_ch_ua(self) -> str:
        return greased_sec_ch_ua(self.major, self.brand)

    @property
    def sec_ch_ua_platform(self) -> str:
        return f'"{self.platform.value}"'

    @property
    def sec_ch_ua_mobile(self) -> str:
        return "?0"

    # ---- 직렬화 ----
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["brand"] = self.brand.value
        d["platform"] = self.platform.value
        d["created_at"] = self.created_at.isoformat(timespec="seconds")
        # 사람이 보기 편하도록 유도값도 함께 기록 (로드시에는 무시)
        d["user_agent"] = self.user_agent
        d["sec_ch_ua"] = self.sec_ch_ua
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """신규 형식 + 구버전(fingerprint.json: browser/chrome_major/is_edge) 모두 지원"""
        impersonate = d.get("impersonate") or d.get("browser")
        major = d.get("major") or d.get("chrome_major")
        if not impersonate or not major:
            raise ValueError("지문 파일에 impersonate/major 가 없습니다")
        if "brand" in d:
            brand = BrowserBrand(d["brand"])
        else:
            brand = BrowserBrand.EDGE if d.get("is_edge") else BrowserBrand.CHROME
        created = d.get("created_at")
        return cls(
            seed_hash=str(d.get("seed_hash", "")),
            impersonate=str(impersonate),
            major=int(major),
            brand=brand,
            platform=Platform(d.get("platform", Platform.WINDOWS.value)),
            accept_language=str(d.get("accept_language") or DEFAULT_ACCEPT_LANGUAGE),
            created_at=datetime.fromisoformat(created) if created else datetime.now(timezone.utc),
        )

    def describe(self) -> str:
        return (
            f"브라우저   : {self.brand.value} {self.major} ({self.impersonate} TLS 지문)\n"
            f"User-Agent : {self.user_agent}\n"
            f"sec-ch-ua  : {self.sec_ch_ua}\n"
            f"언어       : {self.accept_language}\n"
            f"지문 해시  : {self.seed_hash}"
        )
