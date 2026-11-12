"""사진 업로드: 에디터 JWT -> 사진 세션키 -> upphoto simpleUpload [실측 2026-11-12]

  1) GET  apis.cafe.naver.com/editor/v2/cafes/{cafeId}/editor?menuId=&from=pc -> result.token, result.userId
  2) GET  platform.editor.naver.com/.../photo-uploader/session-key
          SE-Authorization: <JWT>, SE-App-Id: SE-<uuid> -> {sessionKey}
  3) POST cafe.upphoto.naver.com/{sessionKey}/simpleUpload/0?userId=&extractExif=...  (쿠키 없이, credentials omit)
          multipart 필드명 image -> XML <item> url/path/fileName/width/height/fileSize

2~3단계 헤더/쿼리/쿠키는 브라우저 캡처(2026-11-12)와 동일하게 맞췄다.
본문 이미지가 404 가 되던 원인은 업로드가 아니라 contentJson 의 path 값이었다 (utils/editor.py 참고).
"""
import uuid
from pathlib import Path

from ..core import endpoints
from ..core.errors import NaverAPIError
from ..models import UploadedImage
from ..utils.multipart import FilePart, encode_multipart
from ..utils.parsing import as_dict, dig
from .base import BaseService


class PhotoService(BaseService):
    async def editor_session(self, cafe_id: int, menu_id: int) -> tuple[str, str]:
        """에디터 초기화 -> (JWT 토큰, userId) [실측]"""
        data = await self.session.get_json(
            endpoints.editor_init(cafe_id),
            params={"menuId": menu_id, "from": "pc"},
            headers=dict(endpoints.PRODUCT_HEADERS),
            referer=endpoints.write_page(cafe_id, menu_id),
        )
        res = dig(data, "result")
        token = dig(res, "token")
        user_id = dig(res, "userId")
        if not token:
            raise NaverAPIError("에디터 토큰 발급 실패 (글쓰기 권한/로그인 확인)", body=str(data)[:500])
        return str(token), str(user_id or "")

    async def editor_token(self, cafe_id: int, menu_id: int) -> str:
        token, _ = await self.editor_session(cafe_id, menu_id)
        return token

    async def session_key(self, cafe_id: int, menu_id: int, *, token: str | None = None) -> str:
        token = token or await self.editor_token(cafe_id, menu_id)
        data = await self.session.get_json(
            endpoints.PHOTO_SESSION_KEY,
            headers={
                "Pragma": "no-cache",
                "SE-Authorization": token,
                "SE-App-Id": f"SE-{uuid.uuid4()}",
                "Accept": "application/json",
            },
            referer=endpoints.write_page(cafe_id, menu_id),
        )
        key = as_dict(data).get("sessionKey")
        if not key:
            raise NaverAPIError("사진 세션키 발급 실패", body=str(data)[:500])
        return str(key)

    async def upload(self, cafe_id: int, menu_id: int, data: bytes, filename: str = "image.png") -> UploadedImage:
        """이미지 1장 업로드 -> articles.write(images=[...]) 에 넘길 UploadedImage

        [실측 2026-11-12] 쿼리는 브라우저 업로더 캡처값 그대로 (_upload_query).
        """
        token, user_id = await self.editor_session(cafe_id, menu_id)
        key = await self.session_key(cafe_id, menu_id, token=token)
        content_type, body = encode_multipart([FilePart(name="image", filename=filename, data=data)])
        resp = await self.session.post(
            endpoints.photo_upload(key),
            params=_upload_query(user_id),
            data=body,
            headers={"content-type": content_type},
            referer=endpoints.write_page(cafe_id, menu_id),
            credentials=False,
        )
        if resp.status_code != 200 or "isSuccess>false" in resp.text:
            raise NaverAPIError(f"이미지 업로드 실패 ({resp.status_code})", resp.status_code, resp.text[:500])
        return UploadedImage.from_xml(
            resp.text, domain=endpoints.PHINF_DOMAIN, fallback_name=filename, fallback_size=len(data)
        )

    async def upload_file(self, cafe_id: int, menu_id: int, path: str | Path) -> UploadedImage:
        p = Path(path)
        return await self.upload(cafe_id, menu_id, p.read_bytes(), p.name)


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
