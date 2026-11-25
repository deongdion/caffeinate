"""카페 만들기 모델 [실측 2026-11-24 Whale 캡처 + web-section 프론트 번들]

- CafeCreateOptions : 사용자가 정하는 입력 (기본값은 개설 화면 기본값을 따른다)
- CreationInfo      : 개설 화면을 열 때 받는 값 (주제 목록, 캡차 키, clubTempId, alimCode)
- CaptchaChallenge  : 풀어야 할 캡차 1개
- CreatedCafe       : 만들어진 카페
"""
import re
from dataclasses import dataclass, field
from typing import Any, Self

from ..core.errors import CafeValidationError
from ..enums import CafeFormField, CafeOpenType, CaptchaType, ThemeDirectory, ValidationResult
from ..utils.parsing import JSON, as_dict, as_int, as_list

# 개설 화면 입력 제한 (프론트 maxByte / maxSize) [번들: j=60, S=20, L=20, B=100, keyword maxSize 10]
MAX_NAME_BYTES = 60
MAX_URL_BYTES = 20
MAX_INTRODUCTION_BYTES = 100
MAX_KEYWORD_BYTES = 20
MAX_KEYWORDS = 10
# 프론트가 create-cafes 에 늘 넣는 값 (P() 의 groupId:999) [번들, 실측 2026-11-24 캡처 동일]
CREATE_GROUP_ID = 999

# [실측 2026-11-24] "-" "_" 는 INVALIDCHARACTER. 대문자 허용 여부는 미확인 -> 소문자로 바꿔 보낸다 [추정]
_RE_CAFE_URL = re.compile(r"^[a-z0-9]+$")


def naver_byte_len(text: str) -> int:
    """개설 화면이 세는 바이트 수: 코드 단위가 128 을 넘으면 2, 아니면 1 [번들 getByte]

    (JS 문자열 길이 기준이라 이모지 같은 서로게이트 쌍은 2 x 2 = 4)
    """
    return sum(
        (2 if ord(ch) > 128 else 1) * (2 if ord(ch) > 0xFFFF else 1)
        for ch in text
    )


def _check_bytes(f: CafeFormField, value: str, limit: int) -> None:
    if not value:
        raise CafeValidationError(f"{f.value} 이(가) 비어 있습니다", field=f.value, value=value, result="ISEMPTY")
    if naver_byte_len(value) > limit:
        raise CafeValidationError(
            f"{f.value} 이(가) {limit}바이트를 넘습니다 ({naver_byte_len(value)}바이트): {value!r}",
            field=f.value, value=value, result=ValidationResult.BYTE.value,
        )


@dataclass(slots=True, kw_only=True)
class CafeCreateOptions:
    """카페 만들기 입력. `name` 만 필수이고 나머지는 개설 화면 기본값을 따른다.

        CafeCreateOptions(name="온울", url="onoulapp", theme=ThemeDirectory.TRAVEL, sub_theme=192,
                          introduction="패키지, 항공권, 숙소 B2B서비스", keywords=["패키지", "항공권"])

    - name            : 카페 이름 (clubName, 60바이트 이하)
    - url             : 카페 주소 slug (clubUrl, 영문 소문자+숫자, 20바이트 이하). None 이면 서버 무작위 주소
    - theme           : 주제 대분류 (currentThemeDir). 기본 생활
    - sub_theme       : 주제 소분류 ID (currentThemeDir2). None 이면 대분류의 첫 소분류를 조회해서 쓴다
    - introduction    : 카페 소개 (100바이트 이하). None 이면 카페 이름
    - keywords        : 검색 키워드 (최대 10개, 각 20바이트 이하). 중복은 순서대로 한 번만
    - open_type       : 공개/가입 방식 (기본 OPEN = 공개 + 바로 가입)
    - use_real_name   : 실명 가입만 허용 (useName Y/N). 바로 가입(OPEN)에서는 쓸 수 없다
    - open_member_list: 멤버 목록 공개 (기본 False - 개설 화면 기본값)
    - region_code     : 지역 코드 (rcode). 공개 카페만. `cafe.cafes.regions()` 의 Region.code ("06290" 대구 달서구)
                        [실측 2026-11-24: 만든 카페 관리 설정의 regionCodeDetail.rcode 로 반영 확인]
    - 비공개(HIDDEN) 카페는 서버가 theme/sub_theme/introduction 을 버린다 (관리 설정 주제 -1, 소개 "") [실측 2026-11-24]
    - agree_to_privacy_policy: 개인정보 수집·이용 동의 (기본 True - create() 를 부르는 것이 동의)
    """

    name: str
    url: str | None = None
    theme: ThemeDirectory | int = ThemeDirectory.LIFE
    sub_theme: int | None = None
    introduction: str | None = None
    keywords: list[str] | tuple[str, ...] = ()
    open_type: CafeOpenType = CafeOpenType.OPEN
    use_real_name: bool = False
    open_member_list: bool = False
    region_code: str | None = None
    agree_to_privacy_policy: bool = True

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if self.url is not None:
            self.url = self.url.strip().lower() or None
        if self.introduction is not None:
            self.introduction = self.introduction.strip()
        self.open_type = CafeOpenType(self.open_type)
        if isinstance(self.keywords, str):  # "항공권" 이 글자 단위로 쪼개지지 않게
            self.keywords = (self.keywords,)
        # 공백 제거 + 빈 값 제거 + 중복 제거 (순서 유지)
        self.keywords = tuple(dict.fromkeys(k.strip() for k in self.keywords if k and k.strip()))
        self.check()

    @property
    def effective_introduction(self) -> str:
        """실제로 보낼 소개 (비어 있으면 카페 이름)"""
        return self.introduction or self.name

    def check(self) -> None:
        """서버에 묻기 전에 알 수 있는 입력 오류 검사 (실패면 CafeValidationError / ValueError)"""
        _check_bytes(CafeFormField.NAME, self.name, MAX_NAME_BYTES)
        if self.url is not None:
            _check_bytes(CafeFormField.URL, self.url, MAX_URL_BYTES)
            if not _RE_CAFE_URL.match(self.url):
                raise CafeValidationError(
                    f"카페 주소에 쓸 수 없는 문자가 있습니다: {self.url!r}",
                    field=CafeFormField.URL.value, value=self.url, result=ValidationResult.INVALIDCHARACTER.value,
                )
        _check_bytes(CafeFormField.INTRODUCTION, self.effective_introduction, MAX_INTRODUCTION_BYTES)
        if len(self.keywords) > MAX_KEYWORDS:
            raise CafeValidationError(
                f"키워드는 최대 {MAX_KEYWORDS}개입니다 ({len(self.keywords)}개)",
                field=CafeFormField.KEYWORD.value, value=",".join(self.keywords), result=ValidationResult.BYTE.value,
            )
        for kw in self.keywords:
            _check_bytes(CafeFormField.KEYWORD, kw, MAX_KEYWORD_BYTES)
        if self.use_real_name and not self.open_type.allows_real_name:
            raise ValueError("실명 가입(use_real_name)은 바로 가입(CafeOpenType.OPEN) 카페에서 쓸 수 없습니다")
        if self.region_code and not self.open_type.is_public:
            raise ValueError("지역(region_code)은 공개 카페에서만 설정할 수 있습니다")
        if not self.agree_to_privacy_policy:
            raise ValueError("개인정보 수집·이용에 동의해야 카페를 만들 수 있습니다 (agree_to_privacy_policy)")


@dataclass(slots=True, frozen=True, kw_only=True)
class Directory:
    """카페 주제/지역 분류 (themeDirList[] / areaDirList[] / sub-directories)"""

    dir_id: int
    name: str
    parent_id: int = 0
    depth: int = 1

    @classmethod
    def from_api(cls, d: Any, parent_id: int = 0) -> Self:
        d = as_dict(d)
        return cls(
            dir_id=as_int(d.get("dirId", d.get("directoryId"))),
            name=str(d.get("dirName", d.get("directoryName", ""))),
            parent_id=as_int(d.get("parentDirId", parent_id)),
            depth=as_int(d.get("dirDepth", 2 if parent_id else 1)),
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class Region:
    """카페 지역 (cafe-add-api cafe-region) [실측 2026-11-24] - code 를 CafeCreateOptions.region_code 로 쓴다"""

    code: str                     # rcode: "06" 대구광역시, "06290" 달서구, "A1017" 아시아
    name: str                     # 이 단계 이름 ("달서구")
    overseas: bool = False
    names: tuple[str, ...] = ()   # 상위부터 이름 ("대구광역시", "달서구")

    @property
    def full_name(self) -> str:
        """화면 표시 이름 (국내는 상위 포함 "대구광역시 달서구", 해외는 자기 이름) [번들 fullName]"""
        return self.name if self.overseas else " ".join(self.names or (self.name,))

    @classmethod
    def from_api(cls, d: Any) -> Self:
        d = as_dict(d)
        names = tuple(str(d[f"regionName{i}"]) for i in range(1, 6) if d.get(f"regionName{i}"))
        return cls(
            code=str(d.get("rcode") or d.get("code") or ""),
            name=str(d.get("name") or (names[-1] if names else "")),
            overseas=str(d.get("rcodeType") or d.get("type") or "").upper() == "OVERSEAS",
            names=names,
        )


@dataclass(slots=True, kw_only=True)
class CafeManageInfo:
    """카페 관리 설정 (cafe-manage-api /manage, 매니저만) [실측 2026-11-24]

    만든 카페의 설정이 실제로 반영됐는지 확인할 때 쓴다. 비공개(H) 카페는 서버가 주제를 -1, 소개를 "" 로 둔다
    [실측 2026-11-24: create-cafes 에 주제/소개를 보내도 버림].
    """

    cafe_id: int
    name: str
    url: str
    open_type: CafeOpenType | None
    real_name: bool               # 실명 가입 (enableRealName)
    introduction: str
    theme: int                    # themeDir1Id (-1: 없음)
    sub_theme: int                # themeDir2Id (-1: 없음)
    region_code: str = ""         # 설정된 지역 코드 (없으면 "")
    keywords: tuple[str, ...] = ()
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, data: Any, cafe_id: int = 0) -> Self:
        d = as_dict(data)
        res = as_dict(as_dict(d.get("message")).get("result")) or as_dict(d.get("result")) or d
        cafe = as_dict(res.get("cafe"))
        theme = as_dict(res.get("theme"))
        detail = as_dict(as_dict(res.get("region")).get("regionCodeDetail"))
        region = Region.from_api(detail) if detail else None
        try:
            open_type = CafeOpenType(str(cafe.get("openType"))) if cafe.get("openType") else None
        except ValueError:
            open_type = None
        kws = []
        for k in as_list(res.get("cafeKeywordList")):
            kws.append(str(as_dict(k).get("keyword", k) if isinstance(k, dict) else k))
        return cls(
            cafe_id=as_int(cafe.get("cafeId")) or cafe_id,
            name=str(cafe.get("cafeName") or res.get("cafeName") or ""),
            url=str(cafe.get("cafeUrl") or ""),
            open_type=open_type,
            real_name=bool(cafe.get("enableRealName")),
            introduction=str(cafe.get("introduction") or ""),
            theme=as_int(theme.get("themeDir1Id"), -1),
            sub_theme=as_int(theme.get("themeDir2Id"), -1),
            region_code=region.code if region else "",
            keywords=tuple(kws),
            raw=res,
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class CaptchaChallenge:
    """풀어야 할 캡차 1개. 답(csValue)과 함께 key 를 그대로 다시 보낸다."""

    type: CaptchaType
    key: str
    image_url: str = ""   # 이미지 캡차면 nhncaptchav4.gif 주소

    @property
    def sound_url(self) -> str:
        """음성 캡차 음원 (영어 숫자 wav) - 음성 캡차일 때만 의미가 있다"""
        from ..core.endpoints import SOUND_CAPTCHA_WAV

        return f"{SOUND_CAPTCHA_WAV}?key={self.key}"


@dataclass(slots=True, kw_only=True)
class CreationInfo:
    """GET view/creations 응답 (개설 화면을 열 때 1회) [실측 2026-11-24]

    clubTempId / alimCode 는 create-cafes 에 그대로 다시 보내는 화면 토큰이다.
    agreeyn 은 약관 동의 이력 - 프론트는 agreeToTerms 를 이 값에서 만든다 ("Y" -> true) [번들].
    """

    club_temp_id: str
    alim_code: str
    image_captcha_key: str
    image_captcha_url: str
    sound_captcha_key: str
    agreed_terms: bool
    themes: list[Directory] = field(default_factory=list)
    areas: list[Directory] = field(default_factory=list)
    cafe_groups: list[JSON] = field(default_factory=list)
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    def challenge(self, captcha_type: CaptchaType) -> CaptchaChallenge:
        """이 화면의 첫 캡차 문제"""
        if captcha_type is CaptchaType.SOUND:
            return CaptchaChallenge(type=captcha_type, key=self.sound_captcha_key)
        return CaptchaChallenge(type=captcha_type, key=self.image_captcha_key, image_url=self.image_captcha_url)

    @classmethod
    def from_api(cls, data: Any) -> Self:
        res = as_dict(as_dict(as_dict(data).get("message")).get("result"))
        return cls(
            club_temp_id=str(res.get("clubTempId") or ""),
            alim_code=str(res.get("alimCode") or ""),
            image_captcha_key=str(res.get("csKey") or ""),
            image_captcha_url=str(res.get("csImageUrl") or ""),
            sound_captcha_key=str(res.get("soundCaptchaKey") or ""),
            agreed_terms=str(res.get("agreeyn") or "").upper() == "Y",
            themes=[Directory.from_api(d) for d in as_list(res.get("themeDirList"))],
            areas=[Directory.from_api(d) for d in as_list(res.get("areaDirList"))],
            cafe_groups=[as_dict(g) for g in as_list(res.get("cafeGroupList"))],
            raw=res,
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class FieldValidation:
    """입력 1개의 서버 검증 결과"""

    field: CafeFormField
    value: str
    result: ValidationResult

    @property
    def ok(self) -> bool:
        return self.result.ok

    def raise_for_result(self) -> None:
        """CLEAR 가 아니면 CafeValidationError"""
        if not self.ok:
            raise CafeValidationError(
                f"{self.field.value} 검증 실패 ({self.result.value}): {self.value!r}",
                field=self.field.value, value=self.value, result=self.result.value,
            )


@dataclass(slots=True, kw_only=True)
class CreatedCafe:
    """만들어진 카페 (create-cafes 성공 응답 + 선택적으로 카페 ID 조회)"""

    url: str                  # slug (cafe.naver.com/{url})
    name: str
    cafe_id: int = 0          # resolve_id=False 이거나 조회 실패면 0
    icon_url: str = ""        # 올린 아이콘 경로 (없으면 "")
    message: str = ""         # 서버 메시지 ("카페 생성에 성공 했습니다.")
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @property
    def link(self) -> str:
        return f"https://cafe.naver.com/{self.url}"
