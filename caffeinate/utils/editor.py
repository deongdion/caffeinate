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


def _paragraph(line: str) -> dict[str, Any]:
    """문단 한 개. 빈 줄은 textNode 값이 빈 문자열인 문단이다 [실측 2026-11-13 브라우저 캡처]"""
    return {
        "id": se_id(),
        "nodes": [{"id": se_id(), "value": line, "@ctype": "textNode"}],
        "@ctype": "paragraph",
    }


def _text_component(paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    """문단 묶음 하나가 text 컴포넌트 하나 (브라우저는 줄마다 컴포넌트를 만들지 않는다)"""
    return {
        "id": se_id(),
        "layout": "default",
        "value": paragraphs,
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
    [실측 2026-11-13] dio 는 이미지 개수와 무관하게 텍스트 1개 + 이미지 1개까지만.
    이미지마다 항목을 넣으면 이미지 2장부터 500 (IllegalStateException).

    [실측 2026-11-13 브라우저 캡처] 빈 줄 보존: 줄마다 컴포넌트를 만들지 않고
    text 컴포넌트 하나의 value 에 문단 배열로 넣으며, 빈 줄은
    textNode 값이 빈 문자열("" ) 인 문단이 된다.
    dio 텍스트 항목의 st 는 빈 줄을 건너뛰고 "\n" 으로 잇은 바이트 길이
    ("첫 줄\\n\\n셋째 줄" -> 18). 빈 줄을 버리면 두 문단으로 저장된다.
    """
    images = images or []
    lines = text.replace("\r\n", "\n").split("\n") if text else []
    paragraphs = [_paragraph(ln) for ln in lines]

    components: list[dict[str, Any]] = []
    if paragraphs:
        components.append(_text_component(paragraphs))
    components += [_image_component(img, represent=(i == 0)) for i, img in enumerate(images)]

    dio: list[dict[str, Any]] = []
    if text:
        joined = "\n".join(ln for ln in lines if ln.strip())
        dio.append({"dis": "N", "dia": {"t": 0, "p": 0, "st": len(joined.encode("utf-8")), "sk": 1}})
    if images:
        dio.append({"dis": "N", "dia": {"t": 0, "p": 0, "st": 0, "sk": 0}})

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
