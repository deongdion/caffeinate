# caffeinate - 네이버 카페 자동화 (curl_cffi AsyncSession)

로그인은 Camoufox(파이어폭스 기반) 브라우저로 하고, 이후 요청은 그 브라우저와 같은
TLS/HTTP2 지문, 헤더 순서로 보내는 네이버 카페 비동기 파이썬 라이브러리.

## 설치

```
pip install curl_cffi camoufox     # Python 3.11+
python -m camoufox fetch           # Camoufox 브라우저 받기 (약 2.5GB, 대부분 글꼴)
```

## 구조

```
caffeinate/
├── __init__.py        공개 API (Caffeinate, 모델, enum, 예외)
├── lib.py             Caffeinate 고수준 비동기 클라이언트
├── core/              config(Settings) · endpoints · errors · session(AsyncSession)
│                      headers(파이어폭스 헤더 순서) · cookies(CookieStore) · fingerprint(지문)
├── enums/             browser · http · cafe (MenuType, BoardType, SortBy ...)
├── models/            dataclass: Cafe, Board, Article, ArticleSummary, Comment, LikeStatus,
│                      Identifier/Membership/MyInfo, Cookie, Fingerprint
├── services/          cafes · boards · articles · comments · likes · members · photos
├── auth/              login (Camoufox 로그인 -> 쿠키 + 지문)
├── utils/             parsing(URL/JSON) · html · editor(contentJson) · multipart
└── profile/           cookies.json / fingerprint.json / camoufox_preset.json / login_firefox/  (공유·커밋 금지)
```

## 로그인

자동 입력 모드 (아이디/비밀번호를 사람처럼 타이핑해서 직접 로그인):

```python
import asyncio
from caffeinate import Caffeinate, LoginOptions

async def main():
    options = LoginOptions(username="아이디", password="비밀번호")
    async with await Caffeinate.login(options=options) as cafe:
        print(await cafe.is_logged_in())

asyncio.run(main())
```

루트 러너로도 실행할 수 있다 (자격증명은 NAVER_ID / NAVER_PASSWORD 환경변수, 없으면 프롬프트):

```
python login.py            # 자동 입력 모드
python login.py --manual   # 수동 모드 (창만 띄우고 직접 로그인)
```

자동 입력 구현 노트 [2026-11 login.js 분석 기반]:

- 네이버 로그인 페이지는 id/pw 필드의 keydown(keyCode) 타이밍과 값 변화를 감시하고, submit 때
  행동 기반 토큰(wtoken)을 계산해 붙인다. 그래서 `page.fill()` 같은 값 설정은 쓰지 않고,
  Playwright 실제 키 이벤트(브라우저 입력 파이프라인을 거치는 trusted 이벤트)로 글자마다
  랜덤 지연(`LoginOptions.type_delay_ms`, 기본 35~150ms)을 두고 입력한다.
- 마우스 궤적은 Camoufox `humanize=True` (기본)로 움직인다.
- 행동 점수가 낮아 ncaptcha 챌린지가 뜨면:
  - headed 모드(기본): 창에서 사람이 풀 때까지 기다린다. 풀면 토큰이 나오며 로그인이 자동으로 이어진다.
  - headless 모드: LoginError (풀 수 없음).
- 자격증명 오류는 서버 오류 메시지를 읽어 LoginError 로 바로 알린다. 기기 등록/2단계 인증은
  자동 진행하지 않고 안내한다 (수동 모드로 한 번 로그인하면 영구 프로필에 기억됨).
- 대기 중에는 현재 화면을 계속 분류해 보고한다: 2차 인증(QR/SMS/앱 알림)은 안내 후 계속 대기
  (완료하면 자동 이어짐), 보호모드/이용정지/차단은 화면 내용과 함께 즉시 오류, 모르는 화면은
  URL/제목/본문 일부를 그대로 출력한다. 타임아웃 시에도 마지막 화면을 표시한다.

수동 모드:

```python
async with await Caffeinate.login() as cafe:   # 창만 띄우고 사람이 로그인
    print(await cafe.is_logged_in())
```

이후에는 `Caffeinate()` 가 저장된 쿠키와 지문을 읽는다. 쿠키가 만료되면 `Caffeinate.login()` 을 다시 호출한다.

- 로그인 브라우저: Camoufox 영구 프로필(`profile/login_firefox`) + PC별 고정 기기 프리셋(`profile/camoufox_preset.json`).
- 지문: 로그인 때 브라우저가 실제로 보낸 UA / Accept-Language 와 그 버전의 TLS(ja3)를 `fingerprint.json` 에 저장한다.
  ja3 실측표(`core/fingerprint.py FIREFOX_JA3`)에 없는 버전이면 tls.peet.ws 로 한 번 실측한다.
- 로그인 쿠키가 있는데 지문이 로그인 브라우저에서 온 것이 아니면 경고한다 (크롬 시절 쿠키 등).
- `Settings.proxy` 를 쓰면 로그인 브라우저에도 같은 프록시를 건다 (같은 출구 IP).

## 라이브러리

```python
import asyncio
from caffeinate import Caffeinate, SortBy, build_tree

async def main():
    async with Caffeinate() as cafe:
        cafe_id = await cafe.cafes.resolve_id("remonterace")
        boards = await cafe.boards.all(cafe_id)                       # list[Board]
        page = await cafe.boards.articles(cafe_id, 2, sort_by=SortBy.TIME)  # ArticlePage
        article = await cafe.articles.get("https://cafe.naver.com/f-e/cafes/30857348/articles/368535")
        comments = await cafe.comments.all(article.ref)               # list[Comment] (평탄)
        tree = build_tree(comments)                                   # replies 채움
        like = await cafe.likes.status(article.ref)                   # LikeStatus
        best = await cafe.comments.best(article.ref)                  # 베스트 댓글
        likers = await cafe.likes.members(article.ref)                # 좋아요 누른 멤버 (raw)
        # await cafe.comments.delete(article.ref, comment_id)          # 댓글 삭제
        # 게시글 URL 은 f-e/cafes/{id}/articles/{id}, {slug}/{articleId}, ArticleRead.nhn?clubid=.. 등 모두 받는다

        # 하나의 AsyncSession 으로 동시 요청
        pages = await asyncio.gather(*(cafe.boards.articles(cafe_id, b.menu_id) for b in boards))

        # 쓰기 (로그인 + 카페 멤버)
        img = await cafe.photos.upload_file(cafe_id, 1, "a.png")      # UploadedImage
        ref = await cafe.articles.write(cafe_id, 1, "제목", "본문\n둘째 줄", images=[img])  # ArticleRef
        cid = await cafe.comments.add(ref, "댓글")                    # -> commentId
        await cafe.comments.reply(ref, cid, "대댓글")
        await cafe.comments.delete(ref, cid)                          # -> {"msg": "Success"}
        await cafe.articles.update(ref, 1, "새 제목", "새 본문", images=[img])
        await cafe.likes.like(ref)                                    # unlike(ref) 로 취소
        info = await cafe.members.my_info(cafe_id)                     # 닉네임/등급/활동통계

asyncio.run(main())
```

설정은 `Settings(timeout=..., max_retries=..., proxy=..., profile_dir=...)` 로 바꿔 `Caffeinate(settings)` 에 넘긴다.
전체 예제: `python example.py`

## 브라우저 동일 인식 (2026-11-13 실측, Camoufox = Firefox 158)

| 항목 | 방법 | 실측 결과 |
|---|---|---|
| TLS | curl_cffi `firefox147` + 로그인 브라우저 ja3 덮어쓰기 | ja3 / JA4 / peetprint 동일 (덮어쓰기 없으면 158 이 뺀 암호 2개·그룹 2개 때문에 다름) |
| HTTP2 | curl_cffi 파이어폭스 타겟 | akamai 지문 동일 |
| 헤더 순서/값 | `default_headers=False` + 직접 순서 구성 | XMLHttpRequest, fetch GET/POST(JSON/폼/multipart), 문서 이동 모두 동일 |
| priority | XMLHttpRequest 없음, fetch `u=4`, 문서 `u=0, i` | 카페 API 는 XMLHttpRequest(axios) |
| 쿠키 | curl jar 미사용, CookieStore 가 파이어폭스 위치에 Cookie 헤더 | 동일 |
| Referer/Origin | strict-origin-when-cross-origin, POST·CORS 시 Origin | 파이어폭스 규칙 |

## 상태 메모

- 사람 세션 실측 (2026-11-13, Aside 브라우저 로그인 세션에서 카페 작업 수행 + 트래픽 캡처):
  카페 홈/메인/게시글 로드/목록/댓글 작성/좋아요 등록·취소의 실제 요청이 endpoints.py 구현과
  엔드포인트·헤더 수준에서 일치함을 확인 (CommentPost.json 현행 재확인).
  좋아요 content ID 네임스페이스: 사람 브라우저는 {cafeId}_loyaltylife_{articleId},
  기존 E2E 실측은 {cafeId}_{slug}_{articleId} - likes.content_ids() 로 두 후보 순회.
  좋아요 등록/취소는 route-like /v1/services/CAFE/contents/{cid}?_method=POST|DELETE (JSONP) 확인.
  신규: likes.members() (gw/v5 likeIt/members, 라이브 응답으로 LikeMembers/LikeUser 모델 확정),
  comments.best() (gw/v1 best-comments, 응답 키 result.comments - 베스트 미선정 시 실제 빈 목록),
  comments.delete() (CommentDelete.json, [실측 2026-11-13: E2E 성공, 응답 {"msg": "Success"},
  삭제 댓글은 목록에서 완전 사라짐]). comments.add/reply 는 comment_id 를 반환
  (응답은 플랫 {"commentId", "refCommentId"} - 실측).
- 실측 검증 (2026-11-12): 게시판 목록, 게시글 목록, 게시글 읽기, 댓글/대댓글 조회, 좋아요 조회,
  로그인 식별자, slug -> cafeId, 내 카페 목록(homepc, 비어 있으면 레거시 GNB 폴백), 내 정보.
- 쓰기 실측 검증 (브라우저 캡처 기반, 실제 작성 성공):
  - 글쓰기: `editor/v2.0/cafes/{id}/menus/{menu}/articles` + SmartEditor contentJson (`utils/editor.py`)
  - 이미지: 에디터 JWT -> 사진 세션키 -> `upphoto simpleUpload` (`services/photos.py`)
  - 댓글/대댓글: `cafe-mobile/CommentPost.json` / `CommentReply.json` (form-urlencoded)
- 남은 문제:
  - 없음 (2026-11-13 실측 마감). 아래는 이번 실측으로 확정된 사실.
- 쓰기 실측 확정 (2026-11-13):
  - 다중 이미지 글쓰기: articles.write 로 이미지 3장 직접 등록 성공 (본문 img src 모두 HTTP 200).
  - 빈 줄 보존: 브라우저는 줄마다 컴포넌트를 만들지 않고 text 컴포넌트 하나의 value 문단 배열에 넣으며,
    빈 줄은 textNode 값이 빈 문자열인 문단. dio 텍스트 st 는 빈 줄을 건너뛰고 "\n" 으로 잇은 바이트 길이.
  - 비로그인 쓰기: editor 스택은 500(10004 NaverUser 인증 실패) -> NotLoggedInError 매핑,
    쿠키가 아예 없으면 서버 요청 전에 로컬에서 막는다.
  - 댓글 2001("많은 댓글을 연달아 등록할 수 없어요", HTTP 403): Settings.comment_retry_max/delays 로
    자동 재시도 (기본 2회, 12초 -> 20초). 다른 에러 코드는 재시도 없음.
  - 스티커 댓글: sticker_id 는 gfmarket proxyStickerList 항목의
    "{stickerCode}-{imageWidth}-{imageHeight}" (예: motion3d_02-5-185-160), content="" 로 등록.
  - 게시글 삭제: cafe-mobile/ArticleDelete.json (form-urlencoded). 브라우저 캡처로 URL/메서드 확인,
    본문(cafeId/articleId/requestFrom=A)은 캡처되지 않아 댓글 폼 규약으로 구성 -> 서버 Success 로 검증 (192~195 삭제).
  - 카페 등급: cafemain v1.0 cafes/{id}/my?memberDataOptions=NFLEA 확정
    (memberLevel.level/levelName/config = 다음 등급 조건, memberStat = 활동 통계, 미멤버 500/40003).
  - 게시글 정렬: 서버가 실제로 적용하는 값은 TIME(최신순), LIKE(좋아요순) 두 가지.
  - 좋아요: 4013 문제 해결 (요청 timestamp 에 토큰 발급 응답의 timestamp 를 넣어야 함, 177번 글로 검증).

## 주의

- `caffeinate/profile/cookies.json` 에는 네이버 세션 토큰이 들어있다. 공유/업로드 금지.
- 짧은 시간 대량 요청은 계정 제재 위험이 있다. `Settings.max_retries` / `retry_backoff` 참고.
