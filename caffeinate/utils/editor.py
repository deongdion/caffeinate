"""SmartEditor(ONE) 문서 JSON 생성 - 글쓰기 contentJson [실측 2026-11-12 브라우저 캡처 형식]"""
import json
import secrets
import time
import uuid
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from ..models.photo import UploadedImage

SE_VERSION: Final = "2.10.2"
_CROCKFORD: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def se_id() -> str:
    return f"SE-{uuid.uuid4()}"


def ulid() -> str:
    """문서 id: ULID (48bit ms 시각 10자 + 80bit 난수 16자, Crockford base32)"""
    ts = int(time.time() * 1000)
    stamp = "".join(_CROCKFORD[(ts >> (5 * i)) & 0x1F] for i in reversed(range(10)))
    rnd = secrets.randbits(80)
    return stamp + "".join(_CROCKFORD[(rnd >> (5 * i)) & 0x1F] for i in reversed(range(16)))


def _text_component(line: str) -> dict[str, Any]:
    return {
        "id": se_id(),
        "layout": "default",
        "value": [
            {
                "id": se_id(),
                "nodes": [{"id": se_id(), "value": line, "@ctype": "textNode"}],
                "@ctype": "paragraph",
            }
        ],
        "@ctype": "text",
    }


def _image_component(img: "UploadedImage", *, represent: bool) -> dict[str, Any]:
    """[실측] path 는 업로드 응답의 <url>(해시경로/파일명). <path> 를 넣으면 저장 시 src 가 깨져 404"""
    return {
        "id": se_id(),
        "layout": "default",
        "src": img.src,
        "internalResource": True,
        "represent": represent,
        "path": img.url,
        "domain": img.domain,
        "fileSize": img.file_size,
        "width": img.width,
        "widthPercentage": 0,
        "height": img.height,
        "originalWidth": img.width,
        "originalHeight": img.height,
        "fileName": img.file_name,
        "caption": None,
        "format": "normal",
        "displayFormat": "normal",
        "imageLoaded": True,
        "contentMode": "normal",
        "origin": {"srcFrom": "local", "@ctype": "imageOrigin"},
        "ai": False,
        "@ctype": "image",
    }


def build_content_json(text: str, images: "list[UploadedImage] | None" = None) -> str:
    """본문 텍스트(줄 단위 문단) + 업로드 이미지 -> contentJson 문자열

    [실측] di.dio 는 서버 파싱에 필수 (빈 배열이면 500).
    """
    images = images or []
    lines = [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()] if text else []
    components = [_text_component(ln) for ln in lines] + [
        _image_component(img, represent=(i == 0)) for i, img in enumerate(images)
    ]

    dio: list[dict[str, Any]] = []
    if text:
        dio.append({"dis": "N", "dia": {"t": 0, "p": 0, "st": len(text.encode("utf-8")), "sk": 1}})
    dio.extend({"dis": "N", "dia": {"t": 0, "p": 0, "st": 0, "sk": 0}} for _ in images)

    doc = {
        "document": {
            "version": SE_VERSION,
            "theme": "default",
            "language": "ko-KR",
            "id": ulid(),
            "di": {"dif": False, "dio": dio},
            "components": components,
        }
    }
    return json.dumps(doc, ensure_ascii=False)
