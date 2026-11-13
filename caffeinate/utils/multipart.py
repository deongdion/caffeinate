"""multipart/form-data 인코딩 (파이어폭스 형식 boundary, 헤더 순서를 직접 제어하려고 curl mime 대신 사용)"""
import secrets
from dataclasses import dataclass


@dataclass(slots=True, frozen=True, kw_only=True)
class FilePart:
    name: str
    filename: str
    data: bytes
    content_type: str = "application/octet-stream"


def browser_boundary() -> str:
    """----geckoformboundary + 64bit 난수 2개의 16진수 (0 채움 없음, 보통 32자)

    [실측 2026-11-13 Camoufox 158] 예: ----geckoformboundary9f6c59901029aac68e95c14fe74cc0bf
    """
    return f"----geckoformboundary{secrets.randbits(64):x}{secrets.randbits(64):x}"


def encode_multipart(
    files: list[FilePart], fields: dict[str, str] | None = None
) -> tuple[str, bytes]:
    """-> (content-type 헤더 값, 본문 bytes)"""
    boundary = browser_boundary()
    out = bytearray()
    for name, value in (fields or {}).items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode("utf-8") + b"\r\n"
    for f in files:
        # 파이어폭스는 파일명의 " / CR / LF 를 %22 / %0D / %0A 로 바꿔 보낸다 (헤더 주입 방지)
        filename = f.filename.replace('"', "%22").replace("\r", "%0D").replace("\n", "%0A")
        out += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{f.name}"; filename="{filename}"\r\n'
            f"Content-Type: {f.content_type}\r\n\r\n"
        ).encode()
        out += f.data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", bytes(out)
