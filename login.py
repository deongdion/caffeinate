"""
Camoufox 로그인 실행

    python login.py               # 자동 입력 모드
                                  #   자격증명은 NAVER_ID / NAVER_PASSWORD 환경변수,
                                  #   없으면 터미널에서 직접 입력받는다 (입력은 화면에 안 보임)
    python login.py --debug       # 폴링마다 페이지 상태를 [D] 로 전부 덤프 (미지 화면 실측용)
    python login.py --manual      # 수동 모드 (창만 띄우고 직접 로그인)

"로그인 상태 유지"는 항상 체크해서 제출한다 (NID_AUT 만료 연장).
자동 모드는 사람처럼 타이핑해서 로그인하고, 화면 변화(2차 인증/캡차/기기 등록 등)를
계속 분류해 콘솔에 보고한다.
"""
import asyncio
import getpass
import os
import sys

from caffeinate import Caffeinate, LoginOptions


async def main() -> None:
    debug = "--debug" in sys.argv
    if "--manual" in sys.argv:
        options = LoginOptions(debug=debug)
        print("[수동 모드] 창에서 네이버에 로그인해주세요.")
    else:
        username = os.environ.get("NAVER_ID") or input("네이버 아이디: ")
        password = os.environ.get("NAVER_PASSWORD") or getpass.getpass("네이버 비밀번호: ")
        options = LoginOptions(username=username, password=password, debug=debug)

    async with await Caffeinate.login(options=options) as cafe:
        print("\n로그인:", await cafe.is_logged_in())
        print(cafe.fingerprint.describe())


if __name__ == "__main__":
    asyncio.run(main())
