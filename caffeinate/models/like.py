"""좋아요(공감) 모델"""
from dataclasses import dataclass, field
from typing import Any, Self

from ..enums import ReactionType
from ..utils.parsing import JSON, as_dict, as_int, as_list


@dataclass(slots=True, kw_only=True)
class Reaction:
    reaction_type: str
    count: int = 0
    is_reacted: bool = False


@dataclass(slots=True, kw_only=True)
class LikeStatus:
    """like 서비스 /v1/search/contents 의 contents[0]"""

    content_id: str
    is_display: bool = True
    reactions: list[Reaction] = field(default_factory=list)
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    def get(self, reaction: ReactionType | str = ReactionType.LIKE) -> Reaction | None:
        return next((r for r in self.reactions if r.reaction_type == str(reaction)), None)

    @property
    def like_count(self) -> int:
        r = self.get(ReactionType.LIKE)
        return r.count if r else 0

    @property
    def liked(self) -> bool:
        r = self.get(ReactionType.LIKE)
        return bool(r and r.is_reacted)

    @classmethod
    def from_api(cls, content: Any, content_id: str = "") -> Self:
        c = as_dict(content)
        return cls(
            content_id=str(c.get("contentsId") or content_id),
            is_display=bool(c.get("isDisplay", True)),
            reactions=[
                Reaction(
                    reaction_type=str(r.get("reactionType") or ""),
                    count=as_int(r.get("count")),
                    is_reacted=bool(r.get("isReacted", False)),
                )
                for r in map(as_dict, as_list(c.get("reactions")))
            ],
            raw=c,
        )
