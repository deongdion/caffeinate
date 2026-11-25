"""카페 에디터 툴바의 나머지 블록 - 파일·동영상·장소·수식·글감·외부 임베드·투표·일정 [실측 2026-11-24]

전부 headless 브라우저로 실제 카페 글쓰기 에디터(1.78.1)를 조작해 만든 컴포넌트를 캡처하고,
같은 dict 를 글 수정 API 로 저장해 서버 렌더까지 확인한 형식이다.

    from caffeinate import File, Video, Map, Formula, Vote, Schedule

    doc = Document([
        File("report.pdf"),                                  # 작성 때 upapi 로 업로드
        Video("clip.mp4", title="제목"),                      # 작성 때 VOD 업로드 + 인코딩 대기
        Map(await cafe.editor.places(cid, 1, "서울역")),      # 장소 검색 결과 그대로
        Formula(r"\\frac{a}{b}"),                           # 작성 때 네이버 수식 편집기로 렌더 (headless)
        Vote("점심 메뉴", ["김밥", "라면"]),                   # 저장 시 서버가 투표를 만든다
        Schedule("정기 모임", datetime(2026, 12, 1, 19)),      # 저장 시 서버가 일정을 만든다
        await cafe.editor.embed(cid, 1, "https://youtu.be/..."),   # YouTube 등 oembed
        (await cafe.editor.materials(cid, 1, "해리포터"))[0],      # 글감 (책·영화·음악 ...)
    ])

카페에서 쓸 수 없는 것 [실측 2026-11-24]
- 오디오(audio): platform.editor audio-uploader/session-key 가 406 "Audio Infra ServiceId Config fail : serviceId = cafe"
- MYBOX 사진·파일·동영상: MYBOX 본인 인증 계정이 필요 (요청에 따라 제외)
"""
import math
import random
import re
import uuid as _uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, ClassVar, Self
from urllib.parse import quote

from ..enums.editor import FontSize, MaterialType, VoteResultView, VoteSort
from ..utils.editor import se_id
from ..utils.parsing import as_dict, as_int, as_list
from .blocks import (
    CTYPE,
    Block,
    JSONDict,
    Paragraph,
    Thumbnail,
    _check_link,
    _enum_or_str,
    _s,
    _split,
    font_size_of,
    paragraphs,
)
from .photo import UploadedImage

# ---------------------------------------------------------------- 파일


@dataclass(slots=True, frozen=True)
class UploadedFile:
    """upapi.cafe.naver.com/v1.0/cafes/editor/files 응답 {fileId, fileName, fileSize} [실측 2026-11-24]"""

    file_id: str
    file_name: str
    file_size: int = 0

    @classmethod
    def from_api(cls, d: Any) -> Self:
        d = as_dict(d)
        if not d.get("fileId"):
            raise ValueError(f"파일 업로드 응답에 fileId 가 없습니다: {str(d)[:200]}")
        return cls(str(d["fileId"]), str(d.get("fileName") or ""), as_int(d.get("fileSize")))


@dataclass(slots=True)
class File(Block):
    """파일 첨부 (file) - source 가 UploadedFile 이 아니면 작성 때 업로드 (bytes / 경로 / (bytes, 이름))

    [실측 2026-11-24] 에디터 "파일 > 내 컴퓨터" -> POST upapi .../editor/files (multipart userId, file)
    -> {layout, fileId, fileName, fileSize}. 저장하면 se-file 로 렌더. 50MB 까지 (fileUploadLimitFileSize).
    """

    CTYPE: ClassVar[str] = "file"
    source: Any = None
    layout: str = "default"

    def __post_init__(self) -> None:
        if self.source is None:
            raise ValueError("File 에는 source(UploadedFile / bytes / 파일 경로 / (bytes, 이름))가 필요합니다")

    @property
    def uploaded(self) -> UploadedFile | None:
        return self.source if isinstance(self.source, UploadedFile) else None

    def _body(self) -> JSONDict:
        f = self.uploaded
        if f is None:
            raise ValueError("업로드 안 된 File 입니다 - articles.write 에 넘기면 자동으로 올립니다")
        return {"layout": _s(self.layout), "fileId": f.file_id, "fileName": f.file_name, "fileSize": f.file_size}

    @classmethod
    def _parse(cls, d: JSONDict) -> "File":
        return cls(UploadedFile(str(d.get("fileId") or ""), str(d.get("fileName") or ""), as_int(d.get("fileSize"))),
                   str(d.get("layout") or "default"), id=str(d.get("id") or se_id()),
                   extra=_split(d, ("id", "layout", "fileId", "fileName", "fileSize")))


# ---------------------------------------------------------------- 동영상


@dataclass(slots=True, frozen=True)
class UploadedVideo:
    """VOD 업로드 + 인코딩 결과 [실측 2026-11-24 nexus.vod.naver.com postman VideoHeader/Thumbnails]"""

    vid: str
    file_size: int = 0
    play_time: int = 0          # 초 (VideoHeader.duration 내림 - 7.5초 -> 7 실측)
    width: int = 0
    height: int = 0
    thumbnail: str = ""         # 대표 장면 (Thumbnails 의 첫 SCENE)
    service_id: str = "5"       # videoInfraServiceId (카페 = 5)


@dataclass(slots=True)
class Video(Block):
    """동영상 (video) - source 가 UploadedVideo 가 아니면 작성 때 업로드하고 인코딩을 기다린다

    [실측 2026-11-24] 업로드 창 "완료" 직후 컴포넌트 (키 순서 그대로). 제목·정보는 mediaMeta 에만 들어간다
    (별도 API 없음). 저장하면 서버가 재생 키(inkey)를 붙여 플레이어로 렌더.
    represent 를 비우면 문서의 첫 사진/동영상이 대표가 된다.
    """

    CTYPE: ClassVar[str] = "video"
    source: Any = None
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    caption: Any = None
    represent: bool | None = None
    layout: str = "default"

    def __post_init__(self) -> None:
        if self.source is None:
            raise ValueError("Video 에는 source(UploadedVideo / bytes / 파일 경로 / (bytes, 이름))가 필요합니다")
        self.caption = paragraphs(self.caption) if self.caption is not None else None
        if len(self.title) > 40:
            raise ValueError("동영상 제목은 40자까지입니다 (에디터 maxVideoTitleLength)")
        if len(self.description) > 300:
            raise ValueError("동영상 정보는 300자까지입니다 (에디터 maxVideoDescLength)")
        if len(self.tags) > 10:
            raise ValueError("동영상 태그는 10개까지입니다")

    @property
    def uploaded(self) -> UploadedVideo | None:
        return self.source if isinstance(self.source, UploadedVideo) else None

    def media(self) -> Iterator[Any]:
        yield self

    def _body(self) -> JSONDict:
        v = self.uploaded
        if v is None:
            raise ValueError("업로드 안 된 Video 입니다 - articles.write 에 넘기면 자동으로 올립니다")
        w, h = video_display_size(v.width, v.height)
        meta: JSONDict = {}
        if self.title:
            meta["title"] = self.title
        meta["tags"] = list(self.tags)
        if self.description:
            meta["description"] = self.description
        meta[CTYPE] = "mediaMeta"
        return {
            "layout": _s(self.layout), "contentMode": "normal", "fileSize": v.file_size, "playTime": v.play_time,
            "internalResource": True, "thumbnail": {"src": v.thumbnail, CTYPE: "thumbnail"},
            "originalWidth": v.width, "originalHeight": v.height, "width": w, "height": h,
            "caption": [p.to_dict() for p in self.caption] if self.caption else None, "format": "normal",
            "represent": bool(self.represent), "vid": v.vid, "mediaMeta": meta,
            "videoInfraServiceId": v.service_id, "origin": {"srcFrom": "local", CTYPE: "videoOrigin"}, "ai": False,
        }

    @classmethod
    def _parse(cls, d: JSONDict) -> "Video":
        th = as_dict(d.get("thumbnail"))
        meta = as_dict(d.get("mediaMeta"))
        v = UploadedVideo(str(d.get("vid") or ""), as_int(d.get("fileSize")), as_int(d.get("playTime")),
                          as_int(d.get("originalWidth") or d.get("width")),
                          as_int(d.get("originalHeight") or d.get("height")), str(th.get("src") or ""),
                          str(d.get("videoInfraServiceId") or "5"))
        cap = d.get("caption")
        return cls(v, str(meta.get("title") or ""), str(meta.get("description") or ""),
                   [str(t) for t in as_list(meta.get("tags"))],
                   [Paragraph.from_dict(p) for p in cap] if isinstance(cap, list) and cap else None,
                   bool(d.get("represent")), str(d.get("layout") or "default"), id=str(d.get("id") or se_id()),
                   extra=_split(d, ("id", "layout", "contentMode", "fileSize", "playTime", "internalResource",
                                    "thumbnail", "originalWidth", "originalHeight", "width", "height", "caption",
                                    "format", "represent", "vid", "mediaMeta", "videoInfraServiceId", "origin",
                                    "ai")))


CAFE_DOCUMENT_WIDTH = 800   # 카페 에디터 productConfig.documentWidth [cafe app.js 2026-11-24]


def video_display_size(width: int, height: int, document_width: int = CAFE_DOCUMENT_WIDTH) -> tuple[int, int]:
    """에디터가 넣는 표시 크기 - 문서 폭보다 넓으면 비율 유지로 줄인다
    [실측 2026-11-24: 640x360 -> 640x360, 1280x720 -> 800x450]

    높이는 반올림이 아니라 버림이다: 에디터 _resolveWidthAndHeight 가 Math.floor(h * (documentWidth / w))
    [번들 se-app-context.js]. 곱하는 순서도 같게 해 부동소수 결과까지 맞춘다.
    """
    if width > document_width and width:
        return document_width, math.floor(height * (document_width / width))
    return width, height


# ---------------------------------------------------------------- 장소 (지도)


@dataclass(slots=True, frozen=True)
class Place:
    """장소 하나 (placesMap.places[]) - 보통 `cafe.editor.places()` 검색 결과"""

    name: str
    latitude: float
    longitude: float
    address: str = ""
    place_id: str = ""
    tel: str = ""
    search_type: str = "s"

    def to_dict(self) -> JSONDict:
        d: JSONDict = {}
        if self.place_id:
            d["placeId"] = self.place_id
        d.update(name=self.name, address=self.address,
                 latlng={"latitude": self.latitude, "longitude": self.longitude, CTYPE: "position"},
                 searchType=self.search_type)
        if self.tel:
            d["tel"] = self.tel
        d[CTYPE] = "place"
        return d

    @classmethod
    def from_dict(cls, d: Any) -> Self:
        d = as_dict(d)
        ll = as_dict(d.get("latlng"))
        return cls(str(d.get("name") or ""), float(ll.get("latitude") or 0), float(ll.get("longitude") or 0),
                   str(d.get("address") or ""), str(d.get("placeId") or ""), str(d.get("tel") or ""),
                   str(d.get("searchType") or "s"))

    @classmethod
    def from_api(cls, item: Any) -> Self:
        """platform.editor /map/naver/places 의 result.place.list[] -> Place [실측 2026-11-24]

        에디터는 address 에 도로명 주소(roadAddress)를 넣는다.
        """
        d = as_dict(item)
        return cls(str(d.get("name") or ""), float(d.get("y") or 0), float(d.get("x") or 0),
                   str(d.get("roadAddress") or d.get("address") or ""), str(d.get("id") or ""),
                   str(d.get("tel") or ""), str(d.get("type") or "s"))


STATIC_MAP = "https://simg.pstatic.net/static.map/v2/map/staticmap.bin"


def static_map_url(places: Sequence[Place], width: int = 620, height: int = 200) -> str:
    """에디터와 같은 지도 이미지 주소 [실측 2026-11-24 장소 1곳 / 2곳 캡처]

    한 곳: markers=pos:경도 위도|size:mid|color:0x11cc73|type:d|viewSizeRatio:0.7
    여러 곳: 곳마다 markers=viewSizeRatio:0.7|color:0x11cc73|label:a..|pos:..|size:mid|type:a
    (에디터가 붙이는 dataversion 은 없어도 같은 이미지 - 실측)
    """
    def pos(p: Place) -> str:
        return f"pos:{_num(p.longitude)} {_num(p.latitude)}"

    if len(places) == 1:
        markers = [f"{pos(places[0])}|size:mid|color:0x11cc73|type:d|viewSizeRatio:0.7"]
    else:
        markers = [f"viewSizeRatio:0.7|color:0x11cc73|label:{chr(97 + i % 26)}|{pos(p)}|size:mid|type:a"
                   for i, p in enumerate(places)]
    q = "&".join("markers=" + quote(m, safe="") for m in markers)
    return f"{STATIC_MAP}?caller=smarteditor&{q}&w={width}&h={height}&scale=2"


def _num(v: float) -> str:
    """JS Number.toString 과 같게 (126.9707021 / 37.5)"""
    s = repr(float(v))
    return s.removesuffix(".0")


@dataclass(slots=True)
class Map(Block):
    """장소 지도 (placesMap) [실측 2026-11-24 에디터 "장소" 캡처 + 저장 렌더]

    thumbnail 을 비우면 에디터와 같은 정적 지도 주소를 만든다 (620x200, 문서 폭 기준).
    """

    CTYPE: ClassVar[str] = "placesMap"
    places: list[Place] = field(default_factory=list)
    thumbnail: str | None = None
    search_engine: str = "naver"
    layout: str = "default"

    def __post_init__(self) -> None:
        if isinstance(self.places, Place):
            self.places = [self.places]
        self.places = list(self.places)
        if not self.places:
            raise ValueError("Map 에는 장소가 하나 이상 있어야 합니다")
        if not all(isinstance(p, Place) for p in self.places):
            raise TypeError("Map.places 는 Place 목록입니다 (cafe.editor.places 로 검색)")

    def _body(self) -> JSONDict:
        return {"layout": _s(self.layout), "searchEngine": self.search_engine,
                "thumbnail": {"src": self.thumbnail or static_map_url(self.places), CTYPE: "thumbnail"},
                "places": [p.to_dict() for p in self.places]}

    @classmethod
    def _parse(cls, d: JSONDict) -> "Map":
        return cls([Place.from_dict(p) for p in as_list(d.get("places"))],
                   str(as_dict(d.get("thumbnail")).get("src") or "") or None, str(d.get("searchEngine") or "naver"),
                   str(d.get("layout") or "default"), id=str(d.get("id") or se_id()),
                   extra=_split(d, ("id", "layout", "searchEngine", "thumbnail", "places")))

    def texts(self) -> Iterator[str]:
        return (p.name for p in self.places)


# ---------------------------------------------------------------- 수식


@dataclass(slots=True)
class Formula(Block):
    """수식 (formula) - latex 만 주면 작성 때 네이버 수식 편집기로 html·이미지를 만든다 (headless Camoufox)

    [실측 2026-11-24]
    - html·thumbnail 둘 다 필수 (빠지면 500 99999)
    - 글 보기 화면은 html 을 그린다 (thumbnail 은 이미지 대체용). html 은 mathquill 마크업이어야 수식으로 보인다
      (span/var 는 통과, <img> 는 글자로 이스케이프, <math>·<script> 는 저장 거부 20103)
    - 그래서 html 을 직접 만들지 않고 에디터의 수식 편집기(se-math-editor)를 그대로 돌려 얻는다:
      `await cafe.editor.render_formulas(cid, menu, [Formula(...)])` (articles.write 가 알아서 부른다)
    """

    CTYPE: ClassVar[str] = "formula"
    latex: str = ""
    html: str | None = None
    thumbnail: Thumbnail | None = None
    font_size: FontSize | str = FontSize.FS15
    font_family: str = "system"
    layout: str = "default"

    def __post_init__(self) -> None:
        # 빈 latex 는 템플릿(AI 채우기)용 - 렌더할 때 막는다
        self.font_size = font_size_of(self.font_size)   # 틀린 크기는 브라우저를 띄우기 전에
        if isinstance(self.thumbnail, UploadedImage):
            img = self.thumbnail
            self.thumbnail = Thumbnail(src=f"{img.domain}{img.url}", width=img.width, height=img.height)

    @property
    def rendered(self) -> bool:
        return bool(self.html) and self.thumbnail is not None

    def _body(self) -> JSONDict:
        if not self.rendered or self.thumbnail is None:
            raise ValueError("렌더링 안 된 Formula 입니다 - articles.write 에 넘기거나 cafe.editor.render_formulas 로 먼저")
        return {"layout": _s(self.layout), "latex": self.latex, "html": self.html,
                "thumbnail": self.thumbnail.to_dict(), "fontSizeCode": _s(self.font_size),
                "fontFamily": self.font_family}

    @classmethod
    def _parse(cls, d: JSONDict) -> "Formula":
        return cls(str(d.get("latex") or ""), d.get("html") or None, Thumbnail.from_dict(d.get("thumbnail")),
                   _enum_or_str(FontSize, d.get("fontSizeCode"), FontSize.FS15), str(d.get("fontFamily") or "system"),
                   str(d.get("layout") or "default"), id=str(d.get("id") or se_id()),
                   extra=_split(d, ("id", "layout", "latex", "html", "thumbnail", "fontSizeCode", "fontFamily")))

    def texts(self) -> Iterator[str]:
        yield self.latex


# ---------------------------------------------------------------- 글감 (material)


@dataclass(slots=True, frozen=True)
class MaterialDetail:
    """글감 상세 한 줄 detailInfo[] {label, labelName, values[]}"""

    label: str
    label_name: str
    values: tuple[str, ...] = ()

    def to_dict(self) -> JSONDict:
        return {"label": self.label, "labelName": self.label_name,
                "values": [{"value": v, CTYPE: "value"} for v in self.values], CTYPE: "item"}

    @classmethod
    def from_dict(cls, d: Any) -> Self:
        d = as_dict(d)
        return cls(str(d.get("label") or ""), str(d.get("labelName") or ""),
                   tuple(str(as_dict(v).get("value") or "") for v in as_list(d.get("values"))))


@dataclass(slots=True)
class Material(Block):
    """글감 (material) - 책·영화·방송·음악·쇼핑·뉴스·공연전시·스포츠·부동산 검색 결과 카드

    보통 `cafe.editor.materials()` 검색 결과를 그대로 쓴다 (Material.from_search 가 에디터 변환을 그대로 옮긴 것).
    sign 은 검색 응답의 서버 서명. [실측 2026-11-24 책 글감 캡처 + 저장 렌더 se-material-book]
    """

    CTYPE: ClassVar[str] = "material"
    type: MaterialType | str = MaterialType.BOOK
    title: str = ""
    link: str = ""
    details: list[MaterialDetail] = field(default_factory=list)
    data_id: str = ""
    sub_id: str | None = None
    thumbnail: Thumbnail | None = None
    sign: str = ""
    vol_no: str | None = None
    vol_scs: str = "1"
    layout: str = "material_basic"

    def _body(self) -> JSONDict:
        d: JSONDict = {"layout": _s(self.layout), "type": _s(self.type), "title": self.title, "link": self.link,
                       "detailInfo": [x.to_dict() for x in self.details], "dataId": self.data_id}
        if self.sub_id:
            d["subId"] = self.sub_id
        if self.thumbnail:
            d["thumbnail"] = self.thumbnail.to_dict()
        if self.vol_no:
            d["volNo"] = self.vol_no
        d["volScs"] = self.vol_scs
        d["sign"] = self.sign
        return d

    @classmethod
    def _parse(cls, d: JSONDict) -> "Material":
        return cls(_enum_or_str(MaterialType, d.get("type")), str(d.get("title") or ""), str(d.get("link") or ""),
                   [MaterialDetail.from_dict(x) for x in as_list(d.get("detailInfo"))], str(d.get("dataId") or ""),
                   d.get("subId") or None, Thumbnail.from_dict(d.get("thumbnail")), str(d.get("sign") or ""),
                   d.get("volNo") or None, str(d.get("volScs") or "1"), str(d.get("layout") or "material_basic"),
                   id=str(d.get("id") or se_id()),
                   extra=_split(d, ("id", "layout", "type", "title", "link", "detailInfo", "dataId", "subId",
                                    "thumbnail", "volNo", "volScs", "sign")))

    def texts(self) -> Iterator[str]:
        yield self.title

    @classmethod
    def from_search(cls, kind: MaterialType | str, item: Any, *, thumbnail: Thumbnail | None = None) -> "Material":
        """글감 검색 응답 항목 -> Material (에디터 se-app-context 의 _makeMaterialInfo 를 그대로 옮김)

        thumbnail 크기는 에디터가 이미지를 불러와 잰다 -> cafe.editor.materials 가 같은 방식으로 채운다.
        """
        k = str(getattr(kind, "value", kind)).lower()
        conv = _MATERIAL_CONVERTERS.get(k)
        if conv is None:
            raise ValueError(f"글감 종류를 모릅니다: {kind!r} (가능: {sorted(_MATERIAL_CONVERTERS)})")
        d = as_dict(item)
        if k == "realestate" and "complexNumber" in d:
            d = normalize_realestate(d)
        m = conv(d)
        m.thumbnail = thumbnail
        return m


def restore_special_char(v: Any) -> str:
    """에디터 restoreSpecialChar (HTML 엔티티 일부 복원)"""
    if not isinstance(v, str):
        return ""
    for a, b in (("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">"), ("&#40;", "("),
                 ("&#41;", ")"), ("&apos;", "'")):
        v = v.replace(a, b)
    return v


def format_with_comma(v: Any) -> str:
    """에디터 formatWithComma (1234567.5 -> 1,234,567.5)"""
    if v in (None, ""):
        return "" if v is None else v
    parts = str(v).split(".")
    head = re.sub(r"\B(?=(\d{3})+(?!\d))", ",", parts[0].replace(",", ""))
    return ".".join([head, *parts[1:2]])


def format_date_with_text(v: Any, year_only: bool = False, trailing_dot: bool = True) -> str:
    """에디터 formatDateWithText ("20241120" -> "2024.11.20.", year_only -> "2024") - moment 엄격 파싱과 같은 결과"""
    if not isinstance(v, str) or not v.strip():
        return ""
    dot = "." if trailing_dot else ""
    s = re.sub(r"[．‧∙·•]", ".", v.strip())
    s = re.sub(r"[\s\-/\\]+", ".", s)
    s = re.sub(r"\.+", ".", s).strip(".")

    def ok(y: int, m: int = 1, d: int = 1) -> bool:
        try:
            datetime(y, m, d, tzinfo=UTC)
        except ValueError:
            return False
        return True

    if re.fullmatch(r"\d{8}", s):
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:])
        return (f"{y:04d}" if year_only else f"{y:04d}.{m:02d}.{d:02d}{dot}") if ok(y, m, d) else ""
    if re.fullmatch(r"\d{6}", s):
        y, m = int(s[:4]), int(s[4:])
        return (f"{y:04d}" if year_only else f"{y:04d}.{m:02d}{dot}") if ok(y, m) else ""
    if re.fullmatch(r"\d{4}", s):
        return s + ("" if year_only else dot)
    mt = re.fullmatch(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", s)
    if mt:
        y, m, d = (int(x) for x in mt.groups())
        return (f"{y:04d}" if year_only else f"{y:04d}.{m:02d}.{d:02d}{dot}") if ok(y, m, d) else ""
    mt = re.fullmatch(r"(\d{4})\.(\d{1,2})", s)
    if mt:
        y, m = (int(x) for x in mt.groups())
        return (f"{y:04d}" if year_only else f"{y:04d}.{m:02d}{dot}") if ok(y, m) else ""
    return ""


def format_date_range_with_text(v: Any) -> str:
    """에디터 formatDateRangeWithText ("2026.01.01 ~ 2026.02.01" -> "2026.01.01. ~ 2026.02.01.")"""
    if not v:
        return ""
    parts = [p.strip() for p in str(v).split(" ~ ")]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return format_date_with_text(str(v))
    a, b = format_date_with_text(parts[0]), format_date_with_text(parts[1])
    if not a and re.fullmatch(r"\d{1,2}\.\d{1,2}\.?|\d{4}", parts[0]) and b:
        a = format_date_with_text(_with_year(parts[0], b[:4]))
    if not b and re.fullmatch(r"\d{1,2}\.\d{1,2}\.?|\d{4}", parts[1]) and a:
        b = format_date_with_text(_with_year(parts[1], a[:4]))
    return f"{a or parts[0]} ~ {b or parts[1]}"


def _with_year(md: str, year: str) -> str:
    if re.fullmatch(r"\d{4}", md):
        return f"{year}{md}"
    m, d = md.rstrip(".").split(".")
    return f"{year}{int(m):02d}{int(d):02d}"


def _values(v: Any) -> tuple[str, ...]:
    """에디터 _makeValue - 값이 있으면 한 개"""
    s = restore_special_char(v) if isinstance(v, str) else ("" if v is None else str(v))
    return (s,) if s else ()


def _people(v: Any) -> tuple[str, ...]:
    """에디터 _modifyPeopleInfo - 문자열 또는 {name} 목록"""
    out = []
    for x in as_list(v):
        n = x if isinstance(x, str) else as_dict(x).get("name")
        if n:
            out.append(restore_special_char(str(n)))
    return tuple(out)


def _mat(kind: str, title: str, link: str, data_id: Any, details: list[MaterialDetail], sign: Any,
         sub_id: Any = None, vol_no: Any = None, layout: str = "material_basic") -> Material:
    return Material(kind, title, str(link or ""), details, str(data_id or ""), str(sub_id) if sub_id else None,
                    None, str(sign or ""), str(vol_no) if vol_no else None, str(random.randint(1, 9)), layout)


def _book(e: JSONDict) -> Material:
    author = e.get("author")
    a = (restore_special_char(re.sub(r" 지음$", "", author.replace("|", ", "))) if isinstance(author, str)
         else "미등록")
    return _mat("book", restore_special_char(e.get("title")), e.get("linkUrl", ""), e.get("isbn"), [
        MaterialDetail("저자", "author", _values(a)),
        MaterialDetail("출판", "publisher", _values(e.get("publisher"))),
        MaterialDetail("발매", "publishDay", _values(format_date_with_text(e.get("publishDay")))),
        MaterialDetail("발행 연도", "publishYear", _values(format_date_with_text(e.get("publishDay"), True))),
    ], e.get("sign"), e.get("bid"), e.get("volNo") or "")


def _release(theaters: Any, year_only: bool = False) -> tuple[str, ...]:
    out = []
    for t in as_list(theaters):
        v = format_date_with_text(as_dict(t).get("day"), year_only)
        if v:
            out.append(v)
    return tuple(out)


def _movie(e: JSONDict) -> Material:
    return _mat("movie", restore_special_char(as_dict(e.get("titles")).get("korean")), e.get("destinationUrl", ""),
                e.get("mcode"), [
                    MaterialDetail("감독", "directors", _people(as_dict(e.get("directors")).get("directors"))),
                    MaterialDetail("출연", "actors", _people(as_dict(e.get("actors")).get("actors"))),
                    MaterialDetail("개봉", "makingYear", _release(e.get("theaters"))),
                    MaterialDetail("개봉 연도", "newMakingYear", _release(e.get("theaters"), True)),
                    MaterialDetail("개봉", "genre", _values(e.get("genre"))),
                ], e.get("sign"))


def _broadcast(e: JSONDict) -> Material:
    return _mat("broadcast", restore_special_char(e.get("title")), e.get("url", ""), e.get("mcode") or e.get("os"), [
        MaterialDetail("연출", "directors", _people(e.get("producer"))),
        MaterialDetail("출연", "actors", _people(e.get("guest"))),
        MaterialDetail("방송", "makingYear", (str(e.get("year") or ""),)),
        MaterialDetail("장르", "genre", (str(e.get("genre") or ""),)),
        MaterialDetail("채널", "channel", (str(e.get("channel") or ""),)),
    ], e.get("sign"))


def _music(e: JSONDict) -> Material:
    return _mat("music", restore_special_char(e.get("title")), e.get("url", ""), e.get("albumID"), [
        MaterialDetail("아티스트", "artist", _values(str(e.get("artist") or "").replace("|", ", "))),
        MaterialDetail("발매일", "release", _values(format_date_with_text(e.get("release")))),
    ], e.get("sign"), e.get("trackID") or "")


# 쇼핑 상품 유형 표 (에디터 Zn/Lh) [mpTp][prodTp]
_GOODS = [[None, 1, 10, 7, 4, 1, 1, 1, 1], [None, 2, 11, 8, 5, 2, 2, 2, 2], [None, 3, 12, 9, 6, 3, 3, 3, 3]]


def _goods_type(mp: Any, prod: Any) -> Any:
    try:
        return _GOODS[int(mp)][int(prod)]
    except (TypeError, ValueError, IndexError):
        return None


def _shopping(e: JSONDict) -> Material:
    gtype = _goods_type(e.get("mpTp"), e.get("prodTp"))
    n = "null" if gtype is None else str(gtype)
    pid = e.get("id")
    if e.get("mallProductUrl"):
        link = str(e["mallProductUrl"])
    elif gtype in (1, 4):
        link = f"https://search.shopping.naver.com/catalog/{pid}?section=price"
    else:
        link = f"https://search.shopping.naver.com/catalog/{pid}"
    return _mat("shopping", restore_special_char(e.get("productTitle")), link, pid, [
        MaterialDetail("", "type", (n,)),
        MaterialDetail("", "nPayPcType", (str(e.get("nPayPcType") or ""),)),
        MaterialDetail("", "nPayMblType", (str(e.get("nPayMblType") or ""),)),
        MaterialDetail("", "mallNameOrg", (restore_special_char(e.get("mallNameOrg")),)),
        MaterialDetail("", "price", (format_with_comma(e.get("price")),)),
    ], e.get("sign"))


def _news(e: JSONDict) -> Material:
    return _mat("news", restore_special_char(e.get("title")), e.get("orgUrl", ""), e.get("articleId"), [
        MaterialDetail("", "subcontent", (restore_special_char(e.get("subcontent")),)),
        MaterialDetail("출처", "officeHname", (restore_special_char(e.get("officeHname")),)),
    ], e.get("sign"), e.get("officeId"))


def _show(e: JSONDict) -> Material:
    exhibition = str(as_dict(e.get("searchLinkParameter")).get("pkid") or "") != "269"
    title: Any
    genre: Any
    if exhibition:
        title, genre, loc = e.get("name"), "전시", e.get("locationName")
    else:
        title, genre, loc = e.get("title"), e.get("majorGenreName"), as_dict(e.get("placeInformation")).get("name")
    return _mat("show", str(title or ""), e.get("rendingUrl", ""), e.get("objectId"), [
        MaterialDetail("장르", "genre", _values(genre)),
        MaterialDetail("장소", "locationName", _values(loc)),
        MaterialDetail("기간", "period", _values(format_date_range_with_text(e.get("formattedPeriod")))),
    ], e.get("sign"), layout="default")


def _sports(e: JSONDict) -> Material:
    return _mat("sports", str(e.get("teamFullName") or ""), e.get("searchUrl", ""), e.get("categoryId"), [
        MaterialDetail("팀명", "shortName", _values(e.get("teamShortName"))),
        MaterialDetail("종목", "sport", _values(e.get("upperCategoryName"))),
        MaterialDetail("리그", "league", _values(e.get("categoryName"))),
    ], e.get("sign"), e.get("teamCode"), layout="default")


# 부동산 유형 코드 (에디터 상수 Ir.o) [cafe 번들 2026-11-24]
REALESTATE_TYPES = {"A01": "아파트", "A02": "오피스텔", "A04": "재건축", "B01": "아파트 분양권", "B02": "오피스텔 분양권"}


def _flexible_date(v: Any) -> str:
    """에디터 getFlexibleDateFormat (8자리 YYYY.MM.DD. / 6자리 YYYY.MM. / 4자리 YYYY.)"""
    s = "" if v is None else str(v)
    if len(s) == 8:
        return f"{s[:4]}.{s[4:6]}.{s[6:]}."
    if len(s) == 6:
        return f"{s[:4]}.{s[4:]}."
    if len(s) == 4:
        return f"{s}."
    return ""


def normalize_realestate(e: JSONDict) -> JSONDict:
    """통합 검색 부동산 항목 -> 컨버터 입력 (에디터 _normalizeRealEstateItem)"""
    cn = str(e.get("complexNumber") or "")
    pr = as_dict(e.get("dealPriceRange"))
    price = "" if not pr else (str(pr.get("floor")) if pr.get("floor") == pr.get("ceiling")
                               else f"{pr.get('floor')}~{pr.get('ceiling')}")
    return {**e, "id": cn, "title": e.get("name"), "dataId": cn, "subId": "",
            "type": REALESTATE_TYPES.get(str(e.get("type")), ""), "dealPriceRange": price,
            "useApprovalDate": _flexible_date(e.get("useApprovalDate")), "link": e.get("url"),
            "thumbnail": e.get("representativePhotoUrl") or ""}


def _realestate(e: JSONDict) -> Material:
    return _mat("realestate", str(e.get("title") or ""), e.get("link") or "", e.get("dataId"), [
        MaterialDetail("타입", "type", _values(e.get("type"))),
        MaterialDetail("가격", "dealPriceRange", _values(e.get("dealPriceRange"))),
        MaterialDetail("날짜", "useApprovalDate", _values(e.get("useApprovalDate"))),
    ], e.get("sign"), e.get("subId") or None, layout="default")


_MATERIAL_CONVERTERS = {"book": _book, "movie": _movie, "broadcast": _broadcast, "music": _music,
                        "shopping": _shopping, "news": _news, "show": _show, "sports": _sports,
                        "realestate": _realestate}

# 글감 종류별 썸네일 필드 경로 (에디터 컨버터마다 _makeThumbnailInfo 에 넘기는 값) [cafe 번들 2026-11-24]
# 뉴스는 에디터가 /material/news/detail 을 한 번 더 불러 그 응답으로 카드를 만든다 (cafe.editor.materials 가 따라 한다)
MATERIAL_THUMBNAIL_KEYS: dict[str, tuple[str, ...]] = {
    "book": ("bigThumbnail", "thumbnail"),
    "movie": ("imageUrls.thumbnail250",),
    "broadcast": ("image",),
    "music": ("albumImg",),
    "shopping": ("imageUrl",),
    "news": ("images.0.url", "images.image.0.url", "images.image.url"),
    "show": ("imageUrl",),
    "sports": ("logoUrl",),
    "realestate": ("thumbnail",),
}


def material_thumbnail_url(kind: MaterialType | str, item: Any) -> str:
    """검색 항목에서 썸네일 주소 (없으면 "")"""
    for path in MATERIAL_THUMBNAIL_KEYS.get(str(getattr(kind, "value", kind)).lower(), ()):
        v: Any = item
        for k in path.split("."):
            if isinstance(v, list):
                v = v[int(k)] if k.isdigit() and int(k) < len(v) else None
            elif isinstance(v, dict):
                v = v.get(k)
            else:
                v = None
        if isinstance(v, str) and v:
            return v
    return ""


# ---------------------------------------------------------------- 외부 임베드 (oembed)


@dataclass(slots=True)
class Embed(Block):
    """외부 임베드 (oembed) - YouTube 등. 보통 `await cafe.editor.embed(cid, menu, url)`

    [실측 2026-11-24] 에디터 "링크"에 YouTube 주소를 넣으면 /oglink 응답의 oembed + oembedSign 으로 이 컴포넌트를 만든다.
    """

    CTYPE: ClassVar[str] = "oembed"
    url: str = ""                      # inputUrl (사용자가 넣은 주소)
    html: str = ""
    title: str = ""
    type: str = "video"
    version: str = "1.0"
    width: int = 0
    height: int = 0
    author_name: str = ""
    author_url: str = ""
    provider_name: str = ""
    provider_url: str = ""
    thumbnail_url: str = ""
    thumbnail_width: int = 0
    thumbnail_height: int = 0
    description: str = ""
    sign: str = ""
    content_mode: str = "fit"
    layout: str = "default"

    def __post_init__(self) -> None:
        _check_link(self.url)
        if not self.html:
            raise ValueError("Embed 에는 html 이 있어야 합니다 (cafe.editor.embed 로 만드세요)")

    def _body(self) -> JSONDict:
        return {"layout": _s(self.layout), "type": self.type, "version": self.version, "html": self.html,
                "originalWidth": self.width, "originalHeight": self.height, "authorName": self.author_name,
                "authorUrl": self.author_url, "providerName": self.provider_name, "providerUrl": self.provider_url,
                "thumbnailUrl": self.thumbnail_url, "thumbnailWidth": self.thumbnail_width,
                "thumbnailHeight": self.thumbnail_height, "title": self.title, "description": self.description,
                "inputUrl": self.url, "contentMode": self.content_mode, "oembedSign": self.sign}

    @classmethod
    def _parse(cls, d: JSONDict) -> "Embed":
        return cls(str(d.get("inputUrl") or ""), str(d.get("html") or ""), str(d.get("title") or ""),
                   str(d.get("type") or "video"), str(d.get("version") or "1.0"), as_int(d.get("originalWidth")),
                   as_int(d.get("originalHeight")), str(d.get("authorName") or ""), str(d.get("authorUrl") or ""),
                   str(d.get("providerName") or ""), str(d.get("providerUrl") or ""),
                   str(d.get("thumbnailUrl") or ""), as_int(d.get("thumbnailWidth")),
                   as_int(d.get("thumbnailHeight")), str(d.get("description") or ""), str(d.get("oembedSign") or ""),
                   str(d.get("contentMode") or "fit"), str(d.get("layout") or "default"),
                   id=str(d.get("id") or se_id()),
                   extra=_split(d, ("id", "layout", "type", "version", "html", "originalWidth", "originalHeight",
                                    "authorName", "authorUrl", "providerName", "providerUrl", "thumbnailUrl",
                                    "thumbnailWidth", "thumbnailHeight", "title", "description", "inputUrl",
                                    "contentMode", "oembedSign")))

    @classmethod
    def from_api(cls, data: Any, url: str | None = None) -> Self:
        """platform.editor /oglink?url= 응답 (oembed 가 있을 때) -> Embed [실측 2026-11-24 YouTube]"""
        d = as_dict(data)
        o = as_dict(d.get("oembed"))
        if not o.get("html"):
            raise ValueError("임베드할 수 없는 주소입니다 (oembed 없음) - cafe.editor.link_card 를 쓰세요")
        sm = as_dict(as_dict(d.get("oglink")).get("summary"))
        return cls(url or str(as_dict(d.get("oglink")).get("url") or ""), str(o.get("html")), str(o.get("title") or ""),
                   str(o.get("type") or "video"), str(o.get("version") or "1.0"), as_int(o.get("width")),
                   as_int(o.get("height")), str(o.get("authorName") or ""), str(o.get("authorUrl") or ""),
                   str(o.get("providerName") or ""), str(o.get("providerUrl") or ""), str(o.get("thumbnailUrl") or ""),
                   as_int(o.get("thumbnailWidth")), as_int(o.get("thumbnailHeight")),
                   str(sm.get("description") or ""), str(d.get("oembedSign") or ""))

    def texts(self) -> Iterator[str]:
        if self.title:
            yield self.title


# ---------------------------------------------------------------- 카페 전용 (custom: 투표·일정)


@dataclass(slots=True)
class Custom(Block):
    """카페 전용 컴포넌트 (@ctype custom, subtype 으로 구분) - 투표(vote)·일정(schedule)

    모르는 subtype 은 RawBlock 으로 보존된다.
    """

    CTYPE: ClassVar[str] = "custom"
    SUBTYPE: ClassVar[str] = ""
    _SUBTYPES: ClassVar[dict[str, type["Custom"]]] = {}
    layout: str = field(default="default", kw_only=True)
    align: str | None = field(default=None, kw_only=True)

    def __init_subclass__(cls, **kw: Any) -> None:
        if cls.__dict__.get("SUBTYPE"):
            Custom._SUBTYPES[cls.SUBTYPE] = cls

    def _data(self) -> JSONDict:
        raise NotImplementedError

    def _body(self) -> JSONDict:
        return {"align": self.align, "subtype": self.SUBTYPE, "layout": _s(self.layout), "data": self._data()}

    @classmethod
    def _parse(cls, d: JSONDict) -> Block:
        from .blocks import RawBlock

        target = Custom._SUBTYPES.get(str(d.get("subtype") or ""))
        if target is None:
            return RawBlock(data=dict(d))
        try:
            return target._from_data(as_dict(d.get("data")), d)
        except (ValueError, TypeError):
            return RawBlock(data=dict(d))   # 검증에 안 맞는 데이터도 버리지 않고 그대로 보존

    @classmethod
    def _from_data(cls, data: JSONDict, d: JSONDict) -> "Custom":
        raise NotImplementedError

    @staticmethod
    def _common(d: JSONDict) -> JSONDict:
        return {"id": str(d.get("id") or se_id()), "layout": str(d.get("layout") or "default"),
                "align": d.get("align")}


def _ms(t: datetime) -> int:
    if t.tzinfo is None:
        t = t.replace(tzinfo=KST)
    return int(t.timestamp() * 1000)


def _from_ms(v: Any, tz: timezone | None = None) -> datetime | None:
    if v in (None, ""):
        return None
    return datetime.fromtimestamp(int(v) / 1000, tz or KST)


KST = timezone(timedelta(hours=9), "KST")


def _is_url(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(("http://", "https://"))


@dataclass(slots=True)
class VoteItem:
    """투표 항목 - image: 업로드된 사진 주소(http..) / bytes / 파일 경로 / (bytes, 이름) - 주소가 아니면 작성 때 업로드"""

    name: str = ""                       # 빈 이름은 템플릿(AI 채우기)용 - 보낼 때(to_dict) 검사
    image: Any = None
    item_id: Any = field(default=None, kw_only=True)    # 서버가 매긴 itemId (저장된 투표를 다시 보낼 때 그대로)
    extra: JSONDict = field(default_factory=dict, kw_only=True)   # votedByMe·voteCount 등 서버 값 보존


@dataclass(slots=True)
class Vote(Custom):
    """투표 (custom/vote) - 글을 저장하면 서버가 투표를 만든다 (customElements 에 voteId·itemId)

        Vote("점심", ["김밥", "라면", VoteItem("국수", image="noodle.png")],
             multiple=2, secret=False, result_view=VoteResultView.ALWAYS,
             close_at=datetime(2026, 12, 1, 18))

    - multiple: 1 = 하나만, 0 = 무제한, n = 최대 n개 (에디터 selectableCount, 항목 수보다 크면 항목 수)
    - secret: 무기명 (에디터 기본 체크). False 면 viewProperty.showVoterChoice=True
    - close_at / close_voters: 자동 종료 (날짜 / 참여자 수). 둘 다 없으면 자동 종료 없음
    [실측 2026-11-24 에디터 투표 캡처 + 저장 -> customElements VOTE (voteId 19975032)]
    """

    SUBTYPE: ClassVar[str] = "vote"
    title: str = ""
    items: list[Any] = field(default_factory=list)
    multiple: int = 1
    secret: bool = True
    result_view: VoteResultView | str = VoteResultView.AFTER_VOTE
    sort: VoteSort | str = VoteSort.ITEM_INDEX
    close_at: datetime | None = None
    close_voters: int | None = None
    cafe_id: int | None = None          # 작성 때 채운다
    writer_id: str | None = None        # 작성 때 채운다 (로그인 아이디)
    voter_count: int = 0                # 서버 값 (새 투표는 0)

    def __post_init__(self) -> None:
        # 빈 제목·항목 이름은 템플릿(AI 채우기)용으로 허용하고 보낼 때(to_dict) 막는다
        self.items = [i if isinstance(i, VoteItem) else VoteItem(str(i)) for i in self.items]
        if len(self.items) < 2:
            raise ValueError("투표 항목은 2개 이상이어야 합니다")
        if self.multiple < 0:
            raise ValueError("multiple 은 0(무제한) 또는 1 이상입니다")
        if self.close_at is not None and self.close_voters is not None:
            raise ValueError("close_at 과 close_voters 는 하나만 정할 수 있습니다")
        if self.close_voters is not None and self.close_voters < 1:
            raise ValueError("close_voters 는 1 이상입니다")

    @property
    def pending_images(self) -> list[VoteItem]:
        return [i for i in self.items if i.image is not None and not _is_url(i.image)]

    def _data(self) -> JSONDict:
        if not self.title.strip():
            raise ValueError("투표 제목이 비었습니다")
        if any(not i.name.strip() for i in self.items):
            raise ValueError("투표 항목 이름이 비었습니다")
        if self.pending_images:
            raise ValueError("업로드 안 된 투표 사진이 있습니다 - articles.write 에 넘기면 자동으로 올립니다")
        if self.close_at is not None:
            cond, end, cnt = "time", _ms(self.close_at), None
        elif self.close_voters is not None:
            cond, end, cnt = "voter_count", None, self.close_voters
        else:
            cond, end, cnt = "none", None, None
        items = []
        for n, it in enumerate(self.items, 1):
            d: JSONDict = {"itemId": it.item_id, "itemOrder": n, "itemName": it.name}
            if it.image:
                d["itemImageUrl"] = it.image
            d["votedByMe"] = False
            d.update(it.extra)
            items.append(d)
        sel = self.multiple
        sel = min(sel, len(items))  # 에디터 serialize 와 같게
        data: JSONDict = {"cafeId": self.cafe_id, "closeCondition": cond, "closeConditionEndTime": end,
                          "closeConditionVoterCount": cnt, "items": items, "selectableCount": sel,
                          "viewProperty": {"resultItemSortType": _s(self.sort), "showVoterChoice": not self.secret,
                                           "resultViewCondition": _s(self.result_view)},
                          "voteName": self.title, "voteWriterId": self.writer_id, "voterCount": self.voter_count,
                          "isSecret": self.secret}
        return data

    @classmethod
    def _from_data(cls, data: JSONDict, d: JSONDict) -> "Vote":
        vp = as_dict(data.get("viewProperty"))
        known = ("cafeId", "closeCondition", "closeConditionEndTime", "closeConditionVoterCount", "items",
                 "selectableCount", "viewProperty", "voteName", "voteWriterId", "voterCount", "isSecret")
        extra = _split(d, ("id", "layout", "align", "subtype", "data"))
        rest = {k: v for k, v in data.items() if k not in known}
        if rest:
            extra["data"] = rest   # 서버가 붙인 voteId·uuid 등은 data 에 그대로 다시 넣는다
        cond = str(data.get("closeCondition") or "none")
        items = sorted(as_list(data.get("items")), key=lambda x: as_int(as_dict(x).get("itemOrder")))
        item_keys = ("itemId", "itemOrder", "itemName", "itemImageUrl")
        v = cls(title=str(data.get("voteName") or ""),
                items=[VoteItem(str(as_dict(i).get("itemName") or ""), as_dict(i).get("itemImageUrl") or None,
                                item_id=as_dict(i).get("itemId"),
                                extra={k: x for k, x in as_dict(i).items() if k not in item_keys})
                       for i in items],
                voter_count=as_int(data.get("voterCount")),
                multiple=as_int(data.get("selectableCount"), 1), secret=bool(data.get("isSecret", True)),
                result_view=_enum_or_str(VoteResultView, vp.get("resultViewCondition")),
                sort=_enum_or_str(VoteSort, vp.get("resultItemSortType")),
                close_at=_from_ms(data.get("closeConditionEndTime")) if cond == "time" else None,
                close_voters=as_int(data.get("closeConditionVoterCount")) or None if cond == "voter_count" else None,
                cafe_id=as_int(data.get("cafeId")) or None, writer_id=data.get("voteWriterId") or None,
                extra=extra, **cls._common(d))
        return v

    def to_dict(self) -> JSONDict:
        d = Block.to_dict(self)
        sub = self.extra.get("data")
        if isinstance(sub, dict):
            d["data"] = {**self._data(), **sub}
        return d

    def texts(self) -> Iterator[str]:
        yield self.title
        for i in self.items:
            yield i.name


@dataclass(slots=True, frozen=True)
class ScheduleTimeZone:
    """일정 시간대 - 기본 대한민국 서울 [실측 2026-11-24 에디터 기본값]"""

    country_code: str = "KR"
    country_name: str = "대한민국"
    city_id: str = "260"
    city_name: str = "서울"
    time_zone_id: str = "Asia/Seoul"
    gmt: str = "GMT+09:00"
    offset_minute: int = 540

    def to_dict(self) -> JSONDict:
        return {"countryCode": self.country_code, "countryName": self.country_name, "cityId": self.city_id,
                "cityName": self.city_name, "timeZoneId": self.time_zone_id, "gmtString": self.gmt,
                "offsetMinute": self.offset_minute}

    @classmethod
    def from_dict(cls, d: Any) -> Self:
        d = as_dict(d)
        if not d:
            return cls()   # timeZone 이 없으면 에디터 기본값 (서울)
        return cls(str(d.get("countryCode") or "KR"), str(d.get("countryName") or ""), str(d.get("cityId") or ""),
                   str(d.get("cityName") or ""), str(d.get("timeZoneId") or "Asia/Seoul"),
                   str(d.get("gmtString") or ""), as_int(d.get("offsetMinute"), 540))

    @property
    def tz(self) -> timezone:
        return timezone(timedelta(minutes=self.offset_minute))


@dataclass(slots=True)
class Schedule(Custom):
    """일정 (custom/schedule) - 글을 저장하면 서버가 카페 일정(캘린더)을 만든다

        Schedule("정기 모임", datetime(2026, 12, 1, 19), datetime(2026, 12, 1, 21), location="대구역")

    - end 를 비우면 시작 + 1시간 (에디터 기본)
    - all_day: 하루 종일 / important: 중요 일정 / allow_share: 다른 사람이 네이버 캘린더로 담기 허용
    - place: 장소 좌표 (Place, cafe.editor.places 결과) - 지도 첨부
    - 시간대 정보가 없는 datetime 은 time_zone 기준 (기본 서울)
    [실측 2026-11-24] data.uuid 가 있어야 서버가 일정을 만든다 (없으면 customElements 에 json 이 비어 있음).
    에디터처럼 uuid4 를 자동으로 넣는다.
    """

    SUBTYPE: ClassVar[str] = "schedule"
    title: str = ""
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    important: bool = False
    location: str = ""
    place: Place | None = None
    allow_share: bool = False
    time_zone: ScheduleTimeZone = field(default_factory=ScheduleTimeZone)
    uuid: str = field(default_factory=lambda: str(_uuid.uuid4()))
    cafe_id: int | None = None          # 작성 때 채운다

    def __post_init__(self) -> None:
        if self.start is None:
            raise ValueError("Schedule 에는 start(시작 시각)가 필요합니다")
        if self.start.tzinfo is None:
            self.start = self.start.replace(tzinfo=self.time_zone.tz)
        if self.end is None:
            self.end = self.start + timedelta(hours=1)
        elif self.end.tzinfo is None:
            self.end = self.end.replace(tzinfo=self.time_zone.tz)
        if self.end < self.start:
            raise ValueError("일정 종료가 시작보다 빠릅니다")
        if self.place is not None and not self.location:
            self.location = self.place.name

    def _data(self) -> JSONDict:
        if not self.title.strip():
            raise ValueError("일정 제목이 비었습니다")
        assert self.start is not None and self.end is not None
        d: JSONDict = {"cafeId": self.cafe_id, "content": self.title, "startDateTimeStamp": _ms(self.start),
                       "endDateTimeStamp": _ms(self.end), "timeZoneId": self.time_zone.time_zone_id,
                       "timeZone": self.time_zone.to_dict(), "allDay": self.all_day, "priority": self.important,
                       "location": self.location}
        if self.place is not None:
            d.update(address=self.place.address, latitude=self.place.latitude, longitude=self.place.longitude)
        d.update(scrap=self.allow_share, deleted=False, uuid=self.uuid)
        return d

    @classmethod
    def _from_data(cls, data: JSONDict, d: JSONDict) -> "Schedule":
        tz = ScheduleTimeZone.from_dict(data.get("timeZone"))
        known = ("cafeId", "content", "startDateTimeStamp", "endDateTimeStamp", "timeZoneId", "timeZone", "allDay",
                 "priority", "location", "address", "latitude", "longitude", "scrap", "deleted", "uuid")
        extra = _split(d, ("id", "layout", "align", "subtype", "data"))
        rest = {k: v for k, v in data.items() if k not in known}
        if rest:
            extra["data"] = rest
        place = None
        if data.get("latitude") and data.get("longitude"):
            place = Place(str(data.get("location") or ""), float(data["latitude"]), float(data["longitude"]),
                          str(data.get("address") or ""))
        start = _from_ms(data.get("startDateTimeStamp"), tz.tz) or datetime.now(UTC)
        return cls(title=str(data.get("content") or ""), start=start,
                   end=_from_ms(data.get("endDateTimeStamp"), tz.tz) or start, all_day=bool(data.get("allDay")),
                   important=bool(data.get("priority")), location=str(data.get("location") or ""), place=place,
                   allow_share=bool(data.get("scrap")), time_zone=tz, uuid=str(data.get("uuid") or _uuid.uuid4()),
                   cafe_id=as_int(data.get("cafeId")) or None, extra=extra, **cls._common(d))

    def to_dict(self) -> JSONDict:
        d = Block.to_dict(self)
        sub = self.extra.get("data")
        if isinstance(sub, dict):
            d["data"] = {**self._data(), **sub}
        return d

    def texts(self) -> Iterator[str]:
        yield self.title
