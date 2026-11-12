"""게시판(메뉴) 모델"""
from dataclasses import dataclass, field
from typing import Any, Self

from ..enums import BoardType, MenuType
from ..utils.parsing import JSON, as_dict, as_int, pick


@dataclass(slots=True, kw_only=True)
class Board:
    """cafe-cafemain-api result.menus[]"""

    menu_id: int
    name: str = ""
    menu_type: MenuType = MenuType.BOARD
    board_type: BoardType = BoardType.LIST
    order: int = 0
    hidden: bool = False
    raw: JSON = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_separator(self) -> bool:
        return self.menu_type is MenuType.SEPARATOR

    @classmethod
    def from_api(cls, d: Any) -> Self:
        d = as_dict(d)
        return cls(
            menu_id=as_int(pick(d, "menuId", "menuid", "id")),
            name=str(pick(d, "name", "menuName", "title", default="")),
            menu_type=MenuType(pick(d, "menuType", default="B")),
            board_type=BoardType(pick(d, "boardType", default="L")),
            order=as_int(d.get("order")),
            hidden=bool(d.get("hidden", False)),
            raw=d,
        )
