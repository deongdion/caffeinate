"""좋아요(공감) 모델"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from ..enums import ReactionType
from ..utils.parsing import JSON, as_dict, as_int, as_list, ms_to_datetime


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


@dataclass(slots=True, kw_only=True)
class LikeUser:
    """likeIt/members users[] 항목 [실측 2026-11-13: 사람 세션 라이브 응답]"""

    index: int = 0
    member_key: str = ""
    nick: str = ""
    image_url: str = ""
    like_at: datetime | None = None
    is_cafe_member: bool = False
    is_current_user: bool = False   # 목록 펼침 권한 여부로 추정
    is_self: bool = False
    is_block_member: bool = False
    is_secede_member: bool = False
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Any) -> Self:
        d = as_dict(d)
        img = as_dict(d.get("image"))
        return cls(
            index=as_int(d.get("index")),
            member_key=str(d.get("memberKey") or ""),
            nick=str(d.get("nick") or ""),
            image_url=str(img.get("url") or ""),
            like_at=ms_to_datetime(d.get("likeItTime")),
            is_cafe_member=bool(d.get("isCafeMember", False)),
            is_current_user=bool(d.get("isCurrentUser", False)),
            is_self=bool(d.get("self", False)),
            is_block_member=bool(d.get("isBlockMember", False)),
            is_secede_member=bool(d.get("isSecedeMember", False)),
            raw=d,
        )


@dataclass(slots=True, kw_only=True)
class LikeMembers:
    """gw/v5 likeIt/members result [실측 2026-11-13 사람 세션 라이브 응답]

    totalCount > users 수면 더 있음. 다음 페이지는 next_timestamp 를 커서로 넘긴다 [실측 2026-11-13 Aside 캡처].
    """

    cafe_id: int = 0
    article_id: int = 0
    total_count: int = 0
    non_creator_total_count: int = 0
    next_timestamp: int | None = None
    users: list[LikeUser] = field(default_factory=list)
    cafe_id_from_cafe: int = 0
    cafe_name: str = ""
    cafe_url: str = ""          # 진짜 slug (예: 별칭으로 resolve 해도 여기서 참 slug 확인 가능)
    article_like_it: bool = False
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Any) -> Self:
        d = as_dict(d)
        cafe = as_dict(d.get("cafe"))
        article = as_dict(d.get("article"))
        return cls(
            cafe_id=as_int(d.get("cafeId")),
            article_id=as_int(d.get("articleId")),
            total_count=as_int(d.get("totalCount")),
            non_creator_total_count=as_int(d.get("nonCreatorTotalCount")),
            next_timestamp=as_int(d.get("nextTimestamp")) or None,
            users=[LikeUser.from_api(u) for u in map(as_dict, as_list(d.get("users")))],
            cafe_id_from_cafe=as_int(cafe.get("id")),
            cafe_name=str(cafe.get("name") or ""),
            cafe_url=str(cafe.get("url") or ""),
            article_like_it=bool(article.get("isLikeIt", False)),
            raw=d,
        )
