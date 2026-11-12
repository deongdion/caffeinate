"""multipart/form-data 인코딩 (크롬 형식 boundary, 헤더 순서를 직접 제어하려고 curl mime 대신 사용)"""
import secrets
import string
from dataclasses import dataclass

_ALNUM = string.ascii_letters + string.digits


@dataclass(slots=True, frozen=True, kw_only=True)
class FilePart:
    name: str
    filename: str
    data: bytes
    content_type: str = "application/octet-stream"


def chrome_boundary() -> str:
    """----WebKitFormBoundary + 16자 (크롬/Blink 형식)"""
    return "----WebKitFormBoundary" + "".join(secrets.choice(_ALNUM) for _ in range(16))


def encode_multipart(
    files: list[FilePart], fields: dict[str, str] | None = None
) -> tuple[str, bytes]:
    """-> (content-type 헤더 값, 본문 bytes)"""
    boundary = chrome_boundary()
    out = bytearray()
    for name, value in (fields or {}).items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode("utf-8") + b"\r\n"
    for f in files:
        filename = f.filename.replace('"', "%22")
        out += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{f.name}"; filename="{filename}"\r\n'
            f"Content-Type: {f.content_type}\r\n\r\n"
        ).encode()
        out += f.data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", bytes(out)
