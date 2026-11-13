"""models/* from_api - 작은 픽스처 dict (실측 응답 키 기준)"""
from datetime import UTC, datetime

from caffeinate import (
    Article,
    ArticleListItemType,
    ArticleSummary,
    Board,
    BoardType,
    Cafe,
    Comment,
    CommentPage,
    Cookie,
    Fingerprint,
    LikeMembers,
    LikeStatus,
    MenuType,
    build_tree,
)

TS = 1_700_000_000_000
DT = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)


def test_board_from_api_and_separator() -> None:
    b = Board.from_api({"menuId": 2, "name": "자유", "menuType": "B", "boardType": "L", "order": 3})
    assert (b.menu_id, b.name, b.menu_type, b.board_type, b.order) == (2, "자유", MenuType.BOARD, BoardType.LIST, 3)
    assert not b.is_separator
    assert Board.from_api({"menuId": 9, "menuType": "S"}).is_separator


def test_cafe_from_api_link() -> None:
    c = Cafe.from_api({"cafeId": 1, "cafeName": "레몬", "cafeUrl": "remonterace", "image": {"url": "u"}})
    assert (c.cafe_id, c.name, c.url, c.image_url) == (1, "레몬", "remonterace", "u")
    assert c.link == "https://cafe.naver.com/remonterace"
    assert Cafe.from_api({"id": 5}).link == "https://cafe.naver.com/f-e/cafes/5"


def test_article_summary_from_api() -> None:
    s = ArticleSummary.from_api({
        "type": "ARTICLE",
        "item": {
            "articleId": 10, "cafeId": 1, "menuId": 2, "subject": "제목",
            "writerInfo": {"nickName": "닉", "memberKey": "k"},
            "writeDateTimestamp": TS, "readCount": 3, "commentCount": 4, "likeCount": 5, "hasImage": True,
        },
    })
    assert (s.article_id, s.subject, s.writer_nick, s.writer_key) == (10, "제목", "닉", "k")
    assert s.written_at == DT
    assert (s.read_count, s.comment_count, s.like_count, s.has_image) == (3, 4, 5, True)
    assert s.item_type is ArticleListItemType.ARTICLE
    assert s.ref.cafe_id == 1 and s.ref.menu_id == 2


def test_article_from_api_full() -> None:
    a = Article.from_api({
        "cafeId": 1,
        "cafe": {"id": 1, "name": "레몬", "url": "remonterace"},
        "article": {
            "id": 10, "subject": "제목", "menu": {"id": 2, "name": "자유"},
            "writer": {"nick": "닉"}, "writeDate": TS, "contentHtml": "<p>안녕<br>하세요</p>",
        },
        "authority": {"isWriteComment": True},
    })
    assert a.article_id == 10 and a.subject == "제목" and a.menu.menu_id == 2
    assert a.writer.nick == "닉"
    assert a.written_at == DT
    assert a.authority.can_write_comment
    assert not a.is_snippet
    assert a.ref.cafe_url == "remonterace" and a.ref.link.endswith("/cafes/1/articles/10")
    assert "안녕" in a.content_text


def test_article_from_api_snippet_for_non_member() -> None:
    a = Article.from_api({
        "cafeId": 1, "articleId": 10, "menuId": 2, "subject": "요약글", "summary": "a < b",
        "cafeViewModel": {"cafeId": 1, "cafeName": "레몬"}, "menuViewModel": {"name": "자유"},
        "writer": {"nick": "닉", "memberLevelName": "새싹"},
    })
    assert a.is_snippet
    assert a.article_id == 10 and a.menu.menu_id == 2
    assert a.content_html == "a &lt; b"


def test_comment_page_and_tree() -> None:
    page = CommentPage.from_api({
        "comments": {"items": [
            {"id": 1, "refId": 1, "content": "부모", "writer": {"nick": "a"}, "updateDate": TS},
            {"id": 2, "refId": 1, "content": "답글", "isRef": True, "writer": {"nick": "b"}},
            {"id": 3, "refId": 99, "content": "고아 답글", "isRef": True},
            {"id": 4, "content": "둘째"},
        ]},
        "displayCommentCount": 4, "hasNext": True,
    })
    assert page.total == 4 and page.has_next and not page.has_prev
    assert page.items[0].updated_at == DT
    assert page.items[3].ref_id == 4  # refId 없으면 자기 id
    tree = build_tree(page.items)
    assert [c.comment_id for c in tree] == [1, 4, 3]  # 부모가 없는 답글은 루트 뒤로
    assert [r.comment_id for r in tree[0].replies] == [2]
    # 다시 호출해도 replies 가 중복되지 않음
    assert [r.comment_id for r in build_tree(page.items)[0].replies] == [2]


def test_comment_from_api_defaults() -> None:
    c = Comment.from_api({})
    assert c.comment_id == 0 and c.content == "" and c.replies == []


def test_like_status() -> None:
    s = LikeStatus.from_api(
        {"contentsId": "1_x_2", "reactions": [{"reactionType": "like", "count": 7, "isReacted": True}]}
    )
    assert s.like_count == 7 and s.liked and s.content_id == "1_x_2"
    empty = LikeStatus.from_api({}, "fallback")
    assert empty.like_count == 0 and not empty.liked and empty.content_id == "fallback"


def test_like_members() -> None:
    m = LikeMembers.from_api({
        "cafeId": 1, "articleId": 2, "totalCount": 3, "nextTimestamp": TS,
        "users": [{"index": 0, "nick": "닉", "memberKey": "k", "likeItTime": TS, "image": {"url": "i"}}],
        "cafe": {"id": 1, "name": "레몬", "url": "loyaltylife"}, "article": {"isLikeIt": True},
    })
    assert m.total_count == 3 and m.next_timestamp == TS and m.cafe_url == "loyaltylife"
    assert m.article_like_it
    assert m.users[0].nick == "닉" and m.users[0].like_at == DT and m.users[0].image_url == "i"


def test_cookie_matches() -> None:
    c = Cookie(name="NID_AUT", value="v", domain=".naver.com", path="/", secure=True)
    assert c.matches("https://cafe.naver.com/x")
    assert c.matches("https://naver.com/")
    assert not c.matches("http://cafe.naver.com/x")  # secure
    assert not c.matches("https://naver.com.evil.com/")
    host_only = Cookie(name="a", value="b", domain="cafe.naver.com", path="/api")
    assert host_only.matches("https://cafe.naver.com/api/x")
    assert not host_only.matches("https://apis.naver.com/api/x")
    assert not host_only.matches("https://cafe.naver.com/apix")
    assert Cookie(name="a", value="b", expires=1).is_expired
    assert Cookie.from_dict(c.to_dict()) == c


def test_fingerprint_roundtrip() -> None:
    from caffeinate.core import fingerprint as fp_mod

    fp = fp_mod.builtin()
    again = Fingerprint.from_dict(fp.to_dict())
    assert again.ja3 == fp.ja3 and again.user_agent == fp.user_agent and again.major == fp.major
    assert not fp.from_login


def test_page_info_uses_requested_page() -> None:
    # [실측] 5페이지짜리 게시판의 3페이지: 다음 묶음 버튼은 없지만 4페이지는 있다
    from caffeinate.models import PageInfo

    p = PageInfo.from_api({"lastNavigationPageNumber": 5, "visibleNextButton": False}, page=3)
    assert p.has_next and not p.has_next_block
    last = PageInfo.from_api({"lastNavigationPageNumber": 5, "visibleNextButton": False}, page=5)
    assert not last.has_next


def test_comment_image_and_reply_member() -> None:
    from caffeinate.models import Comment

    c = Comment.from_api({"id": 2, "refId": 1, "isRef": True, "image": {"url": "u"}, "replyMember": {"nick": "n"}})
    assert c.image_url == "u" and c.reply_to_nick == "n" and c.ref_id == 1


def test_comment_best_fields() -> None:
    from caffeinate.models import Comment

    c = Comment.from_api({"id": 5, "refId": 5, "isBest": True, "likeItCount": 7, "replyCount": 2})
    assert (c.is_best, c.like_count, c.reply_count) == (True, 7, 2)
    assert Comment.from_api({"id": 6, "bestComment": True}).is_best
    assert not Comment.from_api({"id": 7}).is_best
