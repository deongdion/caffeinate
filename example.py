"""
caffeinate 라이브러리 사용 예 (비로그인으로도 동작하는 읽기 기능만 사용)

    python example.py
"""
import asyncio

from caffeinate import Caffeinate, SortBy, build_tree

CAFE = "remonterace"
ARTICLE_URL = "https://cafe.naver.com/f-e/cafes/30857348/articles/368535"


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
        print(f"\n{article.subject} - {article.writer.nick} / 좋아요 {like.like_count}")
        for c in build_tree(comments)[:3]:
            print(f"  {c.writer.nick}: {c.content.splitlines()[0]} (답글 {len(c.replies)})")


if __name__ == "__main__":
    asyncio.run(main())
