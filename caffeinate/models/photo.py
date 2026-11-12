"""업로드된 이미지 모델 (cafe.upphoto simpleUpload 응답)"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Self

from ..core.errors import ParseError


@dataclass(slots=True, kw_only=True)
class UploadedImage:
    """upphoto XML <item> -> SmartEditor image 컴포넌트 재료 [실측 2026-11-12]"""

    url: str    # 해시경로/파일명 - contentJson image.path 에 넣는 값
    path: str   # 해시경로 (파일명 없음) - contentJson 에 넣으면 저장 시 src 가 깨진다
    domain: str
    file_name: str
    width: int = 0
    height: int = 0
    file_size: int = 0
    image_type: str = ""

    @property
    def src(self) -> str:
        return f"{self.domain}{self.url}?type=w1600"

    @classmethod
    def from_xml(cls, text: str, *, domain: str, fallback_name: str, fallback_size: int) -> Self:
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            raise ParseError(f"이미지 업로드 응답(XML) 파싱 실패: {text[:200]}") from e

        def get(tag: str) -> str:
            return (root.findtext(tag) or "").strip()

        def num(tag: str, default: int = 0) -> int:
            v = get(tag)
            return int(v) if v.isdigit() else default

        return cls(
            url=get("url"),
            path=get("path"),
            domain=domain,
            file_name=get("fileName") or fallback_name,
            width=num("width"),
            height=num("height"),
            file_size=num("fileSize", fallback_size),
            image_type=get("imageType"),
        )
