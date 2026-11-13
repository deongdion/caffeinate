"""CLI 명령 구현 (모두 async, Caffeinate 클라이언트 사용)"""
import argparse
from pathlib import Path

from ..auth.login import LoginOptions, browser_login
from ..core.config import Settings
from ..core.cookies import CookieStore
from ..core.fingerprint import load_or_create
from ..core.session import CafeSession
from ..lib import Caffeinate
from ..models import Comment, Cookie, build_tree
from .output import local_time, one_line, print_json

Args = argparse.Namespace


# ---------------------------------------------------------------- 인증/지문
async def cmd_login(args: Args, settings: Settings) -> int:
    store = await browser_login(settings, LoginOptions(port=args.port or None, timeout=args.timeout))
    store.save(settings.cookies_file)
    print(f"[3] 쿠키 저장 완료: {settings.cookies_file} ({len(store)}개)")
    async with Caffeinate(settings, cookies=store) as cafe:
        ok = await cafe.is_logged_in()
    print("[4] 로그인 상태 확인:", "유효" if ok else "만료/실패 - 다시 login 해주세요")
    return 0 if ok else 1


async def cmd_status(args: Args, settings: Settings) -> int:
    store = CookieStore.load(settings.cookies_file)
    if not len(store):
        print("저장된 쿠키 없음. `python -m caffeinate.cli login` 으로 로그인하세요.")
        return 1
    async with Caffeinate(settings, cookies=store) as cafe:
        ident = await cafe.members.identifier()
    names = sorted({c.name for c in store})
    print(f"쿠키 {len(names)}종: {', '.join(names[:12])}{' ...' if len(names) > 12 else ''}")
    if ident.logged_in:
        print(f"로그인 상태: 유효 ({ident.nickname or ident.user_id})")
        return 0
    print("로그인 상태: 만료 - `python -m caffeinate.cli login` 다시 실행")
    return 1


async def cmd_set(args: Args, settings: Settings) -> int:
    store = CookieStore.load(settings.cookies_file)
    store.remove("NID_AUT")
    store.remove("NID_SES")
    store.set(Cookie(name="NID_AUT", value=args.aut, http_only=True, secure=True))
    store.set(Cookie(name="NID_SES", value=args.ses, http_only=True, secure=True))
    store.save(settings.cookies_file)
    print(f"저장 완료: {settings.cookies_file}")
    return 0


async def cmd_fingerprint(args: Args, settings: Settings) -> int:
    fp = load_or_create(settings.fingerprint_file, force_new=args.new)
    if args.new:
        print("새 지문 생성 완료")
    print(fp.describe())
    return 0


async def cmd_check_fingerprint(args: Args, settings: Settings) -> int:
    """tls.peet.ws 로 TLS/HTTP2 지문과 서버가 받은 헤더 순서 확인"""
    async with CafeSession(settings, cookies=CookieStore()) as s:
        r = await s.get_json("https://tls.peet.ws/api/all", referer="https://tls.peet.ws/")
    tls, h2 = r.get("tls", {}), r.get("http2", {})
    print(f"impersonate : {s.fingerprint.impersonate}")
    print(f"JA3         : {tls.get('ja3_hash')}")
    print(f"JA4         : {tls.get('ja4')}")
    print(f"HTTP/2      : {h2.get('akamai_fingerprint_hash')}")
    frames = [f for f in h2.get("sent_frames", []) if f.get("frame_type") == "HEADERS"]
    if frames:
        print("\n서버가 받은 헤더 (도착 순서):")
        for line in frames[0].get("headers", []):
            print("  " + one_line(str(line), 110))
    return 0


# ---------------------------------------------------------------- 카페/게시판
async def cmd_cafes(args: Args, settings: Settings) -> int:
    async with Caffeinate(settings) as cafe:
        rows = await cafe.cafes.my_cafes()
    if args.json:
        print_json(rows)
        return 0
    print(f"가입한 카페 {len(rows)}개")
    for c in rows:
        members = f"  (멤버 {c.member_count})" if c.member_count else ""
        print(f"  [{c.cafe_id}] {c.name}{members}  {c.link}")
    if not rows:
        print("  (가입한 카페가 없거나 로그인 필요 - status 명령으로 확인)")
    return 0


async def cmd_boards(args: Args, settings: Settings) -> int:
    async with Caffeinate(settings) as cafe:
        cafe_id = await cafe.cafes.resolve_id(args.cafe)
        boards = await cafe.boards.all(cafe_id, include_separators=args.all)
        page = await cafe.boards.articles(cafe_id, args.articles, page=args.page) if args.articles else None
    if args.json:
        print_json({"cafe_id": cafe_id, "boards": boards, "articles": page})
        return 0
    if not boards:
        print("게시판 목록을 가져오지 못했습니다. (카페 ID/로그인 상태 확인)")
        return 1
    print(f"카페 {cafe_id} - 게시판 {len(boards)}개")
    for b in boards:
        print(f"  [{b.menu_id}] {b.name or '(구분선)'} ({b.menu_type.name}/{b.board_type.name})")
    if page is not None:
        print(f"\n게시판 {args.articles} 글 목록 {page.page}페이지 ({len(page)}건, 마지막 {page.page_info.last_page})")
        for a in page:
            print(
                f"  [{a.article_id}] {a.subject}  - {a.writer_nick} "
                f"(조회 {a.read_count} 댓글 {a.comment_count} 좋아요 {a.like_count})"
            )
    return 0


async def cmd_myinfo(args: Args, settings: Settings) -> int:
    async with Caffeinate(settings) as cafe:
        cafe_id = await cafe.cafes.resolve_id(args.cafe)
        info = await cafe.members.my_info(cafe_id)
    if args.json:
        print_json(info)
        return 0
    print(f"카페     : {cafe_id}")
    print(f"네이버ID : {info.user_id}")
    print(f"닉네임   : {info.nickname}")
    print(f"가입여부 : {'가입' if info.is_member else '미가입'}")
    if info.grade:
        name, level = info.grade.get("levelName"), info.grade.get("level")
        text = f"{name} (레벨 {level})" if name else one_line(str(info.grade), 200)
        print(f"카페등급 : {text}")
    return 0


# ---------------------------------------------------------------- 게시글
async def cmd_article(args: Args, settings: Settings) -> int:
    async with Caffeinate(settings) as cafe:
        art = await cafe.articles.get(args.article)
    if args.json:
        print_json(art, include_raw=args.raw)
        return 0
    print(f"카페    : {art.cafe.name} ({art.cafe.cafe_id}/{art.cafe.url})")
    print(f"게시판  : {art.menu.name} ({art.menu.menu_id})")
    print(f"제목    : {('[' + art.head + '] ') if art.head else ''}{art.subject}")
    level = f" ({art.writer.level_name})" if art.writer.level_name else ""
    print(f"작성자  : {art.writer.nick}{level}")
    print(f"작성일  : {local_time(art.written_at)}")
    print(f"조회/댓글: {art.read_count} / {art.comment_count}")
    label = "요약    " if art.is_snippet else "본문    "
    print(f"{label}: {one_line(art.content_text, 200)}")
    if art.is_snippet:
        print("  (카페 멤버 공개 글 - 비회원이라 본문 대신 요약만 받음)")
    return 0


async def cmd_post(args: Args, settings: Settings) -> int:
    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else args.body
    if not body:
        print('사용법: --cafe <카페> --menu <게시판ID> --title "제목" --body "내용" [--image 파일]')
        return 2
    missing = [p for p in args.image if not Path(p).is_file()]
    if missing:
        print("이미지 파일 없음:", ", ".join(missing))
        return 2
    async with Caffeinate(settings) as cafe:
        cafe_id = await cafe.cafes.resolve_id(args.cafe)
        images = []
        for path in args.image:
            img = await cafe.photos.upload_file(cafe_id, args.menu, path)
            print(f"이미지 업로드: {img.file_name} ({img.width}x{img.height})")
            images.append(img)
        ref = await cafe.articles.write(cafe_id, args.menu, args.title, body, images=images)
    print(f"작성 완료: {ref.link}")
    return 0


# ---------------------------------------------------------------- 댓글/좋아요
def _print_tree(items: list[Comment]) -> None:
    for c in build_tree(items):
        level = f" ({c.writer.level_name})" if c.writer.level_name else ""
        print(f"  [{c.comment_id}] {c.writer.nick}{level}: {one_line(c.content)}")
        for r in c.replies:
            print(f"      ㄴ[{r.comment_id}] {r.writer.nick}: {one_line(r.content)}")


async def cmd_comment(args: Args, settings: Settings) -> int:
    async with Caffeinate(settings) as cafe:
        ref = await cafe.articles.resolve(args.article)
        if args.add:
            print_json(await cafe.comments.add(ref, args.add))
            return 0
        items = await cafe.comments.all(ref)
    if args.json:
        print_json(build_tree(items) if args.tree else items)
        return 0
    print(f"댓글 {len(items)}개")
    _print_tree(items)
    return 0


async def cmd_reply(args: Args, settings: Settings) -> int:
    async with Caffeinate(settings) as cafe:
        ref = await cafe.articles.resolve(args.article)
        if args.comment and args.text:
            print_json(await cafe.comments.reply(ref, args.comment, args.text))
            return 0
        items = await cafe.comments.all(ref)
    tree = build_tree(items)
    if args.json:
        print_json(tree)
        return 0
    _print_tree(items)
    return 0


async def cmd_like(args: Args, settings: Settings) -> int:
    async with Caffeinate(settings) as cafe:
        if args.on:
            print_json(await cafe.likes.like(args.article))
            return 0
        if args.off:
            print_json(await cafe.likes.unlike(args.article))
            return 0
        st = await cafe.likes.status(args.article)
    print(f"좋아요 {st.like_count}개 / 내가 누름: {st.liked}  (cid={st.content_id})")
    return 0
