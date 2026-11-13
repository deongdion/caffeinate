"""사진 업로드: 에디터 JWT -> 사진 세션키 -> upphoto simpleUpload [실측 2026-11-12]

  1) GET  apis.cafe.naver.com/editor/v2/cafes/{cafeId}/editor?menuId=&from=pc -> result.token, result.userId
  2) GET  platform.editor.naver.com/.../photo-uploader/session-key
          SE-Authorization: <JWT>, SE-App-Id: SE-<uuid> -> {sessionKey}
  3) POST cafe.upphoto.naver.com/{sessionKey}/simpleUpload/0?userId=&extractExif=...  (쿠키 없이, credentials omit)
          multipart 필드명 image -> XML <item> url/path/fileName/width/height/fileSize

2~3단계 헤더/쿼리/쿠키는 브라우저 캡처(2026-11-12)와 동일하게 맞췄다.
[실측 2026-11-13 Aside 캡처] 브라우저는 글쓰기 창을 열 때 1단계를 한 번만 하고, 이미지마다 2~3단계를 반복한다
(세션키는 업로드마다 새로 발급). 그래서 1단계 결과(JWT/userId)와 SE-App-Id 는 (카페, 게시판)별로 잠시 재사용한다.
multipart 이미지 파트는 name=image 하나, Content-Type 은 파일 MIME(image/png, image/jpeg).
댓글 사진은 다른 흐름이다 [실측 2026-11-13 Camoufox UI 캡처]: cafe-mobile/PhotoInfraSessionKey.json(본문 없는 POST)
-> 같은 upphoto simpleUpload (쿼리 extractExif=false, extractAnimatedInfo 없음) -> CommentPost/CommentReply 폼.
에디터 JWT 는 쓰지 않는다 (comment_session_key / upload_comment_image).
본문 이미지가 404 가 되던 원인은 업로드가 아니라 contentJson 의 path 값이었다 (utils/editor.py 참고).
"""
import base64
import binascii
import mimetypes
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from ..core import endpoints
from ..core.errors import NaverAPIError
from ..models import UploadedImage
from ..utils.multipart import FilePart, encode_multipart
from ..utils.parsing import as_dict, dig
from .base import BaseService, CafeLike, ImageLike, image_source

if TYPE_CHECKING:
    from ..lib import Caffeinate


# 글쓰기 창 하나를 연 상태로 보는 시간. JWT 수명은 미확인이라 짧게 잡는다 [추정]
_EDITOR_TTL = 600.0


class PhotoService(BaseService):
    """이미지 업로드 (`cafe.photos`). 보통은 articles.write(images=...) / comments.add(image=...) 가
    알아서 부르므로 직접 쓸 일은 적다. cafe_id 인자는 숫자 ID / slug / 카페 URL 모두 받는다."""

    def __init__(self, client: "Caffeinate") -> None:
        super().__init__(client)
        # (cafe_id, menu_id) -> (token, user_id, app_id, 발급 시각)
        self._editor: dict[tuple[int, int], tuple[str, str, str, float]] = {}

    async def _editor_state(self, cafe_id: int, menu_id: int, *, fresh: bool = False) -> tuple[str, str, str]:
        """글쓰기 창 상태 (JWT, userId, SE-App-Id) - 창을 연 것처럼 한 번 만들고 잠시 재사용"""
        key = (cafe_id, menu_id)
        hit = self._editor.get(key)
        if hit and not fresh and time.monotonic() - hit[3] < _EDITOR_TTL:
            return hit[0], hit[1], hit[2]
        token, user_id = await self.editor_session(cafe_id, menu_id)
        app_id = f"SE-{uuid.uuid4()}"
        self._editor[key] = (token, user_id, app_id, time.monotonic())
        return token, user_id, app_id

    async def editor_session(self, cafe_id: CafeLike, menu_id: int) -> tuple[str, str]:
        """에디터 초기화 -> (JWT 토큰, userId) [실측]. 글쓰기 창을 여는 것과 같다 (로그인 필요)"""
        self._require_login()  # 비로그인이면 500(10004) 대신 로컬에서 NotLoggedInError [실측 2026-11-13]
        cid = await self._cafe_id(cafe_id)
        data = await self.session.get_json(
            endpoints.editor_init(cid),
            params={"menuId": menu_id, "from": "pc"},
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.write_page(cid, menu_id),
        )
        res = dig(data, "result")
        token = dig(res, "token")
        user_id = dig(res, "userId")
        if not token:
            raise NaverAPIError("에디터 토큰 발급 실패 (글쓰기 권한/로그인 확인)", body=str(data)[:500])
        return str(token), str(user_id or "")

    async def editor_token(self, cafe_id: CafeLike, menu_id: int) -> str:
        """에디터 JWT 토큰만 -> str (editor_session 의 첫 값)"""
        token, _ = await self.editor_session(cafe_id, menu_id)
        return token

    async def session_key(
        self, cafe_id: CafeLike, menu_id: int, *, token: str | None = None, app_id: str | None = None
    ) -> str:
        """글쓰기 사진 업로드 세션키 -> str (업로드마다 새로 받는다)

        - token / app_id: 에디터 JWT / SE-App-Id (없으면 새로 만든다)
        """
        cafe_id = await self._cafe_id(cafe_id)
        token = token or await self.editor_token(cafe_id, menu_id)
        data = await self.session.get_json(
            endpoints.PHOTO_SESSION_KEY,
            headers={
                "Pragma": "no-cache",
                "SE-Authorization": token,
                "SE-App-Id": app_id or f"SE-{uuid.uuid4()}",
                "Accept": "application/json",
            },
            referer=endpoints.write_page(cafe_id, menu_id),
        )
        key = as_dict(data).get("sessionKey")
        if not key:
            raise NaverAPIError("사진 세션키 발급 실패", body=str(data)[:500])
        return str(key)

    async def upload(
        self, cafe_id: CafeLike, menu_id: int, data: bytes, filename: str = "image.png"
    ) -> UploadedImage:
        """글쓰기용 이미지 1장 업로드 -> UploadedImage (articles.write/update(images=[...]) 에 넘길 수 있음)

        - data / filename: 이미지 바이트 / 파일명 (MIME 은 확장자, 없으면 파일 시그니처로)

        [실측 2026-11-12] 쿼리는 브라우저 업로더 캡처값 그대로 (_upload_query).

            img = await cafe.photos.upload("deongdion", 1, png_bytes, "a.png")
        """
        cafe_id = await self._cafe_id(cafe_id)
        token, user_id, app_id = await self._editor_state(cafe_id, menu_id)
        try:
            key = await self.session_key(cafe_id, menu_id, token=token, app_id=app_id)
        except NaverAPIError:
            # 재사용한 JWT 가 만료됐을 수 있다 -> 창을 새로 연 것처럼 한 번만 다시
            token, user_id, app_id = await self._editor_state(cafe_id, menu_id, fresh=True)
            key = await self.session_key(cafe_id, menu_id, token=token, app_id=app_id)
        return await self._send(
            key, _upload_query(user_id), data, filename, referer=endpoints.write_page(cafe_id, menu_id)
        )

    async def _send(
        self, key: str, query: dict[str, str], data: bytes, filename: str, *, referer: str
    ) -> UploadedImage:
        """upphoto simpleUpload (쿠키 없이, multipart 파트 name=image 하나)"""
        part = FilePart(name="image", filename=filename, data=data, content_type=_image_mime(filename, data))
        content_type, body = encode_multipart([part])
        resp = await self.session.post(
            endpoints.photo_upload(key),
            params=query,
            data=body,
            headers={"content-type": content_type},
            referer=referer,
            credentials=False,
        )
        if resp.status_code != 200 or "isSuccess>false" in resp.text:
            raise NaverAPIError(f"이미지 업로드 실패 ({resp.status_code})", resp.status_code, resp.text[:500])
        return UploadedImage.from_xml(
            resp.text, domain=endpoints.PHINF_DOMAIN, fallback_name=filename, fallback_size=len(data)
        )

    # ------------------------------------------------------------ 댓글 사진
    async def comment_session_key(self, cafe_id: CafeLike, article_id: int, menu_id: int | None = None) -> str:
        """댓글 사진 업로드 세션키 -> str [실측 2026-11-13 Camoufox UI 캡처]

        댓글 입력창에서 파일을 고르는 즉시 프론트가 보내는 요청:
        POST apis.naver.com/cafe-web/cafe-mobile/PhotoInfraSessionKey.json - 본문 없음(content-length: 0),
        Content-Type / X-Cafe-Product 없음, Referer 는 게시글 iframe URL.
        응답 {"message": {"status": "200", "error": {...}, "result": "<세션키>"}}. 업로드마다 새로 받는다.
        """
        self._require_login()
        cafe_id = await self._cafe_id(cafe_id)
        data = await self.session.post_form(
            endpoints.COMMENT_PHOTO_SESSION_KEY,
            data="",  # 본문 없는 POST (xhr.send(null)) -> content-length: 0
            referer=endpoints.article_frame_page(cafe_id, article_id, menu_id),
        )
        key = dig(data, "message", "result")
        if not key or not isinstance(key, str):
            raise NaverAPIError("댓글 사진 세션키 발급 실패", body=str(data)[:500])
        return key

    async def upload_comment_image(
        self, cafe_id: CafeLike, article_id: int, data: bytes, filename: str = "image.png", *,
        menu_id: int | None = None,
    ) -> UploadedImage:
        """댓글용 이미지 1장 업로드 -> UploadedImage (comments.add/reply(image=...) 에 넘길 수 있음)

        comments.add/reply 에 bytes/경로를 바로 넘기면 이 메서드를 알아서 부른다.

        [실측 2026-11-13 Camoufox UI 캡처] PhotoInfraSessionKey.json -> POST cafe.upphoto.naver.com/{key}/simpleUpload/0
        (쿠키 없음, Accept */*, X-Cafe-Product 없음, Referer 게시글 iframe URL). 쿼리는 글쓰기 업로더와 다르다
        (_comment_upload_query). userId 는 세션키 안에 들어 있는 값을 쓴다.
        """
        cafe_id = await self._cafe_id(cafe_id)
        key = await self.comment_session_key(cafe_id, article_id, menu_id)
        user_id = user_id_from_session_key(key)
        if not user_id:
            _, user_id = await self.editor_session(cafe_id, menu_id or 1)  # [추정] 세션키 형식이 바뀐 경우의 폴백
        return await self._send(
            key, _comment_upload_query(user_id), data, filename,
            referer=endpoints.article_frame_page(cafe_id, article_id, menu_id),
        )

    async def upload_file(self, cafe_id: CafeLike, menu_id: int, path: str | Path) -> UploadedImage:
        """글쓰기용 이미지 파일 1장 업로드 -> UploadedImage (파일명은 경로의 이름)

            img = await cafe.photos.upload_file("deongdion", 1, "a.png")
        """
        p = Path(path)
        return await self.upload(cafe_id, menu_id, p.read_bytes(), p.name)

    async def upload_many(
        self, cafe_id: CafeLike, menu_id: int, images: Iterable[ImageLike]
    ) -> list[UploadedImage]:
        """글쓰기용 이미지 여러 장 -> list[UploadedImage] (입력 순서 유지)

        - images: UploadedImage(그대로 사용) / bytes / 파일 경로(str, Path) / (bytes, 파일명) 튜플 섞어서 가능

        브라우저처럼 한 장씩 순서대로 올린다 (에디터 JWT 는 (카페, 게시판)별로 재사용).
        articles.write/update(images=...) 가 내부에서 이 메서드를 쓴다.
        """
        out: list[UploadedImage] = []
        cid: int | None = None
        for item in images:
            if isinstance(item, UploadedImage):
                out.append(item)
                continue
            if cid is None:
                cid = await self._cafe_id(cafe_id)
            data, name = image_source(item)
            out.append(await self.upload(cid, menu_id, data, name))
        return out


_MAGIC_MIME: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def _image_mime(filename: str, data: bytes) -> str:
    """multipart 파트의 Content-Type.

    브라우저는 파일 선택 시 확장자로 정한 MIME(File.type)을 보내고, 모를 때만
    application/octet-stream 을 쓴다. [실측 2026-11-13 Aside 캡처: 브라우저 파트는 image/png, image/jpeg]
    예전 구현은 항상 octet-stream 이었다. 확장자가 없거나 모르면 파일 시그니처로 판단한다.
    """
    guessed, _ = mimetypes.guess_type(filename)
    if guessed and guessed.startswith("image/"):
        return guessed
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for magic, mime in _MAGIC_MIME:
        if data.startswith(magic):
            return mime
    return "application/octet-stream"


def _upload_query(user_id: str) -> dict[str, str]:
    """브라우저(SmartEditor photoinfra uploader) 업로드 쿼리 - 순서까지 캡처값 그대로"""
    return {
        "userId": user_id,
        "extractExif": "true",
        "extractAnimatedCnt": "false",
        "extractAnimatedInfo": "true",
        "autorotate": "true",
        "extractDominantColor": "false",
        "type": "",
        "customQuery": "",
        "denyAnimatedImage": "false",
        "skipXcamFiltering": "false",
    }


def _comment_upload_query(user_id: str) -> dict[str, str]:
    """댓글 사진 업로더 쿼리 - 순서까지 캡처값 그대로 [실측 2026-11-13 Camoufox UI 캡처]

    글쓰기 업로더(_upload_query)와 달리 extractExif=false 이고 extractAnimatedInfo 가 없다.
    """
    return {
        "userId": user_id,
        "extractExif": "false",
        "extractAnimatedCnt": "false",
        "autorotate": "true",
        "extractDominantColor": "false",
        "type": "",
        "customQuery": "",
        "denyAnimatedImage": "false",
        "skipXcamFiltering": "false",
    }


def user_id_from_session_key(key: str) -> str:
    """댓글 사진 세션키 -> 네이버 아이디 (모르면 "")

    [실측 2026-11-13] 세션키는 base64("발급시각 BEL ms BEL cafe2 BEL {userId} BEL ...") (BEL = 0x07) 이고, 프론트는 같은
    아이디를 업로드 쿼리 userId 로 보낸다.
    """
    try:
        raw = base64.b64decode(key + "=" * (-len(key) % 4), validate=False).decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return ""
    parts = raw.split("\x07")
    return parts[3] if len(parts) > 3 and parts[2].startswith("cafe") else ""
