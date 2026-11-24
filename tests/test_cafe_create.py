"""카페 만들기 - 오프라인 테스트 (네트워크 없음)

응답 본문은 2026-11-24 Whale 캡처(create.proxymanlog)의 실제 값을 줄여서 쓴다.
"""
import asyncio
import json
import warnings
from typing import Any

import pytest

from caffeinate import (
    Cafe,
    CafeCreateOptions,
    CafeFormField,
    CafeOpenType,
    CafeValidationError,
    Caffeinate,
    CaptchaChallenge,
    CaptchaError,
    CaptchaType,
    CreationInfo,
    ThemeDirectory,
    ValidationResult,
)
from caffeinate.core import endpoints
from caffeinate.core import fingerprint as fp_mod
from caffeinate.core.config import CAFE_CREATE_PAGE
from caffeinate.core.headers import RequestContext, build_headers
from caffeinate.enums import HttpMethod, RequestKind
from caffeinate.models import Cookie, UploadedImage, naver_byte_len
from caffeinate.models.fingerprint import Fingerprint
from caffeinate.services.cafe_create import _create_payload, parse_icon_callback

CREATION_VIEW = {
    "message": {"status": "200", "error": {"code": "", "msg": ""}, "result": {
        "csImageUrl": "https://captcha.nid.naver.com/nhncaptchav4.gif?key=v54fBGnpsVptOP2h",
        "csKey": "v54fBGnpsVptOP2h",
        "themeDirList": [
            {"dirId": 8, "dirType": 1, "dirName": "여행", "dirDepth": 1, "parentDirId": 0, "listOrder": 8},
            {"dirId": 12, "dirType": 1, "dirName": "생활", "dirDepth": 1, "parentDirId": 0, "listOrder": 12},
        ],
        "areaDirList": [{"dirId": 1006, "dirType": 2, "dirName": "대구광역시", "dirDepth": 1, "parentDirId": 0}],
        "cafeGroupList": [], "agreeyn": "Y", "soundCaptchaKey": "PSvXis2638sRf6Vr", "resultCode": "SUCCESS",
        "clubTempId": "2NLy3GQrH/OGmKDV", "alimCode": "K7B0MKK40yECtVu9",
    }},
}
# 캡처의 생성 요청 본문 (키 순서 포함)
CAPTURED_CREATE_BODY = (
    '{"agreeToPrivacyPolicy":true,"agreeToTerms":true,"alimCode":"K7B0MKK40yECtVu9","clubName":"온울",'
    '"clubTempId":"2NLy3GQrH/OGmKDV","clubUrl":"onoulapp","csKey":"PSvXis2638sRf6Vr","csValue":"965873",'
    '"currentThemeDir":8,"currentThemeDir2":192,"groupId":999,"introduction":"패키지, 항공권, 숙소 B2B서비스",'
    '"isSoundCaptchaMode":true,"keywords":["패키지","항공권","숙소","B2B","상세페이지"],"openMemberList":false,'
    '"openType":"O","useName":"N","imageUrl":"/MjAyNjExMjRfODYg/MDAxNzk1NDk1NDI5MDUy.lQfX.PNG/357884075.png"}'
)
ICON_SESSION = "MjAyNjExMjQxMzQzMjIHMTc5NTQ5NjEwNzg1MgdjYWZlX2ljb25fcHJvZmlsZTIHZGVvbmdkaW9u"
ICON_POPUP_HTML = (
    "<script>var domain = isSSL() ? 'https://cafe.upphoto.naver.com' : 'http://cafe.upphoto.naver.com';"
    f"(function(){{ document.location.href = domain + '/{ICON_SESSION}/profileUploader?apiKey=13b19d7ffd5d60fe0e4de8f8"
    "df638560&skipXcamFiltering=true&postMessage=true&windowType=popup#origin=https%3A%2F%2Fsection.cafe.naver.com"
    "&msgToken=3119722119'; })();</script>"
)
ICON_CALLBACK_HTML = (
    "<script>var obj = {\n nIndex:0,\n sFileURL:\"/KEY/0\",\n nHeight:400,\n bNewLine:true,\n nWidth:400,\n"
    " sFileName:\"0\",\n nFileSize:56364\n};\nparent.jindo.FileUploader._oCallback.uploadCallback_success(obj);</script>"
)
ICON_SAVE_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><item><index>0</index>'
    "<url>/MjAyNjExMjRfODYg/MDAxNzk1NDk1NDI5MDUy.lQfX.PNG/357884075.png</url>"
    "<path>/MjAyNjExMjRfODYg/MDAxNzk1NDk1NDI5MDUy.lQfX.PNG</path><fileName>357884075.png</fileName>"
    "<width>300</width><height>300</height><fileSize>34739</fileSize><imageType>PNG</imageType></item>"
)


def _ok(result: Any) -> dict[str, Any]:
    return {"message": {"status": "200", "error": {"code": "", "msg": ""}, "result": result}}


# ---------------------------------------------------------------- 옵션 검사
def test_naver_byte_len_matches_front_rule() -> None:
    assert naver_byte_len("onoul") == 5
    assert naver_byte_len("온울") == 4          # 한글 2바이트
    assert naver_byte_len("B2B서비스") == 9
    assert naver_byte_len("😀") == 4            # 서로게이트 쌍 (JS 코드 단위 2개)


def test_options_defaults_and_normalization() -> None:
    o = CafeCreateOptions(name=" 온울 ", url=" OnoulApp ", keywords=["패키지", " 패키지 ", "", "항공권"])
    assert o.name == "온울"
    assert o.url == "onoulapp"
    assert o.keywords == ("패키지", "항공권")
    assert o.theme is ThemeDirectory.LIFE and o.sub_theme is None
    assert o.open_type is CafeOpenType.OPEN and not o.use_real_name and not o.open_member_list
    assert o.effective_introduction == "온울"     # 소개를 비우면 이름


@pytest.mark.parametrize(
    ("kwargs", "result"),
    [
        ({"name": ""}, "ISEMPTY"),
        ({"name": "가" * 31}, "BYTE"),                          # 62바이트 > 60
        ({"name": "a", "url": "onoul_o"}, "INVALIDCHARACTER"),   # 실측: _ - 불가
        ({"name": "a", "url": "onoul-app"}, "INVALIDCHARACTER"),
        ({"name": "a", "url": "a" * 21}, "BYTE"),
        ({"name": "a", "introduction": "가" * 51}, "BYTE"),
        ({"name": "a", "keywords": [f"k{i}" for i in range(11)]}, "BYTE"),
        ({"name": "a", "keywords": ["가" * 11]}, "BYTE"),
    ],
)
def test_options_local_validation(kwargs: dict[str, Any], result: str) -> None:
    with pytest.raises(CafeValidationError) as ei:
        CafeCreateOptions(**kwargs)
    assert ei.value.result == result
    assert ei.value.hint


def test_options_real_name_needs_approval_join() -> None:
    with pytest.raises(ValueError, match="실명"):
        CafeCreateOptions(name="a", use_real_name=True)
    assert CafeCreateOptions(name="a", use_real_name=True, open_type=CafeOpenType.CLOSED).use_real_name
    with pytest.raises(ValueError, match="지역"):
        CafeCreateOptions(name="a", region_code="1006", open_type=CafeOpenType.HIDDEN)


def test_enums_lenient_and_properties() -> None:
    assert ValidationResult("NEWVALUE") is ValidationResult.UNKNOWN
    assert ValidationResult("CLEAR").ok and not ValidationResult("DUPLICATED").ok
    assert CafeFormField.URL.body_key == "clubUrl"
    assert not CafeOpenType.HIDDEN.is_public and CafeOpenType.CLOSED.allows_real_name


# ---------------------------------------------------------------- 응답/본문
def test_creation_info_from_api() -> None:
    info = CreationInfo.from_api(CREATION_VIEW)
    assert info.club_temp_id == "2NLy3GQrH/OGmKDV" and info.alim_code == "K7B0MKK40yECtVu9"
    assert info.agreed_terms
    assert [t.dir_id for t in info.themes] == [8, 12] and info.themes[0].name == "여행"
    assert info.areas[0].name == "대구광역시"
    sound = info.challenge(CaptchaType.SOUND)
    assert sound.key == "PSvXis2638sRf6Vr" and sound.sound_url.endswith("soundCaptchaEn.wav?key=PSvXis2638sRf6Vr")
    assert info.challenge(CaptchaType.IMAGE).image_url.startswith("https://captcha.nid.naver.com/")


def test_create_payload_matches_capture_byte_for_byte() -> None:
    opts = CafeCreateOptions(
        name="온울", url="onoulapp", theme=ThemeDirectory.TRAVEL, sub_theme=192,
        introduction="패키지, 항공권, 숙소 B2B서비스", keywords=["패키지", "항공권", "숙소", "B2B", "상세페이지"],
    )
    icon = UploadedImage(
        url="/MjAyNjExMjRfODYg/MDAxNzk1NDk1NDI5MDUy.lQfX.PNG/357884075.png", path="", domain="", file_name="x",
    )
    challenge = CaptchaChallenge(type=CaptchaType.SOUND, key="PSvXis2638sRf6Vr")
    body = _create_payload(opts, CreationInfo.from_api(CREATION_VIEW), "onoulapp", 192, challenge, "965873", icon)
    # 세션이 보내는 직렬화와 같은 방식
    assert json.dumps(body, ensure_ascii=False, separators=(",", ":")) == CAPTURED_CREATE_BODY


def test_create_payload_omits_undefined_like_axios() -> None:
    opts = CafeCreateOptions(name="a", region_code="1006")
    challenge = CaptchaChallenge(type=CaptchaType.IMAGE, key="k")
    body = _create_payload(opts, CreationInfo.from_api(CREATION_VIEW), "abc", None, challenge, "x", None)
    assert "imageUrl" not in body and "currentThemeDir2" not in body
    assert body["rcode"] == "1006" and body["isSoundCaptchaMode"] is False
    assert list(body).index("rcode") == list(body).index("openType") + 1


def test_icon_callback_parse() -> None:
    assert parse_icon_callback(ICON_CALLBACK_HTML)["nWidth"] == "400"


def test_cafe_is_manager_from_homepc() -> None:
    assert Cafe.from_api({"cafeId": 1, "manageCafe": True}).is_manager
    assert not Cafe.from_api({"cafeId": 1, "manageCafe": False}).is_manager
    assert not Cafe.from_api({"cafeId": 1}).is_manager
    assert Cafe.from_api({"cafeId": 1, "openType": "H"}).open_type is CafeOpenType.HIDDEN
    assert Cafe.from_api({"cafeId": 1, "openType": "Z"}).open_type is None
    assert Cafe.from_api({"cafeId": 1}).open_type is None


def test_region_and_manage_info_parse() -> None:
    from caffeinate import CafeManageInfo, Region

    gu = Region.from_api({"rcodeType": "DOMESTIC", "type": "DOMESTIC", "rcode": "06290", "name": "달서구",
                          "regionName1": "대구광역시", "regionName2": "달서구", "regionCode1": "06"})
    assert gu.code == "06290" and gu.full_name == "대구광역시 달서구" and not gu.overseas
    asia = Region.from_api({"rcodeType": "OVERSEAS", "rcode": "A1017", "name": "아시아", "regionName1": "아시아"})
    assert asia.overseas and asia.full_name == "아시아"
    assert endpoints.cafe_regions("06") == "https://apis.naver.com/cafe-web/cafe-add-api/v1.0/cafe-region/06/child"
    assert endpoints.cafe_regions(overseas=True).endswith("/cafe-region/overseas/root")
    # 실측 2026-11-24 관리 설정 응답 (줄임)
    info = CafeManageInfo.from_api({"message": {"status": "200", "result": {
        "cafe": {"cafeId": 31822739, "cafeName": "t", "cafeUrl": "bluegray0cyyf", "openType": "O",
                 "enableRealName": False, "introduction": "지역 테스트"},
        "theme": {"themeDir1Id": 24, "themeDir2Id": 364},
        "region": {"regionCodeDetail": {"rcode": "06290", "name": "달서구", "type": "DOMESTIC",
                                        "regionName1": "대구광역시", "regionName2": "달서구"}},
        "cafeKeywordList": [{"keyword": "대구"}, {"keyword": "달서구"}],
    }}})
    assert info.open_type is CafeOpenType.OPEN and info.region_code == "06290"
    assert (info.theme, info.sub_theme) == (24, 364) and info.keywords == ("대구", "달서구")
    hidden = CafeManageInfo.from_api({"message": {"result": {"cafe": {"openType": "H"}, "theme": {
        "themeDir1Id": -1, "themeDir2Id": -1}, "region": {"regionModifiable": True}}}}, 5)
    assert hidden.cafe_id == 5 and hidden.theme == -1 and hidden.region_code == ""


def test_ocr_answer_cleaning() -> None:
    from caffeinate.services.captcha import _clean_answer

    assert _clean_answer(" 51 99662 ") == "5199662"
    assert _clean_answer(".........") is None       # 실측: 못 읽으면 점만 온다
    assert _clean_answer("B9 6C") == "B96C"


# ---------------------------------------------------------------- 헤더 (iframe / audio)
def _fp() -> Fingerprint:
    return fp_mod.builtin()


def test_iframe_form_post_headers() -> None:
    page = f"https://cafe.upphoto.naver.com/{ICON_SESSION}/profileUploader?apiKey=k"
    h = build_headers(_fp(), RequestContext(
        url=f"https://cafe.upphoto.naver.com/{ICON_SESSION}/upload/0", method=HttpMethod.POST,
        kind=RequestKind.IFRAME, referer=page, content_type="multipart/form-data; boundary=x",
        content_length=10, user_activated=False,
    ))
    assert h["sec-fetch-dest"] == "iframe" and h["sec-fetch-mode"] == "navigate"
    assert "sec-fetch-user" not in h
    assert h["origin"] == "https://cafe.upphoto.naver.com"
    assert h["upgrade-insecure-requests"] == "1"


def test_audio_headers_no_cors_without_origin() -> None:
    h = build_headers(_fp(), RequestContext(
        url="https://soundcaptcha.nid.naver.com/soundCaptchaEn.wav?key=k", kind=RequestKind.AUDIO,
        referer=CAFE_CREATE_PAGE, extra={"range": "bytes=0-"},
    ))
    assert h["sec-fetch-dest"] == "audio" and h["sec-fetch-mode"] == "no-cors"
    assert h["sec-fetch-site"] == "same-site"
    assert "origin" not in h and h["range"] == "bytes=0-"
    assert h["accept"].startswith("audio/")


def test_document_still_sends_sec_fetch_user() -> None:
    h = build_headers(_fp(), RequestContext(url="https://cafe.naver.com/x", kind=RequestKind.DOCUMENT))
    assert h["sec-fetch-user"] == "?1" and h["sec-fetch-dest"] == "document"


# ---------------------------------------------------------------- 전체 흐름 (가짜 서버)
class _Headers:
    def get(self, _name: str, default: Any = None) -> Any:
        return default

    def get_list(self, _name: str) -> list[str]:
        return []


class _Resp:
    def __init__(self, status: int = 200, body: Any = None, content: bytes | None = None) -> None:
        self.status_code = status
        if content is not None:
            self.content = content
        elif isinstance(body, str):
            self.content = body.encode()
        else:
            self.content = json.dumps(body, ensure_ascii=False).encode()
        self.text = self.content.decode("utf-8", "replace")
        self.headers = _Headers()

    def json(self) -> Any:
        return json.loads(self.text)


class FakeNaver:
    """URL 별로 캡처 응답을 돌려주고, 보낸 요청을 기록하는 가짜 세션 request()"""

    def __init__(self, *, captcha_fail_first: bool = False, ocr_answers: list[str] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.captcha_fail_first = captcha_fail_first
        self.ocr_answers = list(ocr_answers or ["965873", "111111"])
        self.create_body: Any = None

    async def request(self, method: Any, url: str, **kw: Any) -> _Resp:
        self.calls.append((str(method), url, kw))
        if url == endpoints.CAFE_CREATION_VIEW:
            return _Resp(body=CREATION_VIEW)
        if url == endpoints.CAFE_URL_GENERATE:
            return _Resp(body=_ok({"cafeUrl": "bluegray2rgel"}))
        if url == endpoints.cafe_sub_directories(8):
            return _Resp(body=_ok({"directories": [{"directoryId": 181, "directoryName": "동남아"}]}))
        if url == endpoints.cafe_sub_directories(12):
            return _Resp(body=_ok({"directories": []}))
        if url.startswith(endpoints.cafe_validation("")):
            field = url.rsplit("/", 1)[1]
            body = kw["json_body"]
            if field == "soundCaptcha":
                if self.captcha_fail_first and body["csKey"] == "PSvXis2638sRf6Vr":
                    return _Resp(body=_ok({"validationResult": "FAIL", "csKey": "NEWKEY000000"}))
                return _Resp(body=_ok({"validationResult": "CLEAR"}))
            if body.get("clubUrl") == "onoul":
                return _Resp(body=_ok({"validationResult": "DUPLICATED"}))
            return _Resp(body=_ok({"validationResult": "CLEAR"}))
        if url.startswith("https://soundcaptcha.nid.naver.com/"):
            return _Resp(content=b"RIFF....WAVE")
        if url.startswith("http://49.254.163.248:5000/digits"):
            return _Resp(body={"digits": self.ocr_answers.pop(0)})
        if url == endpoints.CAFE_CREATE:
            self.create_body = kw["json_body"]
            return _Resp(body=_ok({"result": "SUCCESS", "message": "카페 생성에 성공 했습니다.",
                                   "clubUrl": kw["json_body"]["clubUrl"]}))
        if url.startswith(endpoints.CAFE_ICON_UPLOADER):
            return _Resp(body=ICON_POPUP_HTML)
        if "/profileUploader" in url:
            return _Resp(body="<html>uploader</html>")
        if url.endswith("/upload/0"):
            return _Resp(body=ICON_CALLBACK_HTML)
        if url.endswith("/modify"):
            return _Resp(body="<result><isSuccess>true</isSuccess></result>")
        if url.endswith("/save/0"):
            return _Resp(body=ICON_SAVE_XML)
        if url.endswith("/finish"):
            return _Resp(body="<result><isSuccess>true</isSuccess></result>")
        if url.startswith("https://cafe.naver.com/"):
            return _Resp(body="<script>var g_sClubId = \"31822705\"; clubid=31822705</script>")
        raise AssertionError(f"예상 못 한 요청: {method} {url}")

    def urls(self) -> list[str]:
        return [u for _, u, _ in self.calls]


def _client(fake: FakeNaver, monkeypatch: pytest.MonkeyPatch) -> Caffeinate:
    with warnings.catch_warnings():  # 내장 지문 + 로그인 쿠키 조합 경고 (테스트에서는 무관)
        warnings.simplefilter("ignore")
        cafe = Caffeinate(cookies=[Cookie(name="NID_AUT", value="a"), Cookie(name="NID_SES", value="b")])
    monkeypatch.setattr(cafe.session, "request", fake.request)
    return cafe


def test_create_full_flow_with_icon(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeNaver()
    cafe = _client(fake, monkeypatch)
    opts = CafeCreateOptions(name="온울", url="onoulapp", theme=ThemeDirectory.TRAVEL, keywords=["패키지"])
    created = asyncio.run(cafe.cafes.create(opts, icon=(b"\x89PNG\r\n\x1a\nxx", "a.png")))

    assert created.url == "onoulapp" and created.cafe_id == 31822705
    assert created.icon_url.endswith("/357884075.png")
    body = fake.create_body
    assert body["currentThemeDir"] == 8 and body["currentThemeDir2"] == 181   # 첫 소분류 자동
    assert body["csKey"] == "PSvXis2638sRf6Vr" and body["csValue"] == "965873"
    assert body["imageUrl"] == created.icon_url and body["isSoundCaptchaMode"] is True
    urls = fake.urls()
    # 검증 -> 소분류 -> 아이콘 -> 캡차 -> 생성 순서 (화면과 같음)
    order = [
        urls.index(endpoints.cafe_validation("cafeName")),
        urls.index(endpoints.cafe_sub_directories(8)),
        next(i for i, u in enumerate(urls) if u.startswith(endpoints.CAFE_ICON_UPLOADER)),
        urls.index(endpoints.cafe_validation("soundCaptcha")),
        urls.index(endpoints.CAFE_CREATE),
    ]
    assert order == sorted(order)
    # 모든 cafe-home API 는 카페 만들기 화면 Referer + X-Cafe-Product
    for _, u, kw in fake.calls:
        if u.startswith("https://apis.naver.com/"):
            assert kw["referer"] == CAFE_CREATE_PAGE and kw["headers"]["x-cafe-product"] == "pc"
    # 아이콘 업로드는 iframe 폼, OCR 은 쿠키 없이
    up = next(kw for _, u, kw in fake.calls if u.endswith("/upload/0"))
    assert up["kind"] is RequestKind.IFRAME and b'name="callback_func"' in up["data"]
    ocr = next(kw for _, u, kw in fake.calls if u.startswith("http://49.254"))
    assert ocr["credentials"] is False and b'name="audio"; filename="audio.wav"' in ocr["data"]


def test_create_random_url_and_captcha_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeNaver(captcha_fail_first=True)
    cafe = _client(fake, monkeypatch)
    created = asyncio.run(cafe.cafes.create(name="온울", resolve_id=False))
    assert created.url == "bluegray2rgel" and created.cafe_id == 0
    # 첫 답이 틀리면 응답의 새 키로 다시 풀어 그 키/답으로 만든다
    assert fake.create_body["csKey"] == "NEWKEY000000" and fake.create_body["csValue"] == "111111"
    assert "currentThemeDir2" not in fake.create_body    # 생활: 소분류 없음 (가짜 응답)
    assert fake.create_body["introduction"] == "온울"


def test_create_stops_on_server_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeNaver()
    cafe = _client(fake, monkeypatch)
    with pytest.raises(CafeValidationError) as ei:
        asyncio.run(cafe.cafes.create(name="온울", url="onoul"))
    assert ei.value.result == "DUPLICATED" and ei.value.field == "cafeUrl"
    assert endpoints.CAFE_CREATE not in fake.urls()
    assert not any("soundcaptcha" in u for u in fake.urls())   # 캡차 전에 멈춤


def test_create_captcha_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    async def never(_session: Any, _ch: CaptchaChallenge) -> str | None:
        return None

    fake = FakeNaver()
    cafe = _client(fake, monkeypatch)
    cafe.settings.captcha_max_attempts = 2
    with pytest.raises(CaptchaError):
        asyncio.run(cafe.cafes.create(name="온울", url="onoulapp", captcha_solver=never))
    assert endpoints.CAFE_CREATE not in fake.urls()


def test_create_requires_login() -> None:
    from caffeinate import NotLoggedInError

    with pytest.raises(NotLoggedInError):
        asyncio.run(Caffeinate(cookies=[]).cafes.create(name="온울"))
