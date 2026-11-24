"""카페 만들기 (`cafe.cafes.create`) [실측 2026-11-24 Whale 캡처 create.proxymanlog + web-section 프론트 번들]

브라우저 개설 화면(section.cafe.naver.com/ca-fe/home/create)이 보내는 순서 그대로:

  1) GET  view/creations                  주제 목록, 캡차 키, clubTempId, alimCode (화면 열기)
  2) GET  CafeUrlGenerate.json            주소를 비웠을 때 무작위 주소 (화면의 "자동 생성")
     POST validation/cafeUrl|cafeName|introduction|keyword   입력마다 검증 (CLEAR 여야 통과)
  3) GET  directories/{대분류}/sub-directories               주제 소분류
  4) (아이콘) up.cafe.naver.com/PhotoUpload.nhn -> upphoto profileUploader -> upload/0 -> modify -> save/0 -> finish
  5) POST validation/soundCaptcha {csKey, csValue, svcCode: cafecreate}  실패하면 응답의 새 csKey 로 다시
  6) POST v2/create-cafes                 본문 키 순서는 프론트 P() 와 같다 (_create_payload)

API 요청은 모두 axios XHR: Content-Type(application/json) -> X-Cafe-Product: pc, Referer 는 카페 만들기 화면.
"""
import re
import secrets
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from ..core import endpoints
from ..core.config import CAFE_CREATE_PAGE
from ..core.errors import CafeValidationError, CaptchaError, NaverAPIError, ParseError, api_error_class
from ..core.session import error_info
from ..enums import CafeFormField, CaptchaType, RequestKind, ValidationResult
from ..models import (
    CafeCreateOptions,
    CafeManageInfo,
    CaptchaChallenge,
    CreatedCafe,
    CreationInfo,
    Directory,
    FieldValidation,
    Region,
    UploadedImage,
)
from ..models.creation import CREATE_GROUP_ID
from ..utils.multipart import FilePart, encode_multipart
from ..utils.parsing import JSON, as_dict, as_list, dig
from .base import ImageLike, image_source
from .captcha import CaptchaSolverLike, SoundCaptchaOcr, solver_type
from .photos import _image_mime

if TYPE_CHECKING:
    from ..core.session import CafeSession

_URL_GENERATE_TRIES = 5   # 무작위 주소가 검증에 걸리면 다시 받는 횟수
# 아이콘 업로더 modify 명령 - 캡처값 그대로 (400x400 원본이 300x300 으로 저장됨) [실측 2026-11-24]
_ICON_MODIFY_COMMAND = (
    "<items><item><index>0</index><command><width>500</width><height>300</height>"
    "<animationGif>false</animationGif></command></item></items>"
)
_ICON_XHR_HEADERS = {  # jindo XHR: Content-Type + charset 커스텀 헤더, Accept */* [실측 2026-11-24]
    "content-type": "application/x-www-form-urlencoded; charset=utf-8",
    "charset": "utf-8",
    "accept": "*/*",
}
# PhotoUpload.nhn 이 location.href 로 보내는 업로더 주소: domain + '/{세션키}/profileUploader?apiKey=...#origin=...'
_RE_ICON_UPLOADER = re.compile(r"/([A-Za-z0-9_-]{20,})/profileUploader\?([^'\"#\s]+)")
_RE_JS_FIELD = re.compile(r"(\w+)\s*:\s*(\"[^\"]*\"|-?\d+|true|false|null)")


def _result(data: Any) -> JSON:
    """cafe-home 응답의 message.result (dict)"""
    return as_dict(dig(data, "message", "result"))


def _ensure_ok(data: Any, what: str, url: str) -> JSON:
    """message.status 가 200 이 아니면 NaverAPIError 하위 클래스 [번들: 0004 로그인, 0006 그 밖]"""
    status = str(dig(data, "message", "status") or "")
    if status and status != "200":
        code, reason = error_info(data)
        raise api_error_class(None, code)(
            f"{what} 실패 ({code} {reason}): {url}", int(status) if status.isdigit() else None, str(data)[:500], code,
        )
    return _result(data)


class CafeCreationMixin:
    """CafeService 에 섞는 카페 만들기 기능. self 는 CafeService (session / _require_login / id_from_slug)."""

    if TYPE_CHECKING:
        session: CafeSession

        def _require_login(self) -> None: ...
        async def id_from_slug(self, slug: str) -> int: ...
        async def resolve_id(self, value: int | str) -> int: ...

    # ------------------------------------------------------------ 저수준
    async def _home_get(self, url: str, what: str) -> JSON:
        data = await self.session.get_json(url, headers=dict(endpoints.PRODUCT_HEADERS), referer=CAFE_CREATE_PAGE)
        return _ensure_ok(data, what, url)

    async def _home_post(self, url: str, body: JSON, what: str) -> JSON:
        data = await self.session.post_json(
            url, body, headers=dict(endpoints.PRODUCT_HEADERS), referer=CAFE_CREATE_PAGE,
        )
        return _ensure_ok(data, what, url)

    # ------------------------------------------------------------ 화면 정보
    async def creation_info(self) -> CreationInfo:
        """카페 만들기 화면 정보 -> CreationInfo (주제 목록, 캡차 키, 화면 토큰). 로그인 필요

        부를 때마다 새 캡차 키와 clubTempId 가 나온다 [실측 2026-11-24].
        """
        self._require_login()
        res = await self._home_get(endpoints.CAFE_CREATION_VIEW, "카페 만들기 화면 정보")
        info = CreationInfo.from_api({"message": {"result": res}})
        if not info.club_temp_id:
            raise ParseError(f"카페 만들기 화면 정보에 clubTempId 가 없습니다: {str(res)[:300]}")
        return info

    async def sub_directories(self, theme: int) -> list[Directory]:
        """주제 대분류 -> 소분류 목록 (예: ThemeDirectory.TRAVEL -> 동남아/일본/... /항공/여행일반)"""
        res = await self._home_get(endpoints.cafe_sub_directories(int(theme)), "주제 소분류")
        return [Directory.from_api(d, parent_id=int(theme)) for d in as_list(res.get("directories"))]

    async def random_url(self) -> str:
        """서버가 만들어 주는 무작위 카페 주소 (예: "bluegray2rgel") - 화면의 주소 자동 생성"""
        res = await self._home_get(endpoints.CAFE_URL_GENERATE, "카페 주소 생성")
        url = res.get("cafeUrl")
        if not isinstance(url, str) or not url:
            raise ParseError(f"카페 주소 생성 응답에 cafeUrl 이 없습니다: {str(res)[:300]}")
        return url

    async def regions(self, parent: str | None = None, *, overseas: bool = False) -> list[Region]:
        """카페 지역 목록 -> list[Region] (code 를 region_code 로 쓴다) [실측 2026-11-24]

            await cafe.cafes.regions()                 # 시/도: 서울특별시 "09", 대구광역시 "06", ...
            await cafe.cafes.regions("06")             # 대구 시/군/구: 달서구 "06290", ...
            await cafe.cafes.regions(overseas=True)    # 해외: 아시아 "A1017", ...
        """
        url = endpoints.cafe_regions(parent, overseas=overseas)
        data = await self.session.get_json(url, headers=dict(endpoints.PRODUCT_HEADERS), referer=CAFE_CREATE_PAGE)
        rows = as_dict(data).get("result")
        if rows is None:
            rows = _result(data)
        return [Region.from_api(r) for r in as_list(rows)]

    async def manage_info(self, cafe: int | str) -> CafeManageInfo:
        """카페 관리 설정 -> CafeManageInfo (공개 유형, 실명 가입, 주제, 지역, 키워드). 매니저만 [실측 2026-11-24]"""
        self._require_login()
        cid = await self.resolve_id(cafe)
        data = await self.session.get_json(
            endpoints.cafe_manage(cid), headers=dict(endpoints.PRODUCT_HEADERS),
            referer=f"https://cafe.naver.com/ca-fe/cafes/{cid}/manage",  # [추정] 관리 화면
        )
        return CafeManageInfo.from_api(data, cid)

    # ------------------------------------------------------------ 검증
    async def validate(self, field: CafeFormField | str, value: str) -> FieldValidation:
        """입력 1개를 서버에 검증 -> FieldValidation (예외를 내지 않음, .ok / .raise_for_result())

            v = await cafe.cafes.validate(CafeFormField.URL, "onoul")   # result=DUPLICATED
        """
        f = CafeFormField(field)
        res = await self._home_post(endpoints.cafe_validation(f.value), {f.body_key: value}, f"{f.value} 검증")
        return FieldValidation(field=f, value=value, result=ValidationResult(str(res.get("validationResult"))))

    async def is_url_available(self, url: str) -> bool:
        """카페 주소를 쓸 수 있는지 (중복/문자 검사)"""
        return (await self.validate(CafeFormField.URL, url)).ok

    async def validate_options(self, options: CafeCreateOptions) -> list[FieldValidation]:
        """옵션의 이름/주소/소개/키워드를 화면처럼 하나씩 검증 -> 결과 목록 (주소가 None 이면 건너뜀)"""
        checks: list[tuple[CafeFormField, str]] = [(CafeFormField.NAME, options.name)]
        if options.url:
            checks.append((CafeFormField.URL, options.url))
        checks.append((CafeFormField.INTRODUCTION, options.effective_introduction))
        checks += [(CafeFormField.KEYWORD, k) for k in options.keywords]
        return [await self.validate(f, v) for f, v in checks]

    async def validate_captcha(self, challenge: CaptchaChallenge, answer: str) -> tuple[bool, CaptchaChallenge | None]:
        """캡차 답 검증 -> (통과 여부, 실패 시 서버가 준 새 문제 또는 None)

        [실측 2026-11-24] 통과 응답 {"validationResult": "CLEAR"}. 오답이면 {"validationResult": "INVALIDCHARACTER",
        "csKey": 새 키} (이미지면 csImageUrl 도 [번들]). 통과한 키/답은 create-cafes 에 그대로 다시 보낸다.
        """
        res = await self._home_post(
            endpoints.cafe_validation(challenge.type.value),
            {"csKey": challenge.key, "csValue": answer, "svcCode": "cafecreate"},
            "캡차 검증",
        )
        if ValidationResult(str(res.get("validationResult"))).ok:
            return True, None
        key = res.get("csKey")
        if not isinstance(key, str) or not key:
            return False, None
        return False, CaptchaChallenge(type=challenge.type, key=key, image_url=str(res.get("csImageUrl") or ""))

    # ------------------------------------------------------------ 아이콘
    async def upload_icon(self, image: ImageLike, filename: str | None = None) -> UploadedImage:
        """카페 아이콘 업로드 -> UploadedImage (url 을 create-cafes imageUrl 로 보낸다). 로그인 필요

        [실측 2026-11-24] 개설 화면의 "카페아이콘 등록" 팝업 흐름:
          GET  up.cafe.naver.com/PhotoUpload.nhn?mode=CafeProfileUploader&origin=...&msgToken=  (팝업 문서)
               -> 응답 JS 가 cafe.upphoto.naver.com/{세션키}/profileUploader?apiKey=... 로 이동
          POST {세션키}/upload/0?autorotate=true&documentDomain=false&skipXcamFiltering=true
               (iframe 폼, multipart callback_func=uploadCallback + image) -> HTML 콜백 (nWidth/nHeight/sFileURL)
          POST {세션키}/modify  command=<items>...  (XHR) -> <isSuccess>true
          GET  {세션키}/save/0  -> XML <item> url/path/width/height  (url 이 imageUrl)
          GET  {세션키}/finish
        """
        if isinstance(image, UploadedImage):
            return image
        self._require_login()
        data, name = image_source(image, filename)
        s = self.session

        # 1) 팝업 열기 -> 업로더 세션키
        popup_params = {
            "mode": "CafeProfileUploader",
            "origin": "https://section.cafe.naver.com",
            "msgToken": str(secrets.randbelow(9_000_000_000) + 1_000_000_000),  # 10자리 [실측 형식]
        }
        popup_url = f"{endpoints.CAFE_ICON_UPLOADER}?{urlencode(popup_params)}"
        html = await s.get_html(popup_url, referer=CAFE_CREATE_PAGE)
        m = _RE_ICON_UPLOADER.search(html)
        if not m:
            raise ParseError(f"아이콘 업로더 세션키를 찾지 못했습니다: {html[:300]}")
        key, query = m.group(1), m.group(2)
        uploader_url = f"{endpoints.icon_uploader_page(key)}?{query}"
        # 2) JS 이동으로 업로더 화면 (사용자 활성화 아님 -> Sec-Fetch-User 없음) [실측]
        await s.get_html(uploader_url, referer=popup_url, user_activated=False)

        # 3) iframe 폼 업로드
        part = FilePart(name="image", filename=name, data=data, content_type=_image_mime(name, data))
        content_type, body = encode_multipart([part], {"callback_func": "uploadCallback"})
        resp = await s.post(
            endpoints.icon_upload(key),
            params={"autorotate": "true", "documentDomain": "false", "skipXcamFiltering": "true"},
            data=body, headers={"content-type": content_type, "cache-control": "max-age=0"},
            referer=uploader_url, kind=RequestKind.IFRAME, user_activated=False,
        )
        if resp.status_code != 200 or "uploadCallback_success" not in resp.text:
            raise NaverAPIError(f"아이콘 업로드 실패 ({resp.status_code})", resp.status_code, resp.text[:500])

        # 4) 크기 조정 명령 -> 5) 저장 -> 6) 마침
        resp = await s.post(
            endpoints.icon_modify(key), params={"documentDomain": "false"},
            data={"command": _ICON_MODIFY_COMMAND},
            headers={**_ICON_XHR_HEADERS, "content-type": "application/x-www-form-urlencoded; charset=UTF-8"},
            referer=uploader_url,
        )
        if resp.status_code != 200 or "isSuccess>true" not in resp.text:
            raise NaverAPIError(f"아이콘 크기 조정 실패 ({resp.status_code})", resp.status_code, resp.text[:500])
        resp = await s.get(
            endpoints.icon_save(key), params={"documentDomain": "false"}, headers=dict(_ICON_XHR_HEADERS),
            referer=uploader_url,
        )
        if resp.status_code != 200 or "<url>" not in resp.text:
            raise NaverAPIError(f"아이콘 저장 실패 ({resp.status_code})", resp.status_code, resp.text[:500])
        icon = UploadedImage.from_xml(
            resp.text, domain=endpoints.CAFE_ICON_DOMAIN, fallback_name=name, fallback_size=len(data),
        )
        await s.get(
            endpoints.icon_finish(key), params={"documentDomain": "false"}, headers=dict(_ICON_XHR_HEADERS),
            referer=uploader_url,
        )
        return icon

    # ------------------------------------------------------------ 캡차
    async def _solve_captcha(
        self, info: CreationInfo, solver: CaptchaSolverLike, attempts: int,
    ) -> tuple[CaptchaChallenge, str]:
        """풀이기로 캡차를 풀고 서버 검증까지 통과한 (문제, 답). 실패하면 CaptchaError"""
        ctype = solver_type(solver)
        challenge: CaptchaChallenge | None = info.challenge(ctype)
        for _ in range(attempts):
            if challenge is None or not challenge.key:
                # 새 문제를 못 받았으면 화면을 다시 연 것처럼 키를 다시 받는다 [추정]
                fresh = await self.creation_info()
                info.image_captcha_key, info.image_captcha_url = fresh.image_captcha_key, fresh.image_captcha_url
                info.sound_captcha_key = fresh.sound_captcha_key
                challenge = info.challenge(ctype)
            answer = await solver(self.session, challenge)
            if not answer:
                challenge = None
                continue
            ok, refreshed = await self.validate_captcha(challenge, answer)
            if ok:
                return challenge, answer
            challenge = refreshed
        raise CaptchaError(f"캡차를 {attempts}번 안에 풀지 못했습니다 ({ctype.value})")

    # ------------------------------------------------------------ 만들기
    async def create(
        self,
        options: CafeCreateOptions | None = None,
        *,
        icon: ImageLike | None = None,
        captcha_solver: CaptchaSolverLike | None = None,
        validate: bool = True,
        resolve_id: bool = True,
        **fields: Any,
    ) -> CreatedCafe:
        """카페 만들기 -> CreatedCafe. 로그인 필요

            created = await cafe.cafes.create(CafeCreateOptions(name="온울", url="onoulapp"))
            created = await cafe.cafes.create(name="온울", theme=ThemeDirectory.TRAVEL, keywords=["항공권"])

        - options       : CafeCreateOptions. 없으면 **fields 로 만든다 (name= 필수)
        - icon          : 카페 아이콘 (경로/bytes/(bytes, 파일명)/UploadedImage). 없으면 기본 아이콘
        - captcha_solver: 캡차 풀이기. 기본 SoundCaptchaOcr (Settings.sound_captcha_ocr_url)
        - validate      : 화면처럼 입력마다 서버 검증을 먼저 한다 (실패면 CafeValidationError, 캡차 전에 멈춤)
        - resolve_id    : 만든 뒤 cafe.naver.com/{주소} 로 숫자 카페 ID 를 조회한다 (화면도 만든 뒤 이 주소로 이동)

        캡차는 Settings.captcha_max_attempts 번까지 시도하고, 그래도 안 되면 CaptchaError.
        """
        if options is not None and fields:
            raise TypeError("options 와 개별 필드를 함께 줄 수 없습니다")
        opts = options or CafeCreateOptions(**fields)
        self._require_login()
        info = await self.creation_info()

        # 주소: 비었으면 서버 무작위 주소 (검증에 걸리면 다시 받는다)
        url = opts.url
        if url is None:
            for _ in range(_URL_GENERATE_TRIES):
                url = await self.random_url()
                if not validate or await self.is_url_available(url):
                    break
            else:
                raise CafeValidationError(
                    "무작위 카페 주소를 받지 못했습니다", field=CafeFormField.URL.value, value=url or "",
                    result=ValidationResult.DUPLICATED.value,
                )
        if validate:
            for v in await self.validate_options(opts):
                v.raise_for_result()

        sub_theme = opts.sub_theme
        if sub_theme is None:
            subs = await self.sub_directories(int(opts.theme))
            sub_theme = subs[0].dir_id if subs else None

        uploaded = await self.upload_icon(icon) if icon is not None else None

        solver = captcha_solver or SoundCaptchaOcr()
        challenge, answer = await self._solve_captcha(info, solver, self.session.settings.captcha_max_attempts)

        payload = _create_payload(opts, info, str(url), sub_theme, challenge, answer, uploaded)
        res = await self._home_post(endpoints.CAFE_CREATE, payload, "카페 만들기")
        if res.get("result") != "SUCCESS":
            msg = str(res.get("message") or "오류가 발생하였습니다.")
            raise NaverAPIError(f"카페 만들기 실패: {msg}", 200, str(res)[:500])
        club_url = str(res.get("clubUrl") or url)

        cafe_id = 0
        if resolve_id:
            try:
                cafe_id = await self.id_from_slug(club_url)
            except (NaverAPIError, ParseError):
                cafe_id = 0  # 만든 직후 홈이 아직 안 열리는 경우 [추정] - 카페는 만들어졌다
        return CreatedCafe(
            url=club_url, name=opts.name, cafe_id=cafe_id, icon_url=uploaded.url if uploaded else "",
            message=str(res.get("message") or ""), raw=res,
        )


def _create_payload(
    opts: CafeCreateOptions,
    info: CreationInfo,
    url: str,
    sub_theme: int | None,
    challenge: CaptchaChallenge,
    answer: str,
    icon: UploadedImage | None,
) -> JSON:
    """create-cafes 본문 - 키 순서와 값 규칙은 프론트 P() 그대로 [번들, 실측 2026-11-24 캡처와 일치]

    값이 undefined 인 키(rcode, imageUrl, 소분류 없음)는 axios JSON 처럼 빠진다.
    agreeToTerms 는 사용자 체크가 아니라 view/creations 의 agreeyn 에서 온다 (프론트 동작). 약관 동의 이력이 없으면
    False 가 가고 서버가 거절할 수 있다 [추정].
    """
    body: dict[str, Any] = {
        "agreeToPrivacyPolicy": opts.agree_to_privacy_policy,
        "agreeToTerms": info.agreed_terms,
        "alimCode": info.alim_code,
        "clubName": opts.name,
        "clubTempId": info.club_temp_id,
        "clubUrl": url,
        "csKey": challenge.key,
        "csValue": answer,
        "currentThemeDir": int(opts.theme),
        "currentThemeDir2": sub_theme,
        "groupId": CREATE_GROUP_ID,
        "introduction": opts.effective_introduction,
        "isSoundCaptchaMode": challenge.type is CaptchaType.SOUND,
        "keywords": list(opts.keywords),
        "openMemberList": opts.open_member_list,
        "openType": opts.open_type.value,
        "rcode": opts.region_code,
        "useName": "Y" if opts.use_real_name else "N",
        "imageUrl": icon.url if icon else None,
    }
    return {k: v for k, v in body.items() if v is not None}


def parse_icon_callback(html: str) -> dict[str, str]:
    """아이콘 업로드 iframe 콜백 HTML 의 obj = {...} 값들 (디버깅/테스트용)"""
    start = html.find("var obj")
    if start < 0:
        return {}
    chunk = html[start: html.find("};", start)]
    return {k: v.strip('"') for k, v in _RE_JS_FIELD.findall(chunk)}
