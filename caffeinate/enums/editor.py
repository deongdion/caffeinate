"""SmartEditor ONE 블록 값 [실측 2026-11-24: 에디터 1.78.1 번들 + 글 저장/렌더 확인]

서버는 layout 을 검사하지 않는다 (없는 값도 저장되고 se-l-{값} 클래스로만 나온다) [실측 2026-11-24].
그래서 enum 에 없는 값도 문자열로 넘길 수 있게 블록 필드는 `Enum | str` 을 받는다.
"""
from enum import StrEnum


class FontSize(StrEnum):
    """글자 크기 nodeStyle.fontSizeCode. 목록 밖 값("fs999")은 서버가 버린다 [실측 2026-11-24]"""

    FS11 = "fs11"
    FS13 = "fs13"
    FS15 = "fs15"   # 에디터 기본
    FS16 = "fs16"
    FS19 = "fs19"
    FS24 = "fs24"
    FS28 = "fs28"
    FS30 = "fs30"
    FS34 = "fs34"
    FS38 = "fs38"


class FontFamily(StrEnum):
    """서체 nodeStyle.fontFamily - 카페 에디터 서체 목록 [실측 2026-11-24, 보기 화면 se-ff-<값>]
    목록 밖 값도 저장되지만 CSS 가 없어 기본 서체로 보인다."""

    SYSTEM = "system"                            # 기본서체
    NANUM_GOTHIC = "nanumgothic"                 # 나눔고딕
    NANUM_MYEONGJO = "nanummyeongjo"             # 나눔명조
    NANUM_BARUN_GOTHIC = "nanumbarungothic"      # 나눔바른고딕
    NANUM_SQUARE = "nanumsquare"                 # 나눔스퀘어
    NANUM_SQUARE_NEO = "nanumsquareneo"          # 나눔스퀘어 네오
    MARUBURI = "nanummaruburi"                   # 마루부리
    DASI_SIJAGHAE = "nanumdasisijaghae"          # 다시시작해
    BAREUN_HIPI = "nanumbareunhipi"              # 바른히피
    URIDDAL_SONGEULSSI = "nanumuriddalsongeulssi"  # 우리딸손글씨


class Align(StrEnum):
    """문단 정렬 paragraphStyle.align [실측: center -> se-text-paragraph-align-center]"""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class QuotationLayout(StrEnum):
    """인용 모양 [번들 1.78.1, 6종 저장 실측 2026-11-24]"""

    DEFAULT = "default"
    LINE = "quotation_line"
    BUBBLE = "quotation_bubble"
    UNDERLINE = "quotation_underline"
    POSTIT = "quotation_postit"
    CORNER = "quotation_corner"


class LineLayout(StrEnum):
    """구분선 모양 [번들 1.78.1, 8종 저장 실측 2026-11-24]"""

    DEFAULT = "default"
    LINE1 = "line1"
    LINE2 = "line2"
    LINE3 = "line3"
    LINE4 = "line4"
    LINE5 = "line5"
    LINE6 = "line6"
    LINE7 = "line7"


class CodeLayout(StrEnum):
    """코드 블록 모양 [번들 1.78.1, 3종 저장 실측 2026-11-24]"""

    DEFAULT = "default"
    STRIPE = "code_stripe"
    BLACK = "code_black"


class ImageGroupLayout(StrEnum):
    """이미지 묶음 모양 [번들 1.78.1]

    [실측 2026-11-24] slide 는 서버 HTML 에 이미지가 들어가고, collage·individual 은 데이터만 들어간다 (뷰어 JS 가 그림).
    """

    COLLAGE = "collage"
    SLIDE = "slide"
    INDIVIDUAL = "individual"


class LinkCardLayout(StrEnum):
    """링크 미리보기(oglink) 모양 [번들 1.78.1, 4종 저장 실측 2026-11-24]"""

    TEXT = "text"                       # 글자만
    IMAGE = "image"                     # 작은 썸네일 (ff120)
    VERTICAL_IMAGE = "vertical_image"   # 세로 썸네일 (ff250_444)
    LARGE_IMAGE = "large_image"         # 큰 썸네일 (ff500_300) - 에디터 기본


class StickerFormat(StrEnum):
    NORMAL = "normal"
    ANIMATED = "animated"


class VoteResultView(StrEnum):
    """투표 결과 공개 시점 viewProperty.resultViewCondition [cafe 번들 2026-11-24]"""

    AFTER_VOTE = "after_vote"    # 투표 참여 후 보기 (에디터 기본)
    AFTER_CLOSE = "after_close"  # 투표 종료 후 보기
    ALWAYS = "always"            # 항상 보기


class VoteSort(StrEnum):
    """투표 결과 항목 정렬 viewProperty.resultItemSortType [cafe 번들 2026-11-24]"""

    ITEM_INDEX = "item_index"    # 항목 번호 순 (기본)
    MOST_VOTED = "most_voted"    # 득표 많은 순


class MaterialType(StrEnum):
    """글감(material) 종류 - 카페 글감 검색 materialSet [cafe 번들 2026-11-24]"""

    BOOK = "book"
    MOVIE = "movie"
    BROADCAST = "broadcast"
    MUSIC = "music"
    SHOPPING = "shopping"
    NEWS = "news"
    SHOW = "show"                # 공연·전시
    SPORTS = "sports"
    REALESTATE = "realestate"
