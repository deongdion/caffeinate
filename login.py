"""
Camoufox 로그인 실행 (쿠키 + 지문을 프로필 폴더에 저장)

    python login.py               # 자동 입력 모드
                                  #   자격증명은 NAVER_ID / NAVER_PASSWORD 환경변수,
                                  #   없으면 터미널에서 직접 입력받는다 (비밀번호 입력은 화면에 안 보임)
    python login.py --manual      # 수동 모드 (창만 띄우고 직접 로그인)
    python login.py --debug       # 폴링마다 페이지 상태를 [D] 로 전부 덤프 (미지 화면 실측용)
    python login.py --profile-dir D:/naver   # 프로필 폴더 지정 (기본: CAFFEINATE_PROFILE_DIR 또는 자동)

"로그인 상태 유지"는 항상 체크해서 제출한다 (NID_AUT 만료 연장).
자동 모드는 사람처럼 타이핑해서 로그인하고, 화면 변화(2차 인증/캡차/기기 등록 등)를
계속 분류해 콘솔에 보고한다. 저장 후에는 `Caffeinate()` 가 같은 프로필에서 쿠키를 읽는다.
"""
import argparse
import asyncio
import getpass
import os
import sys

from caffeinate import Caffeinate, LoginError, LoginOptions, Settings


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="네이버 로그인 (Camoufox) -> caffeinate 프로필에 쿠키/지문 저장")
    p.add_argument("--manual", action="store_true", help="창만 띄우고 직접 로그인")
    p.add_argument("--debug", action="store_true", help="폴링마다 페이지 상태 덤프")
    p.add_argument("--profile-dir", help="쿠키/지문/로그인 프로필 폴더 (기본: 자동 결정)")
    p.add_argument("--timeout", type=float, default=300.0, help="로그인 대기 최대 시간(초, 기본 300)")
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    settings = Settings(profile_dir=args.profile_dir) if args.profile_dir else Settings()
    if args.manual:
        options = LoginOptions(debug=args.debug, timeout=args.timeout)
        print("[수동 모드] 창에서 네이버에 로그인해주세요.")
    else:
        username = os.environ.get("NAVER_ID") or input("네이버 아이디: ").strip()
        password = os.environ.get("NAVER_PASSWORD") or getpass.getpass("네이버 비밀번호: ")
        options = LoginOptions(username=username, password=password, debug=args.debug, timeout=args.timeout)

    print(f"프로필 폴더: {settings.profile_dir}")
    async with await Caffeinate.login(settings, options) as cafe:
        print("\n로그인:", await cafe.is_logged_in())
        print(cafe.fingerprint.describe())


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(main())
    except LoginError as e:
        sys.exit(f"\n[로그인 실패] {e}")
    except KeyboardInterrupt:
        sys.exit("\n중단됨")
