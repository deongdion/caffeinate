"""댓글 모델"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from ..utils.parsing import JSON, as_dict, as_int, as_list, ms_to_datetime
from .member import Writer


@dataclass(slots=True, kw_only=True)
class Comment:
    """
    gw v4 comments.items[] 항목.
    실측: 대댓글은 replies 중첩이 아니라 평탄화된 목록으로 오고,
          부모 댓글 id 가 ref_id, 대댓글이면 is_reply=True.
    """

    comment_id: int
    ref_id: int
    content: str = ""
    writer: Writer = field(default_factory=Writer)
    updated_at: datetime | None = None
    is_reply: bool = False
    is_deleted: bool = False
    is_mine: bool = False
    is_article_writer: bool = False
    replies: list["Comment"] = field(default_factory=list)  # build_tree() 로 채움
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Any) -> Self:
        d = as_dict(d)
        cid = as_int(d.get("id"))
        return cls(
            comment_id=cid,
            ref_id=as_int(d.get("refId"), cid),
            content=str(d.get("content") or ""),
            writer=Writer.from_api(d.get("writer"), level_src=d),
            updated_at=ms_to_datetime(d.get("updateDate")),
            is_reply=bool(d.get("isRef", False)),
            is_deleted=bool(d.get("isDeleted", False)),
            is_mine=bool(d.get("self", False)),
            is_article_writer=bool(d.get("isArticleWriter", False)),
            raw=d,
        )


def build_tree(flat: list[Comment]) -> list[Comment]:
    """평탄화된 댓글 목록 -> 부모 댓글 리스트 (replies 채움)"""
    roots: dict[int, Comment] = {}
    out: list[Comment] = []
    for c in flat:
        c.replies = []
    for c in flat:
        if not c.is_reply:
            roots[c.comment_id] = c
            out.append(c)
    for c in flat:
        if c.is_reply:
            parent = roots.get(c.ref_id)
            if parent is not None:
                parent.replies.append(c)
            else:
                out.append(c)  # 부모가 다른 페이지에 있는 경우
    return out


@dataclass(slots=True, kw_only=True)
class CommentPage:
    """댓글 목록 한 페이지 (gw v4 comments API result)"""

    items: list[Comment] = field(default_factory=list)
    total: int = 0
    has_next: bool = False
    has_prev: bool = False
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @property
    def tree(self) -> list[Comment]:
        return build_tree(self.items)

    @classmethod
    def from_api(cls, result: Any) -> Self:
        result = as_dict(result)
        items = [Comment.from_api(x) for x in as_list(as_dict(result.get("comments")).get("items"))]
        return cls(
            items=items,
            total=as_int(result.get("displayCommentCount"), len(items)),
            has_next=bool(result.get("hasNext", False)),
            has_prev=bool(result.get("hasPrev", False)),
            raw=result,
        )
