"""로그인용 크로미움 계열 브라우저 탐색/실행"""
import os
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..enums import LoginBrowser


@dataclass(frozen=True, slots=True)
class BrowserExecutable:
    kind: LoginBrowser
    path: Path


_CANDIDATES: tuple[tuple[LoginBrowser, str], ...] = (
    (LoginBrowser.CHROME, r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    (LoginBrowser.CHROME, r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    (LoginBrowser.CHROME, r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    (LoginBrowser.EDGE, r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    (LoginBrowser.EDGE, r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    (LoginBrowser.WHALE, r"%LOCALAPPDATA%\Naver\Whale\Application\whale.exe"),
)


def find_browsers() -> list[BrowserExecutable]:
    """설치된 크로미움 계열 브라우저 (우선순위 순)"""
    seen: set[Path] = set()
    out: list[BrowserExecutable] = []
    for kind, raw in _CANDIDATES:
        p = Path(os.path.expandvars(raw))
        if p.exists() and p not in seen:
            seen.add(p)
            out.append(BrowserExecutable(kind, p))
    return out


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def launch(
    exe: BrowserExecutable,
    *,
    port: int,
    user_data_dir: Path,
    url: str,
    headless: bool = False,
) -> subprocess.Popen[bytes]:
    """디버그 포트를 연 전용 프로필 브라우저 실행"""
    user_data_dir.mkdir(parents=True, exist_ok=True)
    args = [
        str(exe.path),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
    ]
    if headless:
        args.append("--headless=new")
    args.append(url)
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
