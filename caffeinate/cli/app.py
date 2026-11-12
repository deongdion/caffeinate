"""
caffeinate 통합 CLI

    python -m caffeinate.cli login                         # 로그인 창 -> 쿠키 수집
    python -m caffeinate.cli status                        # 로그인/쿠키 상태
    python -m caffeinate.cli fingerprint [--new]           # PC 지문 확인/재생성
    python -m caffeinate.cli check-fingerprint             # TLS/HTTP2/헤더 순서 실측
    python -m caffeinate.cli cafes                         # 내 카페 목록
    python -m caffeinate.cli boards --cafe remonterace [--articles 2]
    python -m caffeinate.cli myinfo --cafe remonterace
    python -m caffeinate.cli article --article <URL>       # 게시글 읽기
    python -m caffeinate.cli post --cafe .. --menu 2 --title .. --body ..
    python -m caffeinate.cli comment --article <URL> [--add "내용"]
    python -m caffeinate.cli reply --article <URL> [--comment <ID> --text "내용"]
    python -m caffeinate.cli like --article <URL> [--on | --off]
"""
import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence

from ..core.config import Settings
from ..core.errors import CaffeinateError, NotLoggedInError
from . import commands as c
from .output import setup_console

Handler = Callable[[argparse.Namespace, Settings], Awaitable[int]]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m caffeinate.cli",
        description="네이버 카페 자동화 (curl_cffi)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="<command>")

    def add(name: str, handler: Handler, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.set_defaults(handler=handler)
        return p

    p = add("login", c.cmd_login, "로그인 창을 띄우고 쿠키 수집")
    p.add_argument("--port", type=int, default=0, help="이미 띄운 디버그 브라우저 포트에 연결")
    p.add_argument("--timeout", type=float, default=300.0, help="로그인 대기 시간(초)")

    add("status", c.cmd_status, "쿠키/로그인 상태 확인")

    p = add("set", c.cmd_set, "NID_AUT/NID_SES 수동 등록")
    p.add_argument("--aut", required=True)
    p.add_argument("--ses", "--sei", dest="ses", required=True)

    p = add("fingerprint", c.cmd_fingerprint, "현재 PC 지문 보기")
    p.add_argument("--new", action="store_true", help="지문 재생성")

    add("check-fingerprint", c.cmd_check_fingerprint, "TLS/HTTP2/헤더 순서 실측 (tls.peet.ws)")

    p = add("cafes", c.cmd_cafes, "내 카페 목록")
    p.add_argument("--json", action="store_true")

    p = add("boards", c.cmd_boards, "게시판 목록 (+ 게시글 목록)")
    p.add_argument("--cafe", required=True, help="카페 ID / slug / URL")
    p.add_argument("--articles", type=int, metavar="MENU_ID", help="해당 게시판 글 목록도 출력")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--all", action="store_true", help="구분선 메뉴 포함")
    p.add_argument("--json", action="store_true")

    p = add("myinfo", c.cmd_myinfo, "카페 내 내 정보 (로그인 필요)")
    p.add_argument("--cafe", required=True)
    p.add_argument("--json", action="store_true")

    p = add("article", c.cmd_article, "게시글 읽기")
    p.add_argument("--article", required=True, help="게시글 URL")
    p.add_argument("--json", action="store_true")
    p.add_argument("--raw", action="store_true", help="--json 에 원본 응답 포함")

    p = add("post", c.cmd_post, "게시글 작성 (이미지 첨부 가능)")
    p.add_argument("--cafe", required=True)
    p.add_argument("--menu", type=int, required=True)
    p.add_argument("--title", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--body")
    g.add_argument("--body-file")
    p.add_argument("--image", action="append", default=[], metavar="PATH", help="첨부 이미지 (여러 번 지정 가능)")

    p = add("comment", c.cmd_comment, "댓글 조회 / 작성")
    p.add_argument("--article", required=True)
    p.add_argument("--add", metavar="TEXT")
    p.add_argument("--tree", action="store_true", help="--json 을 트리 형태로")
    p.add_argument("--json", action="store_true")

    p = add("reply", c.cmd_reply, "대댓글 트리 조회 / 작성")
    p.add_argument("--article", required=True)
    p.add_argument("--comment", type=int, metavar="COMMENT_ID")
    p.add_argument("--text")
    p.add_argument("--json", action="store_true")

    p = add("like", c.cmd_like, "좋아요 상태 / 등록·취소")
    p.add_argument("--article", required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--on", action="store_true")
    g.add_argument("--off", action="store_true")

    return ap


def main(argv: Sequence[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    try:
        return asyncio.run(handler(args, Settings()))
    except NotLoggedInError as e:
        print(f"로그인 필요: {e}\n  -> python -m caffeinate.cli login", file=sys.stderr)
        return 1
    except CaffeinateError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
