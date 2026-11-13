"""utils/editor.py - SmartEditor contentJson 규칙 [README 실측 2026-11-13 기준]"""
import json
from typing import Any

from caffeinate import UploadedImage
from caffeinate.utils.editor import build_content_json, ulid


def _doc(text: str, images: list[UploadedImage] | None = None) -> dict[str, Any]:
    return json.loads(build_content_json(text, images))["document"]


def _image(name: str) -> UploadedImage:
    return UploadedImage(
        url=f"/abc/{name}", path=f"/p/{name}", domain="https://cafeptthumb-phinf.pstatic.net",
        file_name=name, file_size=100, width=10, height=20,
    )


def test_single_text_component_keeps_blank_lines() -> None:
    doc = _doc("첫 줄\n\n셋째 줄")
    comps = doc["components"]
    assert len(comps) == 1 and comps[0]["@ctype"] == "text"
    values = [p["nodes"][0]["value"] for p in comps[0]["value"]]
    assert values == ["첫 줄", "", "셋째 줄"]


def test_dio_text_length_skips_blank_lines() -> None:
    # "첫 줄\n셋째 줄" 의 UTF-8 바이트 길이 = 18 (README 예시)
    doc = _doc("첫 줄\n\n셋째 줄")
    assert doc["di"]["dio"] == [{"dis": "N", "dia": {"t": 0, "p": 0, "st": 18, "sk": 1}}]


def test_crlf_normalized() -> None:
    doc = _doc("a\r\nb")
    assert [p["nodes"][0]["value"] for p in doc["components"][0]["value"]] == ["a", "b"]


def test_images_appended_first_is_representative_and_single_dio() -> None:
    doc = _doc("본문", [_image("1.png"), _image("2.png"), _image("3.png")])
    comps = doc["components"]
    assert [c["@ctype"] for c in comps] == ["text", "image", "image", "image"]
    assert [c["represent"] for c in comps[1:]] == [True, False, False]
    assert comps[1]["path"] == "/abc/1.png"  # <url> 이어야 함 (<path> 면 404)
    # 이미지 개수와 무관하게 텍스트 1 + 이미지 1 (이미지마다 넣으면 500)
    assert len(doc["di"]["dio"]) == 2


def test_empty_text_with_image() -> None:
    doc = _doc("", [_image("1.png")])
    assert [c["@ctype"] for c in doc["components"]] == ["image"]
    assert doc["di"]["dio"] == [{"dis": "N", "dia": {"t": 0, "p": 0, "st": 0, "sk": 0}}]


def test_ulid_format() -> None:
    u = ulid()
    assert len(u) == 26
    assert set(u) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def test_lone_cr_is_newline() -> None:
    doc = json.loads(build_content_json("a\rb"))["document"]
    assert [p["nodes"][0]["value"] for p in doc["components"][0]["value"]] == ["a", "b"]


def test_empty_body_rejected_locally() -> None:
    import pytest

    with pytest.raises(ValueError):
        build_content_json("")
