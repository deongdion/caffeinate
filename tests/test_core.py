"""core: 예외 메시지(hint), Settings, parse_json 에러 매핑, 공개 API, 오프라인 클라이언트"""
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import caffeinate
from caffeinate import (
    ArticleRef,
    Caffeinate,
    CaffeinateError,
    NaverAPIError,
    NetworkError,
    NotLoggedInError,
    ParseError,
    Settings,
)
from caffeinate.core import config
from caffeinate.core.session import parse_json


# ---------------------------------------------------------------- 예외
def test_error_hierarchy() -> None:
    assert issubclass(NotLoggedInError, NaverAPIError)
    assert issubclass(NaverAPIError, CaffeinateError)
    assert issubclass(ParseError, ValueError)


def test_not_logged_in_message_tells_user_to_relogin() -> None:
    e = NotLoggedInError("API 오류 401: https://x (0004 로그인하지 않음)", 401, "{}", "0004")
    text = str(e)
    assert text.startswith("API 오류 401")
    assert "다시 로그인" in text and "login.py" in text
    assert e.status == 401 and e.code == "0004"
    assert "status=401" in repr(e)


def test_plain_api_error_has_no_hint() -> None:
    assert str(NaverAPIError("x", 500)) == "x"
    assert NetworkError("y").hint and "y" in str(NetworkError("y"))


# ---------------------------------------------------------------- Settings
def test_settings_profile_dir_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAFFEINATE_PROFILE_DIR", str(tmp_path / "p"))
    s = Settings()
    assert s.profile_dir == tmp_path / "p"
    assert s.cookies_file == tmp_path / "p" / "cookies.json"


def test_settings_accepts_str_profile_dir(tmp_path: Path) -> None:
    s = Settings(profile_dir=str(tmp_path))  # type: ignore[arg-type]
    assert s.fingerprint_file == tmp_path / "fingerprint.json"


def test_settings_default_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAFFEINATE_PROFILE_DIR", raising=False)
    # 소스 체크아웃에서는 기존 위치(패키지 안 profile/) 그대로
    assert Settings().profile_dir == config.DEFAULT_PROFILE_DIR


def test_settings_site_packages_uses_user_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAFFEINATE_PROFILE_DIR", raising=False)
    fake_pkg = tmp_path / "site-packages" / "caffeinate"
    monkeypatch.setattr(config, "PACKAGE_DIR", fake_pkg)
    monkeypatch.setattr(config, "DEFAULT_PROFILE_DIR", fake_pkg / "profile")
    monkeypatch.setattr(config, "user_data_dir", lambda app="caffeinate": tmp_path / "user" / app)
    assert Settings().profile_dir == tmp_path / "user" / "caffeinate"
    # 예전 설치에 profile/ 이 남아 있으면 그대로 사용 (하위 호환)
    (fake_pkg / "profile").mkdir(parents=True)
    assert Settings().profile_dir == fake_pkg / "profile"


@pytest.mark.parametrize("kw", [{"timeout": 0}, {"max_retries": -1}, {"max_clients": 0}])
def test_settings_validation(kw: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Settings(**kw)


# ---------------------------------------------------------------- parse_json
@dataclass
class FakeResponse:
    status_code: int
    data: Any = None
    text: str = field(default="")

    def json(self) -> Any:
        if self.data is None:
            raise ValueError("no json")
        return self.data


def test_parse_json_ok() -> None:
    assert parse_json(FakeResponse(200, {"result": 1}), "u") == {"result": 1}  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "body", "exc", "code"),
    [
        (401, {"result": {"errorCode": "0004", "reason": "로그인"}}, NotLoggedInError, "0004"),
        (500, {"error": {"errorCode": "10004", "message": "NaverUser"}}, NotLoggedInError, "10004"),
        (403, {"message": {"error": {"code": "2001", "msg": "연달아"}}}, NaverAPIError, "2001"),
        (500, None, NaverAPIError, None),
    ],
)
def test_parse_json_error_mapping(status: int, body: Any, exc: type[Exception], code: str | None) -> None:
    with pytest.raises(exc) as info:
        parse_json(FakeResponse(status, body, "body"), "https://x")  # type: ignore[arg-type]
    assert type(info.value) is exc
    assert getattr(info.value, "code", None) == code


def test_parse_json_non_json_200() -> None:
    with pytest.raises(NaverAPIError):
        parse_json(FakeResponse(200, None, "<html>"), "u")  # type: ignore[arg-type]


# ---------------------------------------------------------------- 클라이언트 (오프라인)
def test_client_offline_construct_and_require_login(_isolated_profile: Path) -> None:
    cafe = Caffeinate()
    assert cafe.settings.profile_dir == _isolated_profile
    assert not cafe.has_login_cookies
    assert "비로그인" in repr(cafe)

    async def write() -> None:
        await cafe.comments.add(ArticleRef(cafe_id=1, article_id=2), "x")

    # 쿠키가 없으면 서버 요청 전에 막고, 메시지에 재로그인 안내가 있다
    with pytest.raises(NotLoggedInError, match="로그인"):
        asyncio.run(write())


def test_run_refuses_inside_running_loop() -> None:
    async def job(cafe: Caffeinate) -> int:
        return 1

    async def inner() -> None:
        with pytest.raises(RuntimeError, match="이벤트 루프"):
            caffeinate.run(job)

    asyncio.run(inner())


def test_enable_logging_idempotent() -> None:
    log = caffeinate.enable_logging()
    n = len(log.handlers)
    caffeinate.enable_logging()
    assert len(log.handlers) == n
    for h in [h for h in log.handlers if getattr(h, "_caffeinate", False)]:
        log.removeHandler(h)
    log.setLevel(0)


def test_public_exports() -> None:
    for name in caffeinate.__all__:
        assert hasattr(caffeinate, name), name
    assert (Path(caffeinate.__file__).parent / "py.typed").exists()
