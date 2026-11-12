"""
PC별 고정 브라우저 지문 생성/로드

- 윈도우 MachineGuid(PC 설치 시 생성되는 고유 값)를 시드로 사용
- 같은 PC -> 항상 같은 지문 (impersonate 타겟, 언어), 다른 PC -> 다른 지문
- profile/fingerprint.json 에 저장 (삭제하거나 force_new 시 재생성)

TLS/HTTP2 는 curl_cffi impersonate 가, UA/sec-ch-ua 는 Fingerprint 가 같은 메이저 버전으로 맞춘다.
"""
import hashlib
import json
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..enums import BrowserBrand
from ..models.fingerprint import Fingerprint

try:
    import winreg
except ImportError:  # 윈도우 외 OS
    winreg = None  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class BrowserTarget:
    impersonate: str
    major: int
    brand: BrowserBrand = BrowserBrand.CHROME


# 윈도우 데스크톱 크롬 계열 후보 (설치된 curl_cffi 가 지원하는 것만 사용)
CANDIDATES: Final[tuple[BrowserTarget, ...]] = (
    BrowserTarget("chrome116", 116),
    BrowserTarget("chrome119", 119),
    BrowserTarget("chrome120", 120),
    BrowserTarget("chrome123", 123),
    BrowserTarget("chrome124", 124),
    BrowserTarget("chrome131", 131),
    BrowserTarget("chrome133a", 133),
    BrowserTarget("chrome136", 136),
    BrowserTarget("chrome142", 142),
    BrowserTarget("chrome145", 145),
    BrowserTarget("chrome146", 146),
    BrowserTarget("chrome150", 150),
)

ACCEPT_LANGUAGE_OPTIONS: Final[tuple[str, ...]] = (
    "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "ko-KR,ko;q=0.9,en;q=0.8",
    "ko-KR,ko;q=0.8,en-US;q=0.7,en;q=0.6",
    "ko-KR",
)


def machine_seed() -> str:
    """PC 고유 시드: 윈도우 MachineGuid, 실패시 호스트명+MAC"""
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
                guid, _ = winreg.QueryValueEx(k, "MachineGuid")
                return str(guid)
        except OSError:
            pass
    return f"{socket.gethostname()}|{uuid.getnode():012x}"


def seed_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def available_targets() -> set[str]:
    """설치된 curl_cffi 가 지원하는 impersonate 타겟"""
    try:
        from curl_cffi.requests.impersonate import BrowserType
    except ImportError:
        return set()
    return {m.value for m in BrowserType}


def _index(hex_part: str, n: int) -> int:
    return int(hex_part, 16) % n


def build(seed: str) -> Fingerprint:
    """시드에서 결정적으로 지문 생성 (최신 절반을 70% 가중)"""
    h = seed_hash(seed)
    usable = available_targets()
    pool = sorted((c for c in CANDIDATES if c.impersonate in usable), key=lambda c: c.major)
    if not pool:
        pool = [CANDIDATES[0]]
    half = max(1, len(pool) // 2)
    weighted = pool[half:] if int(h[:4], 16) % 100 < 70 else pool[:half]
    target = weighted[_index(h[4:12], len(weighted))]
    # h[12:20] 은 구버전에서 GREASE 선택에 쓰던 구간 (이제 메이저 버전으로 결정) - 언어 선택 구간 유지
    lang = ACCEPT_LANGUAGE_OPTIONS[_index(h[20:28], len(ACCEPT_LANGUAGE_OPTIONS))]
    return Fingerprint(
        seed_hash=h[:16],
        impersonate=target.impersonate,
        major=target.major,
        brand=target.brand,
        accept_language=lang,
    )


def save(fp: Fingerprint, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fp.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_or_create(path: Path, *, force_new: bool = False) -> Fingerprint:
    """지문 로드. 없거나 / 다른 PC 에서 만든 것이거나 / 미지원 타겟이면 새로 만들어 저장."""
    h = seed_hash(machine_seed())[:16]
    if not force_new and path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            fp = Fingerprint.from_dict(raw)
            if fp.seed_hash == h and fp.impersonate in available_targets():
                if "impersonate" not in raw or raw.get("sec_ch_ua") != fp.sec_ch_ua:
                    save(fp, path)  # 구버전 형식/잘못된 sec-ch-ua -> 신규 형식으로 갱신
                return fp
        except (ValueError, KeyError, OSError):
            pass
    fp = build(machine_seed())
    save(fp, path)
    return fp
