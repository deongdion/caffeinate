"""utils/parsing.py - JSON 헬퍼 + 카페 URL 파싱"""
from datetime import UTC, datetime

import pytest

from caffeinate import ParseError
from caffeinate.utils.parsing import as_count, as_dict, as_int, as_list, dig, ms_to_datetime, parse_cafe_url, pick


def test_pick_returns_first_non_none() -> None:
    assert pick({"a": None, "b": 0, "c": 1}, "a", "b", "c") == 0
    assert pick({"a": None}, "a", default="x") == "x"
    assert pick("not a dict", "a", default=3) == 3


def test_dig_nested_and_index() -> None:
    data = {"result": {"items": [{"id": 1}, {"id": 2}]}}
    assert dig(data, "result", "items", 1, "id") == 2
    assert dig(data, "result", "items", -1, "id") == 2
    assert dig(data, "result", "items", 5, "id", default="none") == "none"
    assert dig(data, "result", "missing", default={}) == {}
    assert dig({"a": None}, "a", default=7) == 7


def test_as_helpers() -> None:
    assert as_dict([1]) == {}
    assert as_list({"a": 1}) == []
    assert as_int("12") == 12
    assert as_int(None, 5) == 5
    assert as_int("x") == 0


def test_ms_to_datetime() -> None:
    assert ms_to_datetime(0) is None
    assert ms_to_datetime(None) is None
    assert ms_to_datetime("bad") is None
    assert ms_to_datetime(1_700_000_000_000) == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://cafe.naver.com/f-e/cafes/30857348/articles/368535",
            {"cafe_id": 30857348, "cafe_url": None, "menu_id": None, "article_id": 368535},
        ),
        (
            "https://cafe.naver.com/f-e/cafes/30857348/articles/368535?menuid=12&referrerAllArticles=true",
            {"cafe_id": 30857348, "cafe_url": None, "menu_id": 12, "article_id": 368535},
        ),
        (
            "https://cafe.naver.com/f-e/cafes/18886295/menus/2",
            {"cafe_id": 18886295, "cafe_url": None, "menu_id": 2, "article_id": None},
        ),
        (
            "https://m.cafe.naver.com/ca-fe/web/cafes/remonterace/articles/77",
            {"cafe_id": None, "cafe_url": "remonterace", "menu_id": None, "article_id": 77},
        ),
        (
            "https://cafe.naver.com/remonterace/123456",
            {"cafe_id": None, "cafe_url": "remonterace", "menu_id": None, "article_id": 123456},
        ),
        (
            "https://cafe.naver.com/ArticleRead.nhn?clubid=18886295&menuid=2&articleid=99",
            {"cafe_id": 18886295, "cafe_url": None, "menu_id": 2, "article_id": 99},
        ),
        (
            "https://cafe.naver.com/remonterace?iframe_url=/ArticleRead.nhn%3Fclubid%3D18886295%26articleid%3D5",
            {"cafe_id": 18886295, "cafe_url": "remonterace", "menu_id": None, "article_id": 5},
        ),
        (
            "https://section.cafe.naver.com/cafe-fe/articles/18886295/42",
            {"cafe_id": 18886295, "cafe_url": None, "menu_id": None, "article_id": 42},
        ),
        ("18886295", {"cafe_id": 18886295, "cafe_url": None, "menu_id": None, "article_id": None}),
        ("remonterace", {"cafe_id": None, "cafe_url": "remonterace", "menu_id": None, "article_id": None}),
        (
            "cafe.naver.com/remonterace",
            {"cafe_id": None, "cafe_url": "remonterace", "menu_id": None, "article_id": None},
        ),
    ],
)
def test_parse_cafe_url(url: str, expected: dict[str, object]) -> None:
    assert parse_cafe_url(url) == expected


def test_parse_cafe_url_rejects_other_hosts() -> None:
    with pytest.raises(ParseError):
        parse_cafe_url("https://example.com/f-e/cafes/1/articles/2")
    # ParseError 는 ValueError 이기도 하다
    with pytest.raises(ValueError):
        parse_cafe_url("https://evil.com/x")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # iframe_url_utf8 는 두 번 인코딩돼 있다
        (
            "https://cafe.naver.com/remonterace?iframe_url_utf8=%2FArticleRead.nhn%253Fclubid%3D30857348%2526articleid%3D368535",
            {"cafe_id": 30857348, "cafe_url": "remonterace", "menu_id": None, "article_id": 368535},
        ),
        (
            "https://cafe.naver.com/ArticleList.nhn?search.clubid=30857348&search.menuid=2",
            {"cafe_id": 30857348, "cafe_url": None, "menu_id": 2, "article_id": None},
        ),
        (
            "https://m.cafe.naver.com/ca-fe/remonterace/368535",
            {"cafe_id": None, "cafe_url": "remonterace", "menu_id": None, "article_id": 368535},
        ),
        ("²", {"cafe_id": None, "cafe_url": None, "menu_id": None, "article_id": None}),
    ],
)
def test_parse_cafe_url_more_forms(url: str, expected: dict[str, object]) -> None:
    assert parse_cafe_url(url) == expected


def test_parse_cafe_url_rejects_lookalike_host() -> None:
    with pytest.raises(ParseError):
        parse_cafe_url("https://evilnaver.com/f-e/cafes/1/articles/2")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1234, 1234), ("1,234", 1234), ("4만", 40000), ("3.4만", 34000), ("1.2천", 1200), ("x", 0), (None, 0)],
)
def test_as_count(value: object, expected: int) -> None:
    assert as_count(value) == expected
