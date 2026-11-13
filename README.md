# caffeinate - 네이버 카페 자동화 (curl_cffi AsyncSession)

실제 크롬과 같은 TLS/HTTP2 지문, 헤더 순서로 네이버 카페를 다루는 비동기 파이썬 라이브러리.

## 설치

```
pip install curl_cffi        # Python 3.11+
```

## 구조

```
caffeinate/
├── __init__.py        공개 API (Caffeinate, 모델, enum, 예외)
├── lib.py             Caffeinate 고수준 비동기 클라이언트
├── core/              config(Settings) · endpoints · errors · session(AsyncSession)
│                      headers(크롬 헤더 순서) · cookies(CookieStore) · fingerprint(PC 지문)
├── enums/             browser · http · cafe (MenuType, BoardType, SortBy ...)
├── models/            dataclass: Cafe, Board, Article, ArticleSummary, Comment, LikeStatus,
│                      Identifier/Membership/MyInfo, Cookie, Fingerprint
├── services/          cafes · boards · articles · comments · likes · members · photos
├── auth/              browser(크롬 실행) · cdp(curl_cffi WebSocket) · login(쿠키 수집)
├── utils/             parsing(URL/JSON) · html · editor(contentJson) · multipart
└── profile/           PC별 fingerprint.json / cookies.json  (공유·커밋 금지)
```

## 로그인

```python
import asyncio
from caffeinate import Caffeinate

async def main():
    # 전용 크롬 프로필로 로그인 창을 띄우고 쿠키를 profile/cookies.json 에 저장
    async with await Caffeinate.login() as cafe:
        print(await cafe.is_logged_in())

asyncio.run(main())
```

이후에는 `Caffeinate()` 가 저장된 쿠키를 읽는다. 쿠키가 만료되면 `Caffeinate.login()` 을 다시 호출한다.

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
        # 게시글 URL 은 f-e/cafes/{id}/articles/{id}, {slug}/{articleId}, ArticleRead.nhn?clubid=.. 등 모두 받는다

        # 하나의 AsyncSession 으로 동시 요청
        pages = await asyncio.gather(*(cafe.boards.articles(cafe_id, b.menu_id) for b in boards))

        # 쓰기 (로그인 + 카페 멤버)
        img = await cafe.photos.upload_file(cafe_id, 1, "a.png")      # UploadedImage
        ref = await cafe.articles.write(cafe_id, 1, "제목", "본문\n둘째 줄", images=[img])  # ArticleRef
        await cafe.comments.add(ref, "댓글")                          # -> commentId
        await cafe.comments.reply(ref, 136299567, "대댓글")
        await cafe.articles.update(ref, 1, "새 제목", "새 본문", images=[img])
        await cafe.likes.like(ref)                                    # unlike(ref) 로 취소
        info = await cafe.members.my_info(cafe_id)                     # 닉네임/등급/활동통계

asyncio.run(main())
```

설정은 `Settings(timeout=..., max_retries=..., proxy=..., profile_dir=...)` 로 바꿔 `Caffeinate(settings)` 에 넘긴다.
전체 예제: `python example.py`

## 브라우저 동일 인식 (2026-11-12 실측)

| 항목 | 방법 | 실측 결과 |
|---|---|---|
| TLS / HTTP2 | curl_cffi impersonate (PC별 고정 타겟) | AKAMAI h2 해시 실제 크롬과 동일 |
| sec-ch-ua | Chromium GREASE 알고리즘을 메이저 버전으로 재현 | 크롬 131/133/157 실값과 일치 |
| 헤더 순서 | `default_headers=False` + 직접 순서 구성 | XHR GET/POST, 문서 이동 모두 크롬 157과 동일 |
| 쿠키 | curl jar 미사용, CookieStore 가 크롬 위치에 Cookie 헤더 | 중복 전송 제거 |
| Referer/Origin | strict-origin-when-cross-origin, CORS 시 Origin | 크롬 규칙 |

## 상태 메모

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
