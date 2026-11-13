"""오프라인 테스트 공통 설정 - 실제 프로필(쿠키)을 절대 건드리지 않도록 임시 폴더로 돌린다"""
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    profile = tmp_path / "profile"
    monkeypatch.setenv("CAFFEINATE_PROFILE_DIR", str(profile))
    yield profile
