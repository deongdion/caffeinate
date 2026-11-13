"""services 의 순수 함수 (네트워크 없음): gw_params, like content_ids, comment_id_from"""
import pytest

from caffeinate import ArticleRef, ParseError
from caffeinate.services.base import gw_params
from caffeinate.services.comments import comment_id_from
from caffeinate.services.likes import content_ids


@pytest.mark.parametrize(
    ("cafe", "flag"),
    [(30857348, "true"), ("30857348", "true"), ("remonterace", "false")],
)
def test_gw_params_use_cafe_id(cafe: int | str, flag: str) -> None:
    assert gw_params(cafe) == {"useCafeId": flag}


def test_gw_params_extra_kept() -> None:
    assert gw_params(1, page=2, size=100) == {"useCafeId": "true", "page": 2, "size": 100}


def test_content_ids_with_and_without_slug() -> None:
    with_slug = ArticleRef(cafe_id=1, article_id=2, cafe_url="abc")
    # loyaltylife 는 카페 30857348 의 참 slug 였을 뿐이라 폴백 후보에서 제거됨 (slug 없으면 빈 튜플)
    assert content_ids(with_slug) == ("1_abc_2",)
    assert content_ids(ArticleRef(cafe_id=1, article_id=2)) == ()


def test_comment_id_from() -> None:
    assert comment_id_from({"commentId": 123, "refCommentId": 0}) == 123
    with pytest.raises(ParseError):
        comment_id_from({"message": {"result": {"commentId": 1}}})


def test_like_members_cursor_url() -> None:
    from caffeinate.core import endpoints

    base = "https://article.cafe.naver.com/gw/v5/cafes/1/articles/2/likeIt/members"
    assert endpoints.like_members(1, 2) == f"{base}?perPage=10"
    # [실측 2026-11-13 Aside] 커서가 perPage 보다 앞
    assert endpoints.like_members(1, 2, 10, 1794461889072) == f"{base}?nextTimestamp=1794461889072&perPage=10"


def test_article_frame_page_entry_forms() -> None:
    from caffeinate.core import endpoints

    base = "https://cafe.naver.com/ca-fe/cafes/1/articles/2"
    assert endpoints.article_frame_page(1, 2) == f"{base}?fromNext=true"
    assert endpoints.article_frame_page(1, 2, 3) == (
        f"{base}?menuid=3&referrerAllArticles=false&fromNext=true"
    )
