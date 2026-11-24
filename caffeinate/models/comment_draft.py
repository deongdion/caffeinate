"""댓글 본문 블록 - 글과 같은 블록(Text, Sticker, Image)으로 댓글을 만든다 [실측 2026-11-24]

    from caffeinate import CommentDraft, Image, Sticker, Text

    await cafe.comments.add(ref, ["첫 줄\\n둘째 줄", sticker, Image("a.png")])
    await cafe.comments.add(ref, CommentDraft("본문", sticker=sticker, image="a.png"))
    await cafe.comments.reply(ref, parent_id, [sticker])          # 스티커만

댓글 폼이 받는 것은 글(content), 스티커(stickerId) 1개, 사진 1장뿐이다. 그래서 블록 중 Text/문자열/Sticker/Image 만
받는다. 서식(굵게·색·링크)은 ValueError, 다른 블록은 TypeError 로 알린다 (서버에 서식 필드가 없다).

서버 동작 [실측 2026-11-24, 글 pinkd67zt/2 의 댓글]
- 여러 줄·빈 줄 그대로 저장, HTML/주소는 글자 그대로 (서식 없음)
- 스티커 + 사진 + 글 동시에 가능
- 글·스티커·사진이 다 없으면 403 (9999 내용이 없는 댓글 작성 시도입니다.)
- 길이 제한 CP949 6000 바이트: 한글 2, 영문 1, 이모지처럼 CP949 에 없는 글자는 1 ("?" 로 셈)
  한글 3000자·영문 6000자·이모지 6000개 OK / 한글 3001자·영문 6001자·이모지 6001개 400 (9999 댓글 길이가 초과되었습니다.)
"""
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Self, TypeAlias

from ..utils.parsing import as_dict, as_int
from .blocks import STICKER_PACKS, Block, Image, Paragraph, Sticker, Text
from .photo import UploadedImage

COMMENT_MAX_BYTES = 6000
_FORM_KEYS = ("content", "stickerId", "imagePath", "imageFileName", "imageWidth", "imageHeight", "refCommentId")


def comment_byte_len(text: str) -> int:
    """서버 댓글 길이 계산 = CP949 바이트, 없는 글자는 "?" 1바이트 [실측 2026-11-24 한글·영문·이모지 경계]"""
    return len(text.encode("cp949", errors="replace"))


def image_fields(img: UploadedImage | None) -> dict[str, Any]:
    """사진 댓글 폼 필드 - stickerId 와 refCommentId 사이, 순서까지 캡처값 그대로 [실측 2026-11-13 Camoufox UI 캡처]

    imagePath 는 upphoto 응답 path(파일명 없는 해시 경로) 끝에 "/" 를 붙인 값이다
    (예: /MjAy.../MDAx...PNG/). imageFileName 은 응답 fileName.
    """
    if img is None:
        return {}
    path = img.path or img.url.rsplit("/", 1)[0]
    return {
        "imagePath": path if path.endswith("/") else f"{path}/",
        "imageFileName": img.file_name,
        "imageWidth": img.width,
        "imageHeight": img.height,
    }


def _plain(p: Paragraph) -> str:
    for s in p.spans:
        if (s.style and not s.style.is_empty()) or s.link:
            raise ValueError(f"댓글에는 서식·링크를 넣을 수 없습니다 (글자만): {s.text!r}")
    return p.text


@dataclass(slots=True)
class CommentDraft:
    """댓글 본문 (글 + 스티커 1개 + 사진 1장)

    - text   : 글 (여러 줄 가능)
    - sticker: Sticker 또는 "cafe_001-1-185-160"
    - image  : 사진 1장 - Image 블록 / UploadedImage / bytes / 파일 경로 / (bytes, 파일명). 올리지 않은 것은 작성 때 업로드
    - extra  : 폼 필드 추가/덮어쓰기 (완전 커스텀)
    """

    text: str = ""
    sticker: Any = None
    image: Any = None
    extra: dict[str, Any] = field(default_factory=dict, kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("CommentDraft.text 는 str 이어야 합니다")
        if isinstance(self.sticker, str):
            self.sticker = Sticker.parse(self.sticker) if self.sticker else None
        elif self.sticker is not None and not isinstance(self.sticker, Sticker):
            raise TypeError(f"sticker 는 Sticker 또는 문자열입니다: {type(self.sticker).__name__}")
        if isinstance(self.image, Image):
            if self.image.caption or self.image.link:
                raise ValueError("댓글 사진에는 캡션·링크를 넣을 수 없습니다")
            self.image = self.image.source
        if not (self.text.strip() or self.sticker or self.image is not None):
            raise ValueError("댓글에는 글·스티커·사진 중 하나가 있어야 합니다 (서버 403 9999)")
        size = comment_byte_len(self.text)
        if size > COMMENT_MAX_BYTES:
            raise ValueError(f"댓글은 {COMMENT_MAX_BYTES}바이트(CP949: 한글 2, 영문·이모지 1)까지입니다: {size}바이트 (서버 400)")

    @property
    def uploaded_image(self) -> UploadedImage | None:
        return self.image if isinstance(self.image, UploadedImage) else None

    @property
    def needs_upload(self) -> bool:
        return self.image is not None and not isinstance(self.image, UploadedImage)

    @classmethod
    def of(cls, body: "CommentBody" = "", *, sticker: Any = None, image: Any = None) -> Self:
        """댓글 입력 (문자열 / CommentDraft / 블록 / 블록 목록) + 따로 받은 스티커·사진 -> CommentDraft

        Text·문자열은 줄바꿈으로 이어 붙이고, Sticker·Image 는 각각 하나까지.
        """
        if isinstance(body, CommentDraft):
            parts: list[Any] = [*([body.text] if body.text else []), *([body.sticker] if body.sticker else []),
                                *([body.image] if body.image is not None else [])]
            extra = dict(body.extra)
        elif isinstance(body, str | Block):
            parts, extra = ([body] if body != "" else []), {}
        else:
            parts, extra = list(body), {}
        if sticker:
            parts.append(sticker if isinstance(sticker, Sticker) else Sticker.parse(str(sticker)))
        if image is not None:
            parts.append(image if isinstance(image, Image) else _ImageInput(image))

        texts: list[str] = []
        found_sticker: Sticker | None = None
        found_image: Any = None
        for part in parts:
            if isinstance(part, str):
                texts.append(part)
            elif isinstance(part, Text):
                texts.append("\n".join(_plain(p) for p in part.paragraphs))
            elif isinstance(part, Sticker):
                if found_sticker is not None:
                    raise ValueError("댓글에는 스티커를 하나만 넣을 수 있습니다")
                found_sticker = part
            elif isinstance(part, Image | _ImageInput | UploadedImage):
                if found_image is not None:
                    raise ValueError("댓글에는 사진을 한 장만 넣을 수 있습니다")
                found_image = part.value if isinstance(part, _ImageInput) else part
            elif isinstance(part, Block):
                raise TypeError(f"댓글에 넣을 수 없는 블록입니다: {type(part).__name__} (Text, Sticker, Image 만)")
            else:
                raise TypeError(f"댓글 입력으로 쓸 수 없는 값입니다: {type(part).__name__}")
        return cls("\n".join(texts), found_sticker, found_image, extra=extra)

    def to_dict(self, ref_comment_id: int | None = None) -> dict[str, Any]:
        """CommentPost/CommentReply 폼 앞부분 (뒤에 cafeId, articleId, requestFrom 이 붙는다)

        [실측 2026-11-13 Camoufox UI 캡처] 순서: content, stickerId, [imagePath, imageFileName, imageWidth,
        imageHeight], [refCommentId]
        """
        if self.needs_upload:
            raise ValueError("업로드 안 된 사진입니다 - comments.add/reply 에 넘기면 자동으로 올립니다")
        fields: dict[str, Any] = {"content": self.text,
                                  "stickerId": self.sticker.comment_id if self.sticker else "",
                                  **image_fields(self.uploaded_image)}
        if ref_comment_id is not None:
            fields["refCommentId"] = ref_comment_id
        fields.update(self.extra)
        return fields

    @classmethod
    def from_dict(cls, d: Any) -> Self:
        """댓글 폼 필드 dict -> CommentDraft (모르는 키는 extra, refCommentId 는 버림)"""
        d = as_dict(d)
        img = None
        if d.get("imagePath"):
            path = str(d["imagePath"]).rstrip("/")
            name = str(d.get("imageFileName") or "")
            img = UploadedImage(url=f"{path}/{name}", path=path, domain="", file_name=name,
                                width=as_int(d.get("imageWidth")), height=as_int(d.get("imageHeight")))
        return cls(str(d.get("content") or ""), str(d.get("stickerId") or "") or None, img,
                   extra={k: v for k, v in d.items() if k not in _FORM_KEYS})

    # ------------------------------------------------ spec / 스키마 (AI 채우기)

    @staticmethod
    def json_schema(*, sticker: bool = True, hint: str | None = None) -> dict[str, Any]:
        """댓글 JSON Schema {"text", "sticker"?} - AI 가 채운 결과는 CommentDraft.from_spec 으로

        sticker=False 면 글만. 사진은 AI 가 만들 대상이 아니라 넣지 않는다 (from_spec(image=...) 로 붙인다).
        """
        props: dict[str, Any] = {"text": {"type": "string", "description": hint or
                                          f"댓글 글 (여러 줄 가능, {COMMENT_MAX_BYTES}바이트 이하: 한글 2, 영문·이모지 1)"}}
        if sticker:
            props["sticker"] = {"type": "string", "pattern": r"^(?:[A-Za-z0-9_]+-\d+-\d+-\d+)?$",
                                "description": "스티커 id 'pack-seq-185-160' (없으면 빈 문자열). 묶음(번호 범위): "
                                               + ", ".join(f"{k}(1~{n})" for k, (_, n) in STICKER_PACKS.items())}
        return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "caffeinate Comment",
                "type": "object", "additionalProperties": False, "required": ["text"], "properties": props}

    def to_spec(self) -> dict[str, Any]:
        """{"text", "sticker"?} (사진은 담지 않는다)"""
        d: dict[str, Any] = {"text": self.text}
        if self.sticker:
            d["sticker"] = self.sticker.comment_id
        return d

    @classmethod
    def from_spec(cls, data: Any, *, image: Any = None) -> Self:
        """{"text", "sticker"?} (+ 따로 넘긴 사진) -> CommentDraft. 검사(빈 댓글·길이)는 같다"""
        d = as_dict(data)
        if "text" not in d and "sticker" not in d:
            raise ValueError(f"댓글 spec 에는 text 또는 sticker 가 있어야 합니다: {data!r}")
        return cls(str(d.get("text") or ""), str(d.get("sticker") or "") or None, image)

    def to_blocks(self) -> list[Block]:
        """글 블록 목록으로 (Text, Sticker, Image) - 같은 내용을 게시글에 쓸 때"""
        out: list[Block] = []
        if self.text:
            out.append(Text(self.text))
        if self.sticker:
            out.append(self.sticker)
        if self.image is not None:
            out.append(Image(self.image))
        return out


@dataclass(slots=True, frozen=True)
class _ImageInput:
    """사진 입력 (bytes/경로/튜플) 을 블록 목록 안에서 구분하기 위한 감싸개"""

    value: Any


CommentBody: TypeAlias = "str | CommentDraft | Block | Sequence[Block | str]"
