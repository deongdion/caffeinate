"""에디터 부가 API (platform.editor.naver.com 등, 에디터 JWT 필요) [실측 2026-11-24]

- 스티커 묶음 / 묶음 안 스티커 -> Sticker (글 블록, 댓글 sticker_id 양쪽에 쓴다)
- 링크 미리보기 -> LinkCard (서버 서명 oglinkSign 포함), 외부 임베드 -> Embed (oembed + oembedSign)
- 장소 검색 -> Place (지도 블록 Map 재료)
- 글감 검색 -> Material (책·영화·방송·음악·쇼핑·뉴스·공연전시·스포츠·부동산)
- 업로드: 파일(File), 동영상(Video), 투표 항목 사진(VoteItem.image)
- 수식(Formula): 네이버 수식 편집기로 html·이미지를 만든다 (headless Camoufox 로 글쓰기 창을 열어 돌림, 글은 등록 안 함)

에디터 설정(GET {PLATFORM}/service_config)의 apiInfo 주소다.
요청 헤더 se-authorization 에 글쓰기 창 JWT(photos.editor_session)를 넣는다.
요청 모양은 headless Camoufox 로 실제 글쓰기 에디터를 조작해 캡처한 값이다 (각 메서드 주석).
"""
import asyncio
import json
import logging
import math
import mimetypes
import re
import time
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from ..core import endpoints
from ..core.errors import NaverAPIError
from ..enums.editor import LinkCardLayout, MaterialType
from ..models.blocks import Block, Document, LinkCard, Sticker, StickerPack, Thumbnail
from ..models.media import (
    Embed,
    File,
    Formula,
    Material,
    Place,
    Schedule,
    UploadedFile,
    UploadedVideo,
    Video,
    Vote,
    material_thumbnail_url,
)
from ..utils.imagesize import image_size
from ..utils.multipart import FilePart, encode_parts
from ..utils.parsing import as_dict, as_list, dig
from .base import BaseService, CafeLike

# 에디터가 통합 글감 검색에 넣는 종류 (IMAGE 는 사진 블록이 되므로 Material 로 바꾸지 않는다) [실측 2026-11-24]
logger = logging.getLogger("caffeinate")

_UNIFIED_TYPES = ("BOOK", "MUSIC", "SPORTS", "SHOW", "MOVIE", "SHOPPING", "IMAGE", "NEWS", "REALESTATE")
_CHUNK = 5242880     # VOD 업로드 조각 크기 (세션 요청 chunkSize) [실측 2026-11-24]

# nexus postman 진행 조회 GraphQL - 에디터 동영상 업로더가 보내는 문자열 그대로 [실측 2026-11-24]
_Q_HEADER = """{
  _0_0: video(id: "%s", type: ["Ingest", "VideoHeader"]) {
    type
    status
    data {
      ...ingest
      ...videoHeader
    }
    errors {
      code
      message
    }
  }
}

fragment ingest on Ingest {
  videoId
  encodeType
}

fragment videoHeader on VideoHeader {
  videoCodec
  videoBitrate
  audioCodec
  audioBitrate
  audioSamplingRate
  audioChannel
  audioSamplingBit
  duration
  width
  height
  fps
  rotation
  fileSize
}
"""
_Q_ENCODE = """{
  _0_0: video(id: "%s", type: ["VideoHashCode", "Thumbnails", "Encoding", "Hls", "AbrHls"]) {
    type
    status
    data {
      ...videoHashCode
      ...thumbnails
      ...encoding
      ...hls
      ...abrHls
    }
    errors {
      code
      message
    }
  }
}

fragment videoHashCode on VideoHashCode {
  videoMD5
  videoSHA256
}

fragment thumbnails on Thumbnails {
  type
  path
  timeMark
}

fragment encoding on Encoding {
  encoding
  complete
  percentage
  totalFrames
  qualityId
}

fragment hls on Hls {
  status
  qualityId
}

fragment abrHls on AbrHls {
  status
}
"""

# 글쓰기 창 se-launcher 를 AMD 없이 띄우고 에디터 인스턴스를 잡는 훅 (수식 렌더링용)
_SE_HOOK = """
;(function(){ var v = window.SmartEditor; if (!v || v.__cfHooked) return; var orig = v.launch.bind(v);
  v.launch = function(o){ var p = orig(o); p.then(function(e){ window.__cfSE = e; }); return p; };
  v.__cfHooked = true; })();
"""


# 수식 편집기 글자 크기 버튼 nme_fontsize{n} [실측 2026-11-24]
_FORMULA_SIZES = {"fs11": 1, "fs13": 2, "fs15": 3, "fs16": 4, "fs19": 5, "fs24": 6, "fs28": 7, "fs30": 8, "fs34": 9,
                  "fs38": 10}
_PREVIEW_JS = ("[...document.querySelectorAll('.mq-editable-field .mq-root-block')]"
               ".filter(e => e.offsetParent).map(e => e.innerHTML).join('')")
_BLOCK_RE = re.compile(r"\.(?:jpe?g|png|gif|webp|mp4|m3u8)(?:\?|$)|(?:nelo|lcs\.naver|ntm\.pstatic|jackpotlog|tivan)")


def _formula_key(f: Formula) -> tuple[str, str]:
    return f.latex, str(getattr(f.font_size, "value", f.font_size))


def file_source(src: Any, default_name: str) -> tuple[bytes, str]:
    """업로드 입력 -> (데이터, 파일명): bytes / 경로(str, Path) / (bytes, 이름)"""
    if isinstance(src, tuple):
        data, name = src
        return bytes(data), str(name)
    if isinstance(src, bytes | bytearray):
        return bytes(src), default_name
    p = Path(src)
    return p.read_bytes(), p.name


def _mime(name: str, default: str = "application/octet-stream") -> str:
    return mimetypes.guess_type(name)[0] or default


class EditorService(BaseService):
    """에디터 부가 기능 (`cafe.editor`) - 글쓰기 권한이 있는 (카페, 게시판) 필요"""

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        # (latex, 글자 크기) -> (html, thumbnail, font_size, font_family)
        self._formula_cache: dict[tuple[str, str], tuple[Any, Any, Any, Any]] = {}

    async def _se_headers(self, cid: int, menu_id: int) -> tuple[dict[str, str], str]:
        token, user_id, app_id = await self._client.photos._editor_state(cid, menu_id)
        return {"accept": "application/json", "pragma": "no-cache", "se-authorization": token,
                "se-app-id": app_id}, user_id

    async def _get(self, cafe_id: CafeLike, menu_id: int, url: str, params: dict[str, str] | None = None) -> object:
        self._require_login()
        cid = await self._cafe_id(cafe_id)
        token, _, _ = await self._client.photos._editor_state(cid, menu_id)
        resp = await self.session.get(url, params=params, headers={"se-authorization": token},
                                      referer=endpoints.write_page(cid, menu_id))
        if resp.status_code != 200:
            raise NaverAPIError(f"에디터 API 오류 {resp.status_code}: {url}", body=resp.text[:300])
        return resp.json()

    # ------------------------------------------------------------ 스티커 / 링크

    async def sticker_packs(self, cafe_id: CafeLike, menu_id: int) -> list[StickerPack]:
        """스티커 묶음 목록 -> list[StickerPack] (에디터 스티커 패널 순서) [실측 2026-11-24: 16개]"""
        data = await self._get(cafe_id, menu_id, endpoints.SE_STICKERS)
        return [StickerPack.from_api(p) for p in as_list(as_dict(data).get("list"))]

    async def stickers(self, cafe_id: CafeLike, menu_id: int, pack: str | StickerPack) -> list[Sticker]:
        """묶음 안 스티커 -> list[Sticker] [실측 2026-11-24: cafe_001 24개, 185x160 gif]

            pack = (await cafe.editor.sticker_packs(cid, 1))[0]
            st = (await cafe.editor.stickers(cid, 1, pack))[0]
        """
        code = pack.pack_code if isinstance(pack, StickerPack) else pack
        data = await self._get(cafe_id, menu_id, f"{endpoints.SE_STICKERS}/{code}")
        animated = pack.animated if isinstance(pack, StickerPack) else None
        return [Sticker.from_api(s, pack_code=code, animated=animated) for s in as_list(as_dict(data).get("list"))]

    async def all_stickers(self, cafe_id: CafeLike, menu_id: int) -> dict[str, list[Sticker]]:
        """모든 묶음의 스티커 -> {packCode: [Sticker, ...]} (묶음마다 요청 1번)"""
        return {p.pack_code: await self.stickers(cafe_id, menu_id, p)
                for p in await self.sticker_packs(cafe_id, menu_id)}

    async def link_card(
        self, cafe_id: CafeLike, menu_id: int, url: str, *, layout: LinkCardLayout | str = LinkCardLayout.LARGE_IMAGE
    ) -> LinkCard:
        """주소 -> 링크 미리보기 블록 (제목, 설명, 썸네일, 서명) [실측 2026-11-24]"""
        data = await self._get(cafe_id, menu_id, endpoints.SE_OGLINK, {"url": url})
        return LinkCard.from_api(data, layout=layout)

    async def embed(self, cafe_id: CafeLike, menu_id: int, url: str) -> Embed:
        """주소 -> 외부 임베드 블록 (YouTube 등 oembed 지원 주소) [실측 2026-11-24]

        에디터는 "링크" 에 주소를 넣으면 같은 /oglink 응답에 oembed 가 있을 때 임베드로 넣는다.
        oembed 가 없는 주소면 ValueError -> link_card 를 쓴다.
        """
        data = await self._get(cafe_id, menu_id, endpoints.SE_OGLINK, {"url": url})
        return Embed.from_api(data, url)

    # ------------------------------------------------------------ 장소

    async def places(self, cafe_id: CafeLike, menu_id: int, query: str, *, page: int = 1,
                     count: int = 7) -> list[Place]:
        """장소 검색 -> list[Place] (Map 블록 재료) [실측 2026-11-24 에디터 "장소" 검색]

        GET platform.editor .../map/naver/places?query=&siteSort=0&displayCount=7&page=1
        """
        data = await self._get(cafe_id, menu_id, endpoints.SE_PLACES,
                               {"query": query, "siteSort": "0", "displayCount": str(count), "page": str(page)})
        return [Place.from_api(p) for p in as_list(dig(data, "result", "place", "list"))]

    # ------------------------------------------------------------ 글감

    async def materials(
        self, cafe_id: CafeLike, menu_id: int, query: str,
        kinds: Iterable[MaterialType | str] | None = None, *, count: int = 8, thumbnails: bool = True,
    ) -> list[Material]:
        """글감 검색 -> list[Material] (바로 블록으로 넣을 수 있음) [실측 2026-11-24 에디터 글감 검색]

        - kinds: 원하는 종류만 (기본: 에디터와 같은 전부 + 방송)
        - thumbnails: 썸네일 크기를 재려고 이미지를 받는다 (에디터와 같은 방식, 끄면 썸네일 없음)

        에디터와 같이 통합 검색(/material/search) + 방송(/v2/material/broadcast) 을 부르고,
        뉴스는 넣을 때처럼 /material/news/detail 을 다시 불러 그 응답으로 만든다.
        """
        want = {str(getattr(k, "value", k)).lower() for k in kinds} if kinds is not None else None
        cid = await self._cafe_id(cafe_id)
        out: list[Material] = []
        unified = [t for t in _UNIFIED_TYPES if t != "IMAGE" and (want is None or t.lower() in want)]
        if unified:
            types = _UNIFIED_TYPES if want is None else tuple(unified)
            data = await self._get(cid, menu_id, endpoints.SE_MATERIALS,
                                   {"q": query, "count": str(count), "types": ",".join(types),
                                    "image.paidType": "F"})
            for group in as_list(as_dict(data).get("results")):
                g = as_dict(group)
                kind = str(g.get("type") or "").lower()
                if kind == "image" or (g.get("status") and g.get("status") != "SUCCESS"):
                    continue
                for item in as_list(g.get("items")):
                    if kind == "news":
                        item = await self._news_detail(cid, menu_id, as_dict(item))
                    out.append(await self._material(kind, item, thumbnails))
        if want is None or "broadcast" in want:
            data = await self._get(cid, menu_id, endpoints.SE_BROADCASTS,
                                   {"q": query, "count": str(count), "pageToken": "start"})
            for item in as_list(as_dict(data).get("items")):
                out.append(await self._material("broadcast", item, thumbnails))
        return out

    async def _news_detail(self, cid: int, menu_id: int, item: dict[str, Any]) -> dict[str, Any]:
        data = await self._get(cid, menu_id, endpoints.SE_NEWS_DETAIL,
                               {"oid": str(item.get("officeId") or item.get("subId") or ""),
                                "aid": str(item.get("articleId") or item.get("dataId") or "")})
        return as_dict(dig(data, "items", 0)) or item

    async def _material(self, kind: str, item: Any, thumbnails: bool) -> Material:
        thumb = None
        if thumbnails:
            from ..models.media import normalize_realestate

            src_item = normalize_realestate(as_dict(item)) if kind == "realestate" else item
            thumb = await self.measure_image(material_thumbnail_url(kind, src_item))
        return Material.from_search(kind, item, thumbnail=thumb)

    async def measure_image(self, url: str) -> Thumbnail | None:
        """이미지 주소 -> Thumbnail(크기 포함). 못 받거나 모르는 형식이면 None (에디터 _makeThumbnailInfo 와 같음)"""
        if not url:
            return None
        try:
            resp = await self.session.get(url, credentials=False, headers={"accept": "image/avif,image/webp,*/*"})
        except Exception:  # noqa: BLE001 - 에디터도 이미지 오류면 썸네일 없이 넣는다
            return None
        size = image_size(resp.content) if resp.status_code == 200 else None
        if not size:
            return None
        return Thumbnail(src=url, width=size[0], height=size[1])

    # ------------------------------------------------------------ 파일

    async def upload_file(self, cafe_id: CafeLike, menu_id: int, source: Any,
                          filename: str | None = None) -> UploadedFile:
        """파일 첨부 업로드 -> UploadedFile [실측 2026-11-24 에디터 "파일 > 내 컴퓨터"]

        POST upapi.cafe.naver.com/v1.0/cafes/editor/files  multipart userId, file
        헤더 se-authorization / se-app-id / accept json / pragma no-cache -> {fileId, fileName, fileSize}
        """
        self._require_login()
        data, name = file_source(source, filename or "file")
        name = filename or name
        if len(data) > 50 * 1024 * 1024:
            raise ValueError("첨부 파일은 50MB 까지입니다 (에디터 fileUploadLimitFileSize)")
        cid = await self._cafe_id(cafe_id)
        headers, user_id = await self._se_headers(cid, menu_id)
        ctype, body = encode_parts([("userId", user_id),
                                    FilePart(name="file", filename=name, data=data, content_type=_mime(name))])
        resp = await self.session.post(endpoints.SE_FILE_UPLOAD, data=body,
                                       headers={**headers, "content-type": ctype},
                                       referer=endpoints.write_page(cid, menu_id))
        if resp.status_code != 200:
            raise NaverAPIError(f"파일 업로드 실패 ({resp.status_code})", resp.status_code, resp.text[:300])
        return UploadedFile.from_api(resp.json())

    # ------------------------------------------------------------ 투표 사진

    async def upload_vote_image(self, cafe_id: CafeLike, menu_id: int, source: Any,
                                filename: str | None = None) -> str:
        """투표 항목 사진 업로드 -> 사진 주소 (VoteItem.image 에 넣는 값) [실측 2026-11-24]

        POST upapi.cafe.naver.com/v1.0/cafes/{cafeId}/images/poll (쿠키 포함, accept */*)
        multipart 순서: animatedImage=false, imagefile, requestInputId, name, type, file
        응답 result.deliveryUrl 을 itemImageUrl 로 쓴다.
        """
        self._require_login()
        data, name = file_source(source, filename or "image.png")
        name = filename or name
        mime = _mime(name, "image/png")
        cid = await self._cafe_id(cafe_id)
        ctype, body = encode_parts([
            ("animatedImage", "false"),
            FilePart(name="imagefile", filename=name, data=data, content_type=mime),
            ("requestInputId", f"temp-{uuid.uuid4()}"),
            ("name", name),
            ("type", mime),
            FilePart(name="file", filename=name, data=data, content_type=mime),
        ])
        resp = await self.session.post(endpoints.poll_image_upload(cid), data=body,
                                       headers={"accept": "*/*", "content-type": ctype},
                                       referer=endpoints.write_page(cid, menu_id))
        if resp.status_code != 200:
            raise NaverAPIError(f"투표 사진 업로드 실패 ({resp.status_code})", resp.status_code, resp.text[:300])
        res = as_dict(resp.json())
        url = as_dict(res.get("result") or res).get("deliveryUrl")
        if not url:
            raise NaverAPIError("투표 사진 업로드 응답에 deliveryUrl 이 없습니다", body=resp.text[:300])
        return str(url)

    # ------------------------------------------------------------ 동영상

    async def upload_video(
        self, cafe_id: CafeLike, menu_id: int, source: Any, filename: str | None = None, *,
        timeout: float = 900.0, interval: float = 2.0,
    ) -> UploadedVideo:
        """동영상 업로드 + 인코딩 대기 -> UploadedVideo [실측 2026-11-24 에디터 동영상 업로더 캡처]

        1) GET platform.editor .../v2/video-uploader/token -> {token, videoId, data.serviceId, userId}
        2) POST nexus.vod.naver.com/warp/{serviceId}/upload/v4/{videoId}/sessions -> {key, servers}
        3) POST https://{server}/upload/v2/files - 5MB 조각마다 multipart (chunkIndex 1부터)
        4) POST nexus.vod.naver.com/postman/api/v1/files (GraphQL) - 헤더 -> 인코딩·썸네일 완료까지
        5) POST nexus.vod.naver.com/orbit/{serviceId}/thumbnails/v2/cover/{videoId} - 대표 장면 지정
        에디터 한도: 4GB, 15분 (토큰 응답 fileSizeLimit / durationLimit).
        """
        self._require_login()
        data, name = file_source(source, filename or "video.mp4")
        name = filename or name
        cid = await self._cafe_id(cafe_id)
        referer = endpoints.write_page(cid, menu_id)
        headers, _ = await self._se_headers(cid, menu_id)
        resp = await self.session.get(endpoints.SE_VIDEO_TOKEN, headers=headers, referer=referer)
        if resp.status_code != 200:
            raise NaverAPIError(f"동영상 토큰 발급 실패 ({resp.status_code})", resp.status_code, resp.text[:300])
        tok = as_dict(resp.json())
        info = as_dict(tok.get("data"))
        service_id = info.get("serviceId") or 5
        video_id = str(tok.get("videoId") or "")
        limit = int(info.get("fileSizeLimit") or 0)
        if limit and len(data) > limit:
            raise ValueError(f"동영상이 너무 큽니다 ({len(data)} > {limit} bytes)")
        sess = await self._vod_json(endpoints.vod_session(service_id, video_id), {
            "token": tok.get("token"), "userId": info.get("userId"), "serviceId": service_id, "chunkSize": _CHUNK,
            "fileName": name, "fileSize": len(data), "chunkUpload": True}, referer)
        key = str(sess.get("key") or "")
        servers = as_list(sess.get("servers"))
        if not key or not servers:
            raise NaverAPIError("동영상 업로드 세션 실패", body=json.dumps(sess)[:300])
        chunk = int(sess.get("chunkSize") or _CHUNK)
        upload_url = f"https://{servers[0]}/upload/v2/files"
        total = max(1, math.ceil(len(data) / chunk))
        for i in range(total):
            part = data[i * chunk:(i + 1) * chunk]
            ctype, body = encode_parts([
                ("key", key), ("fileName", name), ("fileSize", str(len(data))), ("chunkIndex", str(i + 1)),
                ("chunkSize", str(chunk)), ("currentChunkSize", str(len(part))), ("chunkUpload", "true"),
                FilePart(name="file", filename=name, data=part, content_type=_mime(name, "video/mp4")),
            ])
            r = await self.session.post(upload_url, data=body, headers={"accept": "*/*", "content-type": ctype},
                                        referer=referer, credentials=False)
            if r.status_code != 200 or not as_dict(r.json()).get("result"):
                raise NaverAPIError(f"동영상 조각 {i + 1}/{total} 업로드 실패 ({r.status_code})", r.status_code,
                                    r.text[:300])
        deadline = time.monotonic() + timeout
        header = await self._vod_wait(key, _Q_HEADER, ("VideoHeader",), deadline, interval, referer)
        done = await self._vod_wait(key, _Q_ENCODE, ("Thumbnails", "Encoding", "Hls"), deadline, interval, referer)
        vh = as_dict(as_list(header["VideoHeader"].get("data"))[0] if as_list(header["VideoHeader"].get("data"))
                     else {})
        scenes = [as_dict(t) for t in as_list(done["Thumbnails"].get("data"))]
        cover = next((t["path"] for t in scenes if t.get("type") == "SCENE" and t.get("path")), "")
        cover = cover or next((t["path"] for t in scenes if t.get("path")), "")
        if cover:
            await self._vod_json(endpoints.vod_cover(service_id, video_id),
                                 {"path": cover, "key": key, "policy": "NEW"}, referer)
        w, h = int(vh.get("width") or 0), int(vh.get("height") or 0)
        if int(vh.get("rotation") or 0) in (90, 270):
            w, h = h, w
        return UploadedVideo(video_id, len(data), math.floor(float(vh.get("duration") or 0)), w, h, cover,
                             str(service_id))

    async def _vod_json(self, url: str, body: dict[str, Any], referer: str) -> dict[str, Any]:
        resp = await self.session.post(
            url, data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(),
            headers={"accept": "*/*", "content-type": "application/json; charset=UTF-8"}, referer=referer,
            credentials=False)
        if resp.status_code != 200:
            raise NaverAPIError(f"동영상 API 오류 {resp.status_code}: {url}", resp.status_code, resp.text[:300])
        return as_dict(resp.json())

    async def _vod_wait(self, key: str, query: str, need: Sequence[str], deadline: float, interval: float,
                        referer: str) -> dict[str, dict[str, Any]]:
        """postman 조회를 need 가 모두 done 일 때까지 반복 -> {type: 항목}"""
        body = json.dumps({"query": query % key}, ensure_ascii=False, separators=(",", ":")).encode()
        while True:
            resp = await self.session.post(VOD_POSTMAN, data=body,
                                           headers={"accept": "*/*", "content-type": "text/plain"},
                                           referer=referer, credentials=False)
            items = {str(as_dict(x).get("type")): as_dict(x)
                     for x in as_list(dig(resp.json() if resp.status_code == 200 else {}, "data", "_0_0"))}
            failed = [t for t, x in items.items() if x.get("status") in ("fail", "failed", "error")]
            if failed:
                raise NaverAPIError(f"동영상 처리 실패: {failed}", body=json.dumps(items, ensure_ascii=False)[:500])
            if all(items.get(t, {}).get("status") == "done" for t in need):
                return items
            if time.monotonic() > deadline:
                raise TimeoutError(f"동영상 처리 대기 시간 초과: { {t: items.get(t, {}).get('status') for t in need} }")
            await asyncio.sleep(interval)

    # ------------------------------------------------------------ 수식

    async def render_formulas(self, cafe_id: CafeLike, menu_id: int, formulas: Sequence[Formula], *,
                              timeout: float = 60.0) -> None:
        """Formula 의 html·이미지를 네이버 수식 편집기로 만든다 (제자리에서 채움) [실측 2026-11-24]

        headless Camoufox 로 글쓰기 창을 열고, 툴바 "수식" -> latex 입력 -> "입력" 을 누른 뒤
        에디터가 만든 formula 컴포넌트(html = mathquill 마크업, thumbnail = 사진 업로더로 올린 PNG)를 읽는다.
        글은 등록하지 않는다. 글 보기 화면은 html 을 그리므로 직접 만든 html 은 쓰지 않는다
        (<img>·MathML 은 보기 화면이 글자로 내보내거나 저장이 거부된다 - 실측).
        글자 크기는 `Formula.font_size` (fs11~fs38) 를 수식 편집기에서 골라 렌더한다.
        """
        todo: list[Formula] = []
        for f in formulas:
            if f.rendered:
                continue
            if not f.latex.strip():
                raise ValueError("Formula 에는 latex 가 있어야 합니다")
            hit = self._formula_cache.get(_formula_key(f))
            if hit is not None:   # 같은 수식·크기는 다시 렌더하지 않는다 (이미지는 공용 주소)
                f.html, f.thumbnail, f.font_size, f.font_family = hit
            else:
                todo.append(f)
        if not todo:
            return
        self._require_login()
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("수식 렌더링에는 camoufox 가 필요합니다 (python -m camoufox fetch)") from e
        cid = await self._cafe_id(cafe_id)
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path or "/",
                    "secure": c.secure, "httpOnly": c.http_only}
                   for c in self.session.cookies if not c.is_expired]
        from ..auth.login import load_preset

        # 고정 기기 프리셋 (로그인 창과 같은 지문). 없으면 첫 실행에 지문 생성으로 ~12s 걸린다 [실측 12.7s -> 1.3s]
        launch: dict[str, Any] = {"headless": True, "main_world_eval": True, "i_know_what_im_doing": True,
                                  "os": "windows",
                                  "fingerprint_preset": load_preset(self.session.settings.browser_preset_file)}
        proxy = getattr(self.session.settings, "proxy", None)
        if proxy:
            launch["proxy"] = {"server": proxy}
        t0 = time.monotonic()
        # 영구 프로필: 에디터 번들 캐시를 다음 실행에서 재사용 [실측 첫 준비 10.6s -> 3.2s]
        prof = self.session.settings.editor_profile_dir
        prof.mkdir(parents=True, exist_ok=True)
        launch.update(persistent_context=True, user_data_dir=str(prof))
        async with AsyncCamoufox(**launch) as browser:
            ctx: Any = browser   # persistent_context 면 BrowserContext
            logger.debug("수식: 브라우저 %.1fs", time.monotonic() - t0)
            await ctx.add_cookies(cookies)

            async def patch(route: Any) -> None:
                r = await route.fetch()
                body = (await r.text()).replace('"function"==typeof define&&define.amd', "false", 1) + _SE_HOOK
                await route.fulfill(response=r, body=body)

            await ctx.route("**/se-launcher.js", patch)

            async def block(route: Any) -> None:
                await route.abort()

            # 수식 렌더에 필요 없는 것 (사진·동영상·통계) - 글꼴·스타일은 렌더에 쓰이므로 둔다
            await ctx.route(_BLOCK_RE, block)
            page = await ctx.new_page()
            await page.goto(endpoints.write_page(cid, menu_id), wait_until="commit")

            async def ev(js: str) -> Any:
                return await page.evaluate("mw:" + js)

            end = time.monotonic() + timeout
            while not await ev("!!window.__cfSE"):
                if time.monotonic() > end:
                    raise TimeoutError("글쓰기 에디터를 열지 못했습니다 (로그인·글쓰기 권한 확인)")
                await asyncio.sleep(0.2)
            count_js = ("window.__cfSE.getDocumentData().document.components"
                        ".filter(c => c['@ctype'] === 'formula' && c.thumbnail && c.thumbnail.src)")
            logger.debug("수식: 에디터 준비 %.1fs", time.monotonic() - t0)
            for f in todo:
                t1 = time.monotonic()
                before = len(await ev(count_js))
                await page.click('.se-document-toolbar button[data-name="formula"]')
                ta = page.locator("textarea.nme_script_editor:visible").first
                await ta.wait_for(timeout=timeout * 1000)
                size = _FORMULA_SIZES.get(str(getattr(f.font_size, "value", f.font_size)))
                if size is None:
                    raise ValueError(f"수식 글자 크기는 {list(_FORMULA_SIZES)} 중 하나입니다: {f.font_size!r}")
                if size != 3:   # 편집기 기본 15 (nme_fontsize3) [실측 2026-11-24 크기 목록 11~38]
                    await page.click(".nme_tool_fontsize")
                    await page.click(f"button.nme_fontsize{size}")
                await ta.fill(f.latex)
                stale = await ev(_PREVIEW_JS)
                # 미리보기는 키 입력으로 갱신된다 (fill 만으로는 빈 수식) [실측]
                await ta.press("End")
                await ta.type(" ")
                await ta.press("Backspace")
                end = time.monotonic() + timeout
                while True:   # 미리보기가 새 수식으로 바뀔 때까지
                    now = await ev(_PREVIEW_JS)
                    if now and now != stale:
                        break
                    if time.monotonic() > end:
                        raise TimeoutError(f"수식 미리보기가 그려지지 않습니다: {f.latex!r}")
                    await asyncio.sleep(0.1)
                await ev("[...document.querySelectorAll('button')]"
                         ".filter(b => b.innerText.trim() === '입력' && b.offsetParent).pop().click()")
                end = time.monotonic() + timeout
                while True:
                    comps = await ev(count_js)
                    if len(comps) > before:
                        break
                    if time.monotonic() > end:
                        raise TimeoutError(f"수식 렌더링 시간 초과: {f.latex!r}")
                    await asyncio.sleep(0.2)
                c = comps[-1]
                th = as_dict(c.get("thumbnail"))
                f.html = str(c.get("html") or "")
                f.thumbnail = Thumbnail(src=str(th.get("src")), width=int(th.get("width") or 0),
                                        height=int(th.get("height") or 0))
                f.font_size = str(c.get("fontSizeCode") or f.font_size)
                f.font_family = str(c.get("fontFamily") or f.font_family)
                self._formula_cache[_formula_key(f)] = (f.html, f.thumbnail, f.font_size, f.font_family)
                logger.debug("수식: %r %.1fs", f.latex, time.monotonic() - t1)

    # ------------------------------------------------------------ 작성 전 준비

    async def prepare(self, cafe_id: CafeLike, menu_id: int, blocks: Document | Sequence[Block]) -> None:
        """블록의 업로드·서버 값 채우기 (articles.write/update 가 부른다)

        파일·동영상 업로드, 투표 사진 업로드와 cafeId·작성자 채우기, 일정 cafeId, 수식 렌더링.
        """
        items = blocks.blocks if isinstance(blocks, Document) else list(blocks)
        if not items:
            return
        cid = await self._cafe_id(cafe_id)
        formulas: list[Formula] = []
        user_id: str | None = None
        for b in items:
            if isinstance(b, File) and b.uploaded is None:
                b.source = await self.upload_file(cid, menu_id, b.source)
            elif isinstance(b, Video) and b.uploaded is None:
                b.source = await self.upload_video(cid, menu_id, b.source)
            elif isinstance(b, Vote):
                for it in b.pending_images:
                    it.image = await self.upload_vote_image(cid, menu_id, it.image)
                if b.cafe_id is None:
                    b.cafe_id = cid
                if b.writer_id is None:
                    if user_id is None:
                        _, user_id, _ = await self._client.photos._editor_state(cid, menu_id)
                    b.writer_id = user_id
            elif isinstance(b, Schedule) and b.cafe_id is None:
                b.cafe_id = cid
            elif isinstance(b, Formula) and not b.rendered:
                formulas.append(b)
        if formulas:
            await self.render_formulas(cid, menu_id, formulas)


VOD_POSTMAN = endpoints.VOD_POSTMAN
