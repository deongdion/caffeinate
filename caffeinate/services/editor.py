"""에디터 부가 API (platform.editor.naver.com, 에디터 JWT 필요) [실측 2026-11-24]

- 스티커 묶음 / 묶음 안 스티커 -> Sticker (글 블록, 댓글 sticker_id 양쪽에 쓴다)
- 링크 미리보기 -> LinkCard (서버 서명 oglinkSign 포함)

에디터 설정(GET {PLATFORM}/service_config)의 apiInfo.fetchStickers / fetchMultiCrawler 주소다.
요청 헤더 se-authorization 에 글쓰기 창 JWT(photos.editor_session)를 넣는다.
"""
from ..core import endpoints
from ..core.errors import NaverAPIError
from ..enums.editor import LinkCardLayout
from ..models.blocks import LinkCard, Sticker, StickerPack
from ..utils.parsing import as_dict, as_list
from .base import BaseService, CafeLike


class EditorService(BaseService):
    """에디터 부가 기능 (`cafe.editor`) - 스티커, 링크 미리보기. 글쓰기 권한이 있는 (카페, 게시판) 필요"""

    async def _get(self, cafe_id: CafeLike, menu_id: int, url: str, params: dict[str, str] | None = None) -> object:
        self._require_login()
        cid = await self._cafe_id(cafe_id)
        token, _, _ = await self._client.photos._editor_state(cid, menu_id)
        resp = await self.session.get(url, params=params, headers={"se-authorization": token},
                                      referer=endpoints.write_page(cid, menu_id))
        if resp.status_code != 200:
            raise NaverAPIError(f"에디터 API 오류 {resp.status_code}: {url}", body=resp.text[:300])
        return resp.json()

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
