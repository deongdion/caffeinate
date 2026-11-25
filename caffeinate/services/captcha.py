"""카페 만들기 캡차 풀이기

풀이기는 `(세션, CaptchaChallenge) -> 답 문자열 | None` 인 async 호출 가능 객체다. `captcha_type` 속성으로
어떤 캡차(음성/이미지)를 받을지 알린다 (없으면 음성).

- SoundCaptchaOcr (기본): 음성 캡차 영어 숫자 wav -> OCR 서버 /digits
  [실측: auth/login.py 의 로그인 캡차, MarketingMinjok cafe_write_normal NaverClient.cs 와 같은 규약
   multipart 필드 audio(audio.wav, audio/wav) -> {"digits": "123456"}]
- ImageCaptchaOcr: 이미지 캡차 -> OCR 서버 /ocr
  [MarketingMinjok backlink_normal CaptchaUtils.cs: multipart 필드 image -> {"digits"} 또는 {"text"}]
  [실측 2026-11-24 실패] 카페 개설 이미지 캡차(nhncaptchav4.gif, 실제로는 JPEG 200x90, 사진 배경 위 영문+숫자)는
  이 서버가 읽지 못한다 ({"digits": "", "text": "........."}). 이미지 캡차는 사람이 푸는 풀이기를 쓴다.

직접 풀려면 함수를 넘긴다:

    async def ask(session, ch):
        print(ch.image_url or ch.sound_url)
        return input("캡차 답: ")
    ask.captcha_type = CaptchaType.IMAGE
    await cafe.cafes.create(opts, captcha_solver=ask)
"""
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from ..core.config import CAFE_CREATE_PAGE
from ..core.errors import NetworkError
from ..core.session import CafeSession
from ..enums import CaptchaType, RequestKind
from ..models import CaptchaChallenge
from ..utils.multipart import FilePart, encode_multipart
from .photos import _image_mime

logger = logging.getLogger("caffeinate")


class CaptchaSolver(Protocol):
    """캡차 풀이기 규약"""

    captcha_type: CaptchaType

    def __call__(self, session: CafeSession, challenge: CaptchaChallenge) -> Awaitable[str | None]: ...


CaptchaSolverLike = CaptchaSolver | Callable[[CafeSession, CaptchaChallenge], Awaitable[str | None]]


def solver_type(solver: object) -> CaptchaType:
    """풀이기가 받는 캡차 종류 (속성이 없으면 음성)"""
    return CaptchaType(getattr(solver, "captcha_type", CaptchaType.SOUND))


def _clean_answer(value: object) -> str | None:
    """OCR 응답 값 -> 영문/숫자만 남긴 답 (비면 None. 못 읽으면 서버가 "....." 를 준다 [실측 2026-11-24])"""
    answer = re.sub(r"[^0-9A-Za-z]", "", str(value or ""))
    return answer or None


async def _post_ocr(session: CafeSession, url: str, part: FilePart) -> dict[str, object]:
    """OCR 서버로 파일 1개 전송 -> JSON dict (네이버 쿠키/Referer 없이)"""
    content_type, body = encode_multipart([part])
    try:
        resp = await session.post(
            url, data=body, headers={"content-type": content_type}, kind=RequestKind.FETCH, credentials=False,
        )
    except NetworkError as e:  # OCR 서버가 죽어도 재시도 -> 끝내 못 풀면 CaptchaError
        logger.debug("캡차 OCR 연결 실패: %s", e)
        return {}
    if resp.status_code != 200:
        logger.debug("캡차 OCR HTTP %s", resp.status_code)
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class SoundCaptchaOcr:
    """음성 캡차 -> 영어 숫자 음원 -> OCR 서버 (기본 풀이기)

    음원은 화면의 <audio> 처럼 받는다 (쿠키 포함, Range: bytes=0-, Referer 카페 만들기 화면)
    화면은 soundCaptcha.wav(한국어)를 재생하지만 OCR 은 영어 숫자를 받으므로 soundCaptchaEn.wav 를 쓴다
    [실측 2026-11-24 카페 개설 키로 En 음원 수신 + OCR 답 첫 시도 통과]
    """

    captcha_type = CaptchaType.SOUND

    def __init__(self, ocr_url: str | None = None, *, retries: int = 2) -> None:
        self.ocr_url = ocr_url
        self.retries = max(1, retries)

    async def __call__(self, session: CafeSession, challenge: CaptchaChallenge) -> str | None:
        url = self.ocr_url or session.settings.sound_captcha_ocr_url
        wav_url = f"{challenge.sound_url}&replay={int(time.time() * 1000)}"
        resp = await session.get(
            wav_url, kind=RequestKind.AUDIO, headers={"range": "bytes=0-"}, referer=CAFE_CREATE_PAGE,
        )
        if resp.status_code not in (200, 206) or not resp.content:
            logger.debug("음성 캡차 음원 다운로드 실패 HTTP %s (%d바이트)", resp.status_code, len(resp.content or b""))
            return None
        part = FilePart(name="audio", filename="audio.wav", data=resp.content, content_type="audio/wav")
        for _ in range(self.retries):
            data = await _post_ocr(session, url, part)
            answer = _clean_answer(data.get("digits"))
            if answer and answer.isdigit():
                return answer
            logger.debug("음성 캡차 OCR 응답이 숫자가 아님: %r", data)
        return None


class ImageCaptchaOcr:
    """이미지 캡차 -> OCR 서버 /ocr [실측 2026-11-24: 카페 개설 이미지 캡차는 못 읽음 - 모듈 설명]"""

    captcha_type = CaptchaType.IMAGE

    def __init__(self, ocr_url: str | None = None) -> None:
        self.ocr_url = ocr_url

    async def __call__(self, session: CafeSession, challenge: CaptchaChallenge) -> str | None:
        if not challenge.image_url:
            return None
        url = self.ocr_url or session.settings.image_captcha_ocr_url
        img = await session.get(challenge.image_url, kind=RequestKind.FETCH, referer=CAFE_CREATE_PAGE)
        if img.status_code != 200 or not img.content:
            return None
        # 주소는 .gif 지만 내용은 JPEG [실측 2026-11-24] -> 시그니처로 MIME 결정
        mime = _image_mime("captcha", img.content)
        part = FilePart(name="image", filename="captcha.jpg" if mime == "image/jpeg" else "captcha.gif", data=img.content,
                        content_type=mime)
        data = await _post_ocr(session, url, part)
        return _clean_answer(data.get("digits")) or _clean_answer(data.get("text"))
