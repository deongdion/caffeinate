"""SmartEditor(ONE) 문서 JSON 생성 - 글쓰기 contentJson [실측 2026-11-12 브라우저 캡처 형식]"""
import secrets
import time
import uuid
from typing import TYPE_CHECKING, Final

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


def build_content_json(text: str, images: "list[UploadedImage] | None" = None) -> str:
    """본문 텍스트(줄 단위 문단) + 업로드 이미지 -> contentJson 문자열 (= Document.from_text(...).to_json())

    [실측] di.dio 는 서버 파싱에 필수 (빈 배열이면 500).
    [실측 2026-11-13] dio 는 이미지 개수와 무관하게 텍스트 1개 + 이미지 1개까지만.
    이미지마다 항목을 넣으면 이미지 2장부터 500 (IllegalStateException).

    [실측 2026-11-13 브라우저 캡처] 빈 줄 보존: 줄마다 컴포넌트를 만들지 않고
    text 컴포넌트 하나의 value 에 문단 배열로 넣으며, 빈 줄은
    textNode 값이 빈 문자열("" ) 인 문단이 된다.
    dio 텍스트 항목의 st 는 빈 줄을 건너뛰고 "
" 으로 잇은 바이트 길이
    ("첫 줄\n\n셋째 줄" -> 18). 빈 줄을 버리면 두 문단으로 저장된다.

    [실측 2026-11-13 E2E] 줄 -> 문단 1:1 로 저장된다: CRLF/단독 CR/LF 모두 줄바꿈, 빈 줄(연속 포함)은 각각
    빈 문단(뷰어에서 \u200b), 공백만 있는 줄은 공백이 그대로 남은 문단. 이모지·& < > " 도 그대로 보존.
    블록(소제목, 인용, 표, 사진 사이 글 등)이 필요하면 models.blocks.Document 를 쓴다.
    """
    from ..models.blocks import Document  # 순환 import 방지

    return Document.from_text(text, images or []).to_json()
