"""CLI 출력 헬퍼"""
import json
import sys
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any


def to_jsonable(obj: Any, *, include_raw: bool = False) -> Any:
    """dataclass/enum/datetime -> JSON 직렬화 가능한 값 (raw 필드는 기본 제외)"""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: to_jsonable(getattr(obj, f.name), include_raw=include_raw)
            for f in fields(obj)
            if include_raw or f.name != "raw"
        }
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v, include_raw=include_raw) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v, include_raw=include_raw) for v in obj]
    return obj


def print_json(obj: Any, *, include_raw: bool = False) -> None:
    print(json.dumps(to_jsonable(obj, include_raw=include_raw), ensure_ascii=False, indent=2))


def one_line(text: str, width: int = 60) -> str:
    s = " / ".join(line.strip() for line in text.splitlines() if line.strip())
    return s if len(s) <= width else s[: width - 1] + "…"


def local_time(dt: datetime | None) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M") if dt else "-"


def setup_console() -> None:
    """윈도우 콘솔(cp949)에서 이모지/한글 출력이 깨지거나 죽지 않도록"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
