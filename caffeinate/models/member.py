"""회원/작성자 모델"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from ..utils.parsing import JSON, as_dict, as_int, ms_to_datetime, pick


@dataclass(slots=True, kw_only=True)
class Writer:
    """게시글/댓글 작성자 (gw v4 writer)"""

    nick: str = ""
    member_key: str = ""
    level: int = 0
    level_name: str = ""
    image_url: str = ""

    @classmethod
    def from_api(cls, d: Any, *, level_src: Any = None) -> Self:
        d = as_dict(d)
        lv = as_dict(level_src) or d  # 댓글은 등급이 writer 밖(comment 본체)에 있음
        image = d.get("image")
        return cls(
            nick=str(pick(d, "nick", "nickName", "nickname", default="")),
            member_key=str(d.get("memberKey") or ""),
            level=as_int(lv.get("memberLevel")),
            level_name=str(lv.get("memberLevelName") or ""),
            image_url=str(image.get("url", "")) if isinstance(image, dict) else "",
        )


@dataclass(slots=True, kw_only=True)
class Identifier:
    """로그인 계정 식별 정보 (member/identifier message.result)"""

    logged_in: bool = False
    user_id: str = ""
    nickname: str = ""
    member_key: str = ""
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Any) -> Self:
        d = as_dict(d)
        return cls(
            logged_in=bool(d.get("loggedIn", False)),
            user_id=str(pick(d, "userId", "userEmail", default="")),
            nickname=str(pick(d, "nickname", "userNickname", default="")),
            member_key=str(d.get("memberKey") or ""),
            raw=d,
        )


@dataclass(slots=True, kw_only=True)
class Membership:
    """카페 내 내 멤버 정보 (cafeinfo members result)

    비멤버: {cafeMember, cafeApply} / 멤버: + nickname, memberKey, memberLevel, memberStat [실측]
    """

    is_member: bool = False
    applied: bool = False
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Any) -> Self:
        d = as_dict(d)
        return cls(
            is_member=bool(d.get("cafeMember", False)),
            applied=bool(d.get("cafeApply", False)),
            raw=d,
        )

    @property
    def cafe_nickname(self) -> str:
        return str(self.raw.get("nickname") or "")

    @property
    def member_key(self) -> str:
        return str(self.raw.get("memberKey") or "")

    @property
    def level(self) -> int:
        return as_int(as_dict(self.raw.get("memberLevel")).get("level"))

    @property
    def level_name(self) -> str:
        return str(as_dict(self.raw.get("memberLevel")).get("levelName") or "")

    @property
    def stats(self) -> JSON:
        return as_dict(self.raw.get("memberStat"))


@dataclass(slots=True, kw_only=True)
class CafeGrade:
    """카페 내 내 등급/활동 통계 (cafemain v1.0 cafes/{id}/my ?memberDataOptions=NFLEA)

    [실측 2026-11-13] memberLevel.config 의 needXxxCount 가 다음 등급 조건,
    memberStat 가 현재 활동 통계. 미멤버면 서버가 500(40003) 을 돌려준다.
    """

    nickname: str = ""
    member_key: str = ""
    joined_at: datetime | None = None
    level: int = 0
    level_name: str = ""
    level_icon_id: int = 0
    next_level: JSON = field(default_factory=dict)   # 다음 등급 조건 (needXxxCount, levelUpPolicy)
    stats: JSON = field(default_factory=dict)        # visitCount/articleCount/commentCount/likeCount
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Any) -> Self:
        d = as_dict(d)
        lv = as_dict(d.get("memberLevel"))
        return cls(
            nickname=str(d.get("nickname") or ""),
            member_key=str(d.get("memberKey") or ""),
            joined_at=ms_to_datetime(d.get("joinedAt")),
            level=as_int(lv.get("level")),
            level_name=str(lv.get("levelName") or ""),
            level_icon_id=as_int(lv.get("levelIconId")),
            next_level=as_dict(lv.get("config")),
            stats=as_dict(d.get("memberStat")),
            raw=d,
        )


@dataclass(slots=True, kw_only=True)
class MyInfo:
    """카페에서의 내 정보 통합"""

    cafe_id: int
    identifier: Identifier
    membership: Membership
    grade: CafeGrade | None = None   # 등급/활동 통계 [실측 2026-11-13]

    @property
    def user_id(self) -> str:
        return self.identifier.user_id

    @property
    def nickname(self) -> str:
        return self.identifier.nickname

    @property
    def is_member(self) -> bool:
        return self.membership.is_member
