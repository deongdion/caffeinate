"""
caffeinate 라이브러리 사용 예 (비로그인으로도 동작하는 읽기 기능만 사용, 실서버 호출)

    python example.py              # 기본 카페/게시글
    python example.py --debug      # 요청 디버그 로그 출력 (logging "caffeinate")
"""
import asyncio
import sys

import caffeinate
from caffeinate import Caffeinate, CaffeinateError, SortBy, build_tree

CAFE = "remonterace"  # 카페 18886295 (게시판/목록 예시)
# 별개 카페(30857348, slug loyaltylife)의 게시글 (상세/댓글/좋아요 예시)
ARTICLE_URL = "https://cafe.naver.com/f-e/cafes/30857348/articles/368535"


def first_line(text: str, width: int = 40) -> str:
    """댓글 첫 줄 (스티커/이미지만 있는 댓글은 내용이 비어 있다)"""
    line = text.strip().splitlines()[0] if text.strip() else "(내용 없음)"
    return line if len(line) <= width else line[: width - 1] + "…"


async def main() -> None:
    async with Caffeinate() as cafe:
        print(cafe.fingerprint.describe(), "\n")
        print("로그인:", await cafe.is_logged_in())

        cafe_id = await cafe.cafes.resolve_id(CAFE)
        boards = await cafe.boards.all(cafe_id)
        print(f"\n카페 {cafe_id} 게시판:", [f"{b.menu_id}:{b.name}" for b in boards])

        # 하나의 AsyncSession 으로 여러 게시판을 동시에 조회
        pages = await asyncio.gather(
            *(cafe.boards.articles(cafe_id, b.menu_id, page_size=3, sort_by=SortBy.TIME) for b in boards)
        )
        for b, page in zip(boards, pages, strict=True):
            print(f"  [{b.name}] " + (" | ".join(a.subject for a in page) or "-"))

        article, comments, like = await asyncio.gather(
            cafe.articles.get(ARTICLE_URL),
            cafe.comments.all(ARTICLE_URL),
            cafe.likes.status(ARTICLE_URL),
        )
        print(f"\n{article.subject} - {article.writer.nick} / 좋아요 {like.like_count} / 댓글 {len(comments)}")
        for c in build_tree(comments)[:3]:
            print(f"  {c.writer.nick}: {first_line(c.content)} (답글 {len(c.replies)})")


if __name__ == "__main__":
    # Windows 콘솔(cp949)에서 이모지 등이 든 제목을 출력하다 UnicodeEncodeError 가 나지 않게
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    if "--debug" in sys.argv:
        caffeinate.enable_logging()
    try:
        asyncio.run(main())
    except CaffeinateError as e:
        # 예외 메시지에는 해결 방법(hint)이 함께 들어 있다 (예: 쿠키 만료 -> 다시 로그인)
        sys.exit(f"\n[오류] {type(e).__name__}: {e}")
