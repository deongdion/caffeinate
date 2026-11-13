"""
caffeinate 둘러보기 - 읽기, (선택) 쓰기, 예외 처리, 요청 간격

    python example.py                              # 읽기만 (공개 카페, 로그인 없이도 동작)
    python example.py --write <내 카페> <게시판번호>   # + 내 카페에 글/좋아요/댓글을 쓰고 바로 지운다
    python example.py --debug                      # 요청 로그 출력

--write 는 로그인이 필요하다. 로그인돼 있지 않으면 브라우저(Camoufox, `python -m camoufox fetch`)를 띄운다:
환경변수 NAVER_ID / NAVER_PASSWORD 가 있으면 자동 입력, 없으면 창에서 직접 로그인. 한 번 로그인하면
쿠키가 프로필 폴더에 저장되어 다음부터는 바로 쓴다.
"""
import argparse
import asyncio
import os
import struct
import sys
import zlib

import caffeinate
from caffeinate import (
    ArticleNotFoundError,
    Caffeinate,
    CaffeinateError,
    LoginOptions,
    NaverAPIError,
    NotLoggedInError,
    PermissionDeniedError,
    Settings,
    build_tree,
)

READ_CAFE = "remonterace"  # 공개 카페 slug (숫자 ID 18886295 나 카페 URL 도 된다)
READ_MENU = 2
ARTICLE_URL = "https://cafe.naver.com/f-e/cafes/30857348/articles/368535"


async def open_client(settings: Settings, *, need_login: bool) -> Caffeinate:
    """클라이언트 열기. 로그인이 필요한데 안 돼 있으면 브라우저로 로그인한다 (처음 한 번)"""
    cafe = Caffeinate(settings)
    if not need_login or await cafe.is_logged_in():
        return cafe
    await cafe.close()
    user, password = os.environ.get("NAVER_ID"), os.environ.get("NAVER_PASSWORD")
    if user and password:
        print("로그인: NAVER_ID / NAVER_PASSWORD 로 자동 입력합니다.")
        return await Caffeinate.login(settings, LoginOptions(username=user, password=password))
    print("로그인: 브라우저 창에서 네이버에 로그인해 주세요.")
    return await Caffeinate.login(settings)  # 수동 모드


async def read_demo(cafe: Caffeinate) -> None:
    # 카페는 slug 로 바로 쓴다. slug -> ID 해석은 한 번만 하고 캐시된다.
    boards = await cafe.boards.all(READ_CAFE)
    print(f"[{READ_CAFE}] 게시판:", ", ".join(f"{b.menu_id}:{b.name}" for b in boards[:8]), "...")

    # 페이지 번호를 신경 쓰지 않고 글을 순서대로 (limit 개까지)
    async for a in cafe.boards.iter_articles(READ_CAFE, READ_MENU, limit=5):
        print(f"  #{a.article_id} {a.subject[:40]} (댓글 {a.comment_count})")

    # 게시글 하나: 본문 + 댓글 트리 + 좋아요 (같은 세션으로 동시 요청)
    article, comments, like = await asyncio.gather(
        cafe.articles.get(ARTICLE_URL),
        cafe.comments.all(ARTICLE_URL),
        cafe.likes.status(ARTICLE_URL),
    )
    print(f"\n{article.subject} - {article.writer.nick} / 좋아요 {like.like_count} / 댓글 {len(comments)}")
    for c in build_tree(comments)[:3]:
        print(f"  {c.writer.nick}: {(c.content.strip() or '(사진/스티커)').splitlines()[0][:40]} (답글 {len(c.replies)})")


async def error_demo(cafe: Caffeinate) -> None:
    # 서버 오류는 종류별 예외로 온다 (모두 NaverAPIError 하위라 한 번에 잡아도 된다)
    cafe_id = await cafe.cafes.resolve_id(READ_CAFE)  # 앞에서 해석한 값이 캐시돼 있어 요청 없음
    try:
        await cafe.articles.get(f"https://cafe.naver.com/f-e/cafes/{cafe_id}/articles/999999999")
    except ArticleNotFoundError as e:
        print(f"\n없는 글 -> {type(e).__name__} (HTTP {e.status}, 코드 {e.code})")
    except PermissionDeniedError as e:
        print(f"\n권한 없음 -> {e.hint}")
    except NaverAPIError as e:
        print(f"\n그 밖의 서버 오류 -> {e!r}")


async def write_demo(cafe: Caffeinate, cafe_slug: str, menu_id: int) -> None:
    info = await cafe.members.my_info(cafe_slug)
    print(f"\n[{cafe_slug}] {info.nickname} / 멤버 {info.is_member}")

    # images 에는 파일 경로, bytes, (bytes, 파일명), 이미 올린 UploadedImage 를 섞어 넣을 수 있다 (순서 유지)
    images: list[caffeinate.ImageLike] = [solid_png(255, 120, 0), (solid_png(0, 120, 255), "blue.png")]
    if os.path.exists("photo.png"):
        images.append("photo.png")
    ref = await cafe.articles.write(cafe_slug, menu_id, "caffeinate 예제 글", "본문 첫 줄\n\n셋째 줄", images=images)
    print(f"글 작성: {ref.link}")
    try:
        article = await cafe.articles.get(ref)
        print(f"  제목 {article.subject!r}, 이미지 {article.content_html.count('<img')}장")

        liked = await cafe.likes.like(ref)  # -> LikeStatus
        print(f"좋아요: {liked.like_count}개, 내가 누름={liked.liked}")
        unliked = await cafe.likes.unlike(ref)
        print(f"좋아요 취소: {unliked.like_count}개, 내가 누름={unliked.liked}")

        comment_id = await cafe.comments.add(ref, "사진 댓글", image=(solid_png(0, 200, 80), "green.png"))
        print(f"댓글 작성: {comment_id}")
        await cafe.comments.delete(ref, comment_id)  # 성공하면 None, 실패하면 예외
        print("댓글 삭제 완료")
    finally:
        await cafe.articles.delete(ref)  # 중간에 실패해도 글은 지운다
        print(f"글 삭제: {ref.article_id}")

    try:
        await cafe.articles.get(ref)
    except ArticleNotFoundError:
        print("  삭제 확인: 이제 ArticleNotFoundError")


def solid_png(r: int, g: int, b: int, size: int = 32) -> bytes:
    """단색 PNG (예제용 - 실제로는 파일 경로나 이미지 bytes 를 넘기면 된다)"""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + bytes((r, g, b)) * size for _ in range(size))
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


async def main() -> None:
    p = argparse.ArgumentParser(description="caffeinate 예제")
    p.add_argument("--write", nargs=2, metavar=("CAFE", "MENU"), help="내 카페(slug/ID)와 게시판 번호 - 쓰고 지운다")
    p.add_argument("--debug", action="store_true", help="요청 로그 출력")
    args = p.parse_args()
    if args.debug:
        caffeinate.enable_logging()

    # 요청 시작 간격을 벌려 서버 부담/제재 위험을 줄인다 (쓰기는 넉넉하게)
    settings = Settings(min_request_interval=1.5 if args.write else 0.3)
    async with await open_client(settings, need_login=bool(args.write)) as cafe:
        await read_demo(cafe)
        await error_demo(cafe)
        if args.write:
            await write_demo(cafe, args.write[0], int(args.write[1]))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if reconfigure := getattr(stream, "reconfigure", None):
            reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(main())
    except NotLoggedInError as e:
        sys.exit(f"[로그인 필요] {e}")
    except CaffeinateError as e:
        sys.exit(f"[오류] {e}")
