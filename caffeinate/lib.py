"""
caffeinate 고수준 비동기 클라이언트

    import asyncio
    from caffeinate import Caffeinate

    async def main():
        async with Caffeinate() as cafe:
            for c in await cafe.cafes.my_cafes():
                print(c.cafe_id, c.name)
            boards = await cafe.boards.all("remonterace")          # 카페 ID / slug / URL 모두 가능
            async for a in cafe.boards.iter_articles("remonterace", 2, limit=40):
                print(a.subject)
            article = await cafe.articles.get("https://cafe.naver.com/f-e/cafes/30857348/articles/368535")
            comments = await cafe.comments.all(article.ref)

    asyncio.run(main())

동기 스크립트/REPL 에서는 run() 으로 한 번에:

    import caffeinate
    article = caffeinate.run(lambda cafe: cafe.articles.get(URL))

요청 간격 (대량 작업):

    Caffeinate(Settings(min_request_interval=1.0))   # 모든 요청 시작 시각을 1초 이상 벌린다

디버그 로그 (요청/재시도 원인 추적):

    caffeinate.enable_logging()          # logging.getLogger("caffeinate") 에 콘솔 핸들러 부착
"""
import asyncio
import logging
import warnings
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Self, TypeVar

from .auth.login import LoginOptions, browser_login
from .core.config import Settings
from .core.cookies import CookieStore
from .core.fingerprint import load_or_create, save
from .core.session import CafeSession
from .models import Cookie, Fingerprint
from .services import (
    ArticleService,
    BoardService,
    CafeService,
    CommentService,
    LikeService,
    MemberService,
    PhotoService,
)

logger = logging.getLogger("caffeinate")
T = TypeVar("T")


class Caffeinate:
    """
    네이버 카페 클라이언트. 기능은 서비스 속성으로 나뉜다.

    - cafes    : 내 카페 목록, 카페 ID 해석 (slug -> ID 는 클라이언트에 캐시)
    - boards   : 게시판 목록, 게시글 목록(페이지 / iter_articles), 공지
    - articles : 게시글 URL 해석, 상세, 글쓰기/수정/삭제 (images= 자동 업로드)
    - photos   : 이미지 업로드
    - comments : 댓글/대댓글 조회(page / all / iter), 작성, 삭제
    - likes    : 좋아요 상태/등록/취소, 누른 멤버
    - members  : 로그인 식별자, 가입 여부, 등급, 내 정보

    카페를 받는 인자(cafe_id)는 숫자 ID, 숫자 문자열, slug("remonterace"), 카페 URL 을 모두 받는다 (CafeLike).

    - settings   : Settings (타임아웃/재시도/프록시/프로필 폴더/요청 간격). 없으면 기본값
    - fingerprint: 지문 직접 지정 (없으면 프로필의 fingerprint.json)
    - cookies    : 쿠키 직접 지정 (없으면 프로필의 cookies.json)
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        fingerprint: Fingerprint | None = None,
        cookies: CookieStore | list[Cookie] | None = None,
    ) -> None:
        self.settings = settings or Settings()
        if isinstance(cookies, list):
            cookies = CookieStore(cookies)
        self.session = CafeSession(self.settings, fingerprint=fingerprint, cookies=cookies)
        self._cafe_ids: dict[str, int] = {}  # slug(소문자) -> cafeId 캐시 (cafes.id_from_slug)
        logger.debug(
            "Caffeinate 생성: 프로필=%s, 로그인 쿠키=%s, 지문=%s %s (%s)",
            self.settings.profile_dir,
            "있음" if self.session.cookies.has_login else "없음",
            self.session.fingerprint.brand.value,
            self.session.fingerprint.major,
            self.session.fingerprint.source,
        )
        if self.session.cookies.has_login and not self.session.fingerprint.from_login:
            warnings.warn(
                "로그인 쿠키는 있지만 지문이 로그인 브라우저에서 온 것이 아닙니다. "
                "Caffeinate.login() 으로 다시 로그인하면 쿠키와 지문이 함께 맞춰집니다.",
                stacklevel=2,
            )

        self.cafes = CafeService(self)
        self.boards = BoardService(self)
        self.articles = ArticleService(self)
        self.comments = CommentService(self)
        self.likes = LikeService(self)
        self.members = MemberService(self)
        self.photos = PhotoService(self)

    async def __aenter__(self) -> Self:
        await self.session.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.session.__aexit__(exc_type, exc, tb)

    async def close(self) -> None:
        """세션 종료 (async with 를 쓰지 않았을 때). 갱신된 로그인 쿠키는 이때 저장된다."""
        await self.session.close()

    def __repr__(self) -> str:
        login = "로그인 쿠키 있음" if self.session.cookies.has_login else "비로그인"
        return f"<Caffeinate {login}, profile_dir={str(self.settings.profile_dir)!r}>"

    # ---------------------------------------------------------------- 편의
    @property
    def fingerprint(self) -> Fingerprint:
        """요청에 쓰는 브라우저 지문 (UA/언어/TLS)"""
        return self.session.fingerprint

    @property
    def has_login_cookies(self) -> bool:
        """로그인 쿠키(NID_AUT/NID_SES)가 로컬에 있는지 - 서버 요청 없음, 만료 여부는 모른다"""
        return self.session.cookies.has_login

    async def is_logged_in(self) -> bool:
        """서버에 물어 실제 로그인 상태 확인 (쿠키 만료 검사). 오류면 False"""
        return await self.members.is_logged_in()

    @classmethod
    async def login(
        cls,
        settings: Settings | None = None,
        options: LoginOptions | None = None,
    ) -> "Caffeinate":
        """Camoufox 로 로그인 -> 쿠키 + 지문 저장 -> 로그인된 클라이언트 반환 (async with 로 사용)

        options.username/password 를 주면 사람처럼 타이핑해서 자동 입력한다 (auth.login 모듈 설명 참고).
        옵션이 없으면 창만 띄우고 사람이 로그인한다(수동 모드).
        지문(UA/언어/TLS)은 로그인한 브라우저에서 유도해 profile/fingerprint.json 에 함께 저장한다.
        한 번 로그인하면 이후에는 `Caffeinate()` 가 저장된 쿠키를 읽는다.

            opts = LoginOptions(username=os.environ["NAVER_ID"], password=os.environ["NAVER_PASSWORD"])
            async with await Caffeinate.login(options=opts) as cafe: ...
            async with await Caffeinate.login() as cafe: ...          # 수동 모드
        """
        settings = settings or Settings()
        logger.info("브라우저 로그인 시작 (프로필: %s)", settings.profile_dir)
        result = await browser_login(settings, options)
        result.cookies.save(settings.cookies_file)
        save(result.fingerprint, settings.fingerprint_file)
        logger.info("로그인 쿠키/지문 저장: %s", settings.profile_dir)
        return cls(settings, fingerprint=result.fingerprint, cookies=CookieStore.load(settings.cookies_file))


def load_fingerprint(settings: Settings | None = None, *, force_new: bool = False) -> Fingerprint:
    """저장된 지문 로드 (없으면 내장 기본값. 로그인하면 로그인 브라우저 값으로 바뀐다)"""
    return load_or_create((settings or Settings()).fingerprint_file, force_new=force_new)


def run(fn: Callable[["Caffeinate"], Awaitable[T]], settings: Settings | None = None) -> T:
    """동기 코드에서 한 번 호출: 클라이언트를 열고 fn(cafe) 를 실행한 뒤 닫는다.

        boards = caffeinate.run(lambda cafe: cafe.boards.all(18886295))

        async def job(cafe: Caffeinate) -> list[str]:
            page = await cafe.boards.articles(18886295, 2)
            return [a.subject for a in page]
        subjects = caffeinate.run(job)

    이미 이벤트 루프가 돌고 있는 곳(Jupyter, async 함수 안)에서는 쓸 수 없다 -> await 로 직접 호출.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "이미 이벤트 루프가 실행 중입니다 (Jupyter/async 함수 안). caffeinate.run() 대신 "
            "`async with Caffeinate() as cafe: await ...` 로 직접 await 하세요."
        )

    async def _main() -> T:
        async with Caffeinate(settings) as cafe:
            return await fn(cafe)

    return asyncio.run(_main())


def enable_logging(level: int | str = logging.DEBUG, *, fmt: str | None = None) -> logging.Logger:
    """"caffeinate" 로거에 콘솔 핸들러를 붙여 디버그 로그를 본다 (중복 호출해도 핸들러는 하나).

    라이브러리는 기본으로 NullHandler 만 달려 있어 아무것도 출력하지 않는다.
    애플리케이션에서 logging.basicConfig 등으로 직접 설정해도 된다 (로거 이름 "caffeinate").
    쿠키 값/비밀번호는 로그에 남기지 않는다.
    """
    log = logging.getLogger("caffeinate")
    log.setLevel(level)
    if not any(getattr(h, "_caffeinate", False) for h in log.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(fmt or "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler._caffeinate = True  # type: ignore[attr-defined]
        log.addHandler(handler)
    return log
