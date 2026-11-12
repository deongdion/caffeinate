"""
Chrome DevTools Protocol 최소 클라이언트 (curl_cffi AsyncSession.ws_connect 사용)

브라우저 타깃(/json/version 의 webSocketDebuggerUrl)에 붙어 Storage.getCookies 등을 호출한다.
Origin 헤더를 보내지 않으므로 --remote-allow-origins 없이도 연결된다 (실측).
"""
import asyncio
import contextlib
import itertools
import json
from types import TracebackType
from typing import Any, Self

from curl_cffi import AsyncSession
from curl_cffi.requests import AsyncWebSocket

from ..core.errors import LoginError


async def wait_for_devtools(http: AsyncSession, port: int, *, timeout: float = 20.0) -> str:
    """디버그 포트가 열릴 때까지 대기 -> 브라우저 webSocketDebuggerUrl"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last: Exception | None = None
    while loop.time() < deadline:
        try:
            r = await http.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
            if ws := r.json().get("webSocketDebuggerUrl"):
                return str(ws)
        except Exception as e:  # noqa: BLE001 - 브라우저 기동 전에는 다양한 오류가 남
            last = e
        await asyncio.sleep(0.5)
    raise LoginError(f"DevTools 접속 실패(port={port}): {last}")


class CdpClient:
    """
    async with CdpClient(ws_url) as cdp:
        cookies = await cdp.get_cookies()
    """

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self._http = AsyncSession()
        self._ws: AsyncWebSocket | None = None
        self._ids = itertools.count(1)

    async def __aenter__(self) -> Self:
        self._ws = await self._http.ws_connect(self.ws_url)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        await self._http.close()

    async def call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 15.0) -> dict[str, Any]:
        """명령 1회 전송 -> 같은 id 응답 대기 (이벤트 메시지는 건너뜀)"""
        if self._ws is None:
            raise LoginError("CDP 연결이 열려있지 않습니다")
        mid = next(self._ids)
        await self._ws.send_json({"id": mid, "method": method, "params": params or {}})
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while (remaining := deadline - loop.time()) > 0:
            msg = json.loads(await self._ws.recv_str(timeout=remaining))
            if msg.get("id") != mid:
                continue
            if "error" in msg:
                raise LoginError(f"CDP 오류 {method}: {msg['error']}")
            return msg.get("result", {})
        raise LoginError(f"CDP 응답 시간초과: {method}")

    async def get_cookies(self) -> list[dict[str, Any]]:
        """브라우저 전체 쿠키 (httpOnly 포함)"""
        res = await self.call("Storage.getCookies")
        return list(res.get("cookies", []))
