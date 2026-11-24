"""네이버 카페 API 값 열거형 (2026-11 실측 응답 기준)"""
from enum import IntEnum, StrEnum


class _Lenient(StrEnum):
    """API 가 모르는 값을 내려줘도 죽지 않도록 UNKNOWN 으로 받는 StrEnum"""

    @classmethod
    def _missing_(cls, value: object) -> "_Lenient":
        del value
        return cls["UNKNOWN"]  # type: ignore[return-value]


class MenuType(_Lenient):
    """cafe-cafemain-api menus[].menuType"""

    BOARD = "B"       # 일반 게시판 (앨범형도 B + boardType I)
    SEPARATOR = "S"   # 구분선 (name 없음)
    MEMO = "M"        # 가입인사 등 메모 게시판
    ATTENDANCE = "A"  # 출석체크
    FOLDER = "F"      # [실측 2026-11-13] 폴더(하위 메뉴 묶음) - 글 목록 없음 (목록 API 가 빈 결과)
    LINK = "L"        # [실측 2026-11-13] 값 존재 확인. 의미(링크 메뉴)는 [추정]
    UNKNOWN = "?"     # 실측에 없던 값

    @property
    def is_board(self) -> bool:
        """글 목록을 가진 일반 게시판인지 (폴더/구분선/링크/모르는 값 제외)"""
        return self is MenuType.BOARD

    @property
    def is_container(self) -> bool:
        """글이 없는 구조용 메뉴(폴더/구분선)인지"""
        return self in (MenuType.FOLDER, MenuType.SEPARATOR)


class BoardType(_Lenient):
    """menus[].boardType - 목록 표시 형태"""

    LIST = "L"
    IMAGE = "I"
    MEMO = "M"
    T = "T"           # [실측 2026-11-13] 값 존재 확인, 표시 형태 의미는 미확인
    UNKNOWN = "?"


class SortBy(StrEnum):
    """게시글 목록 정렬 [실측 2026-11-13]

    서버가 받는 값은 TIME / LIKE / COMMENT / READ 이고, 그 외 값은 400.
    COMMENT, READ 는 받기만 하고 결과는 최신순과 같아서 넣지 않았다.
    """

    TIME = "TIME"   # 최신순
    LIKE = "LIKE"   # 좋아요순


class ViewType(StrEnum):
    """게시글 목록 보기 형태 (boardlist API viewType, L 실측 확인)"""

    LIST = "L"
    IMAGE = "I"
    CARD = "C"


class ReactionType(StrEnum):
    """like 서비스 반응 종류"""

    LIKE = "like"


class ArticleListItemType(_Lenient):
    """boardlist articleList[].type"""

    ARTICLE = "ARTICLE"
    AD = "AD"
    REQUIRED_NOTICE = "REQUIRED_NOTICE"    # [실측 2026-11-13] 필독 공지
    CAFE_MAIN_NOTICE = "CAFE_MAIN_NOTICE"  # [실측 2026-11-13] 카페 전체 공지
    MENU_NOTICE = "MENU_NOTICE"            # [실측 2026-11-13] 게시판 공지
    UNKNOWN = "?"

    @property
    def is_notice(self) -> bool:
        return self in (
            ArticleListItemType.REQUIRED_NOTICE,
            ArticleListItemType.CAFE_MAIN_NOTICE,
            ArticleListItemType.MENU_NOTICE,
        )


# ---------------------------------------------------------------- 카페 만들기 [실측 2026-11-24 Whale 캡처 + 프론트 번들]
class CafeOpenType(StrEnum):
    """카페 만들기 openType - 공개 여부와 가입 방식을 한 값으로 고른다

    [실측 2026-11-24] O/C/H 로 각각 카페를 만들어 homepc myCafe.cafes[].openType 에 같은 값이 돌아오는 것을 확인.
    값의 의미는 프론트 번들(openTypeCode: OPEN->O, CLOSED->C, HIDDEN->H)과 개설 화면의 가입 방식 3가지 대응.
    """

    OPEN = "O"      # 공개 + 바로 가입 (개설 화면 기본값)
    CLOSED = "C"    # 공개 + 가입 신청 승인 후 가입
    HIDDEN = "H"    # 비공개 (검색/주소 방문 불가, 초대로만 가입)

    @property
    def is_public(self) -> bool:
        """검색·주소 방문이 되는 공개 카페인지"""
        return self is not CafeOpenType.HIDDEN

    @property
    def allows_real_name(self) -> bool:
        """실명 가입(useName=Y)을 쓸 수 있는지 - 프론트는 바로 가입이면 실명 옵션을 끈다 (isUsingRealNameAvailable)"""
        return self is not CafeOpenType.OPEN


class CafeFormField(StrEnum):
    """카페 만들기 입력 검증 API 경로 (POST cafe-home/v1/validation/{field}) [실측 2026-11-24]"""

    NAME = "cafeName"            # {"clubName": ...}
    URL = "cafeUrl"              # {"clubUrl": ...}
    INTRODUCTION = "introduction"  # {"introduction": ...}
    KEYWORD = "keyword"          # {"keyword": ...} 키워드 1개씩

    @property
    def body_key(self) -> str:
        """요청 본문 키"""
        return {
            CafeFormField.NAME: "clubName",
            CafeFormField.URL: "clubUrl",
            CafeFormField.INTRODUCTION: "introduction",
            CafeFormField.KEYWORD: "keyword",
        }[self]


class ValidationResult(_Lenient):
    """validation API 의 result.validationResult

    CLEAR / DUPLICATED / INVALIDCHARACTER 는 [실측 2026-11-24]. PROHIBITWORD / BYTE 는 프론트 번들의 분기에 있는 값,
    ISEMPTY 는 프론트 폼 상태 값이다.
    [실측 2026-11-24] 캡차 오답도 INVALIDCHARACTER (+ 새 csKey) 로 온다.
    서버는 길이를 보지 않는다 (60바이트 넘는 이름, 100바이트 넘는 소개도 CLEAR) -> 길이는 CafeCreateOptions.check() 가 막는다.
    짧은 금칙어/욕설 이름("시발")은 DUPLICATED 로 왔다.
    """

    CLEAR = "CLEAR"                       # 사용 가능
    DUPLICATED = "DUPLICATED"             # 이미 쓰는 이름/주소 (짧은 주소 "o", "oi" 도 이 값) [실측]
    INVALIDCHARACTER = "INVALIDCHARACTER"  # 주소에 - _ 등 허용 안 된 문자 [실측]
    PROHIBITWORD = "PROHIBITWORD"         # 금칙어
    BYTE = "BYTE"                         # 길이 초과
    ISEMPTY = "ISEMPTY"                   # 빈 값
    UNKNOWN = "?"

    @property
    def ok(self) -> bool:
        return self is ValidationResult.CLEAR


class CaptchaType(StrEnum):
    """카페 만들기 캡차 종류 (프론트 CAPTCHA_TYPE). 검증 API 경로이기도 하다: validation/{값}"""

    IMAGE = "imageCaptcha"   # 이미지 (nhncaptchav4.gif, view/creations 의 csKey)
    SOUND = "soundCaptcha"   # 음성 (soundCaptcha.wav, view/creations 의 soundCaptchaKey) [실측 2026-11-24 사용]


class ThemeDirectory(IntEnum):
    """카페 주제 대분류 (view/creations themeDirList[].dirId) [실측 2026-11-24]

    소분류(currentThemeDir2)는 대분류마다 다르고 바뀔 수 있어 열거형으로 두지 않는다
    -> `cafe.cafes.sub_directories(ThemeDirectory.TRAVEL)` 로 조회.
    """

    GAME = 1                 # 게임
    ANIMATION = 2            # 만화/애니메이션
    BROADCAST = 3            # 방송/연예
    CULTURE_ART = 4          # 문화/예술
    MOVIE = 5                # 영화
    MUSIC = 6                # 음악
    FAN_CAFE = 7             # 팬카페
    TRAVEL = 8               # 여행
    SPORTS_LEISURE = 9       # 스포츠/레저
    PET_ANIMAL = 10          # 반려동물/동물
    HOBBY = 11               # 취미
    LIFE = 12                # 생활
    FASHION_BEAUTY = 13      # 패션/미용
    HEALTH_DIET = 14         # 건강/다이어트
    FAMILY_PARENTING = 15    # 가족/육아
    COMPUTER = 16            # 컴퓨터/통신
    EDUCATION = 17           # 교육
    FOREIGN_LANGUAGE = 18    # 외국어
    HUMANITIES_SCIENCE = 19  # 인문/과학
    ECONOMY_FINANCE = 20     # 경제/금융
    POLITICS_SOCIETY = 21    # 정치/사회
    LITERATURE = 22          # 문학/창작
    ALUMNI = 23              # 동창/동문
    SOCIAL_GATHERING = 24    # 친목/모임
    RELIGION_VOLUNTEER = 25  # 종교/봉사
