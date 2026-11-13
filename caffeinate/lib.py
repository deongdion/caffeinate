"""
caffeinate 고수준 비동기 클라이언트

    import asyncio
    from caffeinate import Caffeinate

    async def main():
        async with Caffeinate() as cafe:
            for c in await cafe.cafes.my_cafes():
                print(c.cafe_id, c.name)
            boards = await cafe.boards.all(18886295)
            page = await cafe.boards.articles(18886295, 2)
            article = await cafe.articles.get("https://cafe.naver.com/f-e/cafes/30857348/articles/368535")
            comments = await cafe.comments.all(article.ref)

    asyncio.run(main())
"""
import warnings
from types import TracebackType
from typing import Self

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


class Caffeinate:
    """
    네이버 카페 클라이언트. 기능은 서비스 속성으로 나뉜다.

    - cafes    : 내 카페 목록, 카페 ID 해석
    - boards   : 게시판 목록, 게시글 목록, 공지
    - articles : 게시글 URL 해석, 상세, 글쓰기/수정
    - photos   : 글쓰기용 이미지 업로드
    - comments : 댓글/대댓글 조회, 작성
    - likes    : 좋아요 상태/등록/취소
    - members  : 로그인 식별자, 가입 여부, 내 정보
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
        await self.session.close()

    # ---------------------------------------------------------------- 편의
    @property
    def fingerprint(self) -> Fingerprint:
        return self.session.fingerprint

    async def is_logged_in(self) -> bool:
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
        """
        settings = settings or Settings()
        result = await browser_login(settings, options)
        result.cookies.save(settings.cookies_file)
        save(result.fingerprint, settings.fingerprint_file)
        return cls(settings, fingerprint=result.fingerprint, cookies=CookieStore.load(settings.cookies_file))


def load_fingerprint(settings: Settings | None = None, *, force_new: bool = False) -> Fingerprint:
    """저장된 지문 로드 (없으면 내장 기본값. 로그인하면 로그인 브라우저 값으로 바뀐다)"""
    return load_or_create((settings or Settings()).fingerprint_file, force_new=force_new)
