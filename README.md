# caffeinate

네이버 카페를 코드로 다루는 비동기 파이썬 라이브러리입니다.
게시판·글·댓글·좋아요를 읽고 쓸 수 있고, **서버가 실제 파이어폭스 브라우저와 구별하지 못하도록** 요청을 보냅니다.

- 로그인은 실제 브라우저(Camoufox, 파이어폭스 기반)로 한 번 하고, 쿠키를 저장해 재사용합니다.
- 이후 모든 요청은 그 브라우저와 같은 TLS·HTTP/2 지문, 헤더 순서, 쿠키 형식으로 보냅니다.
- 이를 위해 HTTP/2 동작을 패치한 curl_cffi 를 패키지 안에 내장했습니다.

> Python 3.11 이상 · Windows x64 / Linux x86_64 / macOS arm64

---

## 목차

1. [설치](#설치)
2. [빠른 시작](#빠른-시작)
3. [로그인](#로그인)
4. [API 한눈에 보기](#api-한눈에-보기)
5. [설정 · 예외 · 로깅](#설정--예외--로깅)
6. [동작 원리](#동작-원리)
7. [알아야 할 서버 동작](#알아야-할-서버-동작)
8. [프로젝트 구조](#프로젝트-구조)
9. [개발 · 배포](#개발--배포)
10. [주의사항](#주의사항)

---

## 설치

[Releases](https://github.com/deongdion/caffeinate/releases) 에서 내 플랫폼의 휠을 설치합니다.
(아래는 v0.4.0 기준입니다. 다른 버전은 주소의 버전 두 곳을 바꾸세요.)

```bash
# Windows x64
pip install "caffeinate @ https://github.com/deongdion/caffeinate/releases/download/v0.4.0/caffeinate-0.4.0-cp311-abi3-win_amd64.whl"
# Linux x86_64
pip install "caffeinate @ https://github.com/deongdion/caffeinate/releases/download/v0.4.0/caffeinate-0.4.0-cp311-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl"
# macOS arm64
pip install "caffeinate @ https://github.com/deongdion/caffeinate/releases/download/v0.4.0/caffeinate-0.4.0-cp311-abi3-macosx_11_0_arm64.whl"

# 로그인용 브라우저 (처음 한 번, 약 2.5GB)
python -m camoufox fetch
```

설치 확인:

```bash
python -c "import caffeinate.core.curl as c; print(c.BUNDLED)"   # True 여야 정상
```

> 위 휠이 없는 플랫폼에서 소스로 설치하면 공식 curl_cffi 로 대신 동작합니다(`pip install ".[fallback]"`).
> 기능은 같지만 HTTP/2 의 두 가지 세부 동작이 브라우저와 달라집니다. ([동작 원리](#동작-원리) 참고)

---

## 빠른 시작

```python
import asyncio
from caffeinate import Caffeinate, build_tree

async def main():
    async with Caffeinate() as cafe:
        # 카페는 숫자 ID, slug("remonterace"), 카페 URL 어느 것으로든 지정할 수 있습니다.
        for board in await cafe.boards.all("remonterace"):
            print(board.menu_id, board.name)

        # 게시판 글을 페이지 걱정 없이 하나씩
        async for a in cafe.boards.iter_articles("remonterace", 2, limit=10):
            print(a.article_id, a.subject)

        # 글 읽기 + 댓글 트리 + 좋아요
        url = "https://cafe.naver.com/f-e/cafes/30857348/articles/368535"
        article = await cafe.articles.get(url)
        comments = build_tree(await cafe.comments.all(url))
        like = await cafe.likes.status(url)
        print(article.subject, len(comments), like.like_count)

asyncio.run(main())
```

쓰기 (로그인 + 카페 멤버 필요):

```python
async with Caffeinate() as cafe:
    ref = await cafe.articles.write("내카페", 1, "제목", "본문\n둘째 줄", images=["a.png"])
    cid = await cafe.comments.add(ref, "댓글", image="b.png")
    await cafe.likes.like(ref)
    await cafe.comments.delete(ref, cid)
    await cafe.articles.delete(ref)
```

전체 예제는 [`example.py`](example.py) 에 있습니다.

```bash
python example.py                         # 읽기만 (아무것도 쓰지 않음)
python example.py --write <내 카페> <게시판번호>   # 글·좋아요·사진 댓글을 쓰고 바로 지움
python example.py --debug                 # 요청 로그 출력
```

---

## 로그인

처음 한 번 로그인하면 쿠키가 프로필 폴더에 저장되고, 이후에는 `Caffeinate()` 만으로 로그인 상태가 됩니다.

```python
import os
from caffeinate import Caffeinate, LoginOptions

# 자동 입력: 아이디/비밀번호를 사람처럼 타이핑 (자격증명은 환경변수로)
options = LoginOptions(username=os.environ["NAVER_ID"], password=os.environ["NAVER_PASSWORD"])
async with await Caffeinate.login(options=options) as cafe:
    print(await cafe.is_logged_in())

# 수동: 브라우저 창만 띄우고 사람이 직접 로그인
async with await Caffeinate.login() as cafe:
    ...
```

- **2차 인증, 기기 등록, 캡차**는 자동으로 넘기지 않습니다. 창에서 사람이 처리하면 로그인이 이어집니다.
  수동 모드로 한 번 로그인해 두면 브라우저 프로필에 기억됩니다.
- **쿠키가 만료되면** 로그인이 필요한 API 가 `NotLoggedInError` 를 냅니다. 다시 `Caffeinate.login()` 을 부르면 됩니다.
- `cafe.has_login_cookies` 는 로컬 쿠키가 있는지만, `await cafe.is_logged_in()` 은 서버에 실제로 물어봅니다.
- 주요 옵션: `headless`, `timeout`(기본 300초), `debug`(화면 상태 출력). 전체는 `LoginOptions` 참고.

**프로필 폴더** (쿠키·지문·로그인 브라우저 프로필이 저장되는 곳). 다음 순서로 정해집니다.

1. `Settings(profile_dir=...)`
2. 환경변수 `CAFFEINATE_PROFILE_DIR`
3. 소스 체크아웃이면 `caffeinate/profile/`
4. 설치형이면 사용자 데이터 폴더 (Windows `%LOCALAPPDATA%\caffeinate`, macOS `~/Library/Application Support/caffeinate`, Linux `~/.local/share/caffeinate`)

---

## API 한눈에 보기

모든 기능은 `Caffeinate` 객체의 서비스 속성으로 나뉘어 있습니다. 모든 메서드는 `async` 입니다.

- **카페 인자**(`CafeLike`): 숫자 ID, 숫자 문자열, slug, 카페 URL. slug 해석 결과는 캐시됩니다.
- **글 인자**: `ArticleRef` 또는 게시글 URL (f-e, ca-fe, `{slug}/{번호}`, `ArticleRead.nhn` 형식 모두).
- **이미지 인자**(`ImageLike`): 파일 경로, `bytes`, `(bytes, 파일명)`, 이미 올린 `UploadedImage`.

| 서비스 | 메서드 | 설명 |
|---|---|---|
| `cafes` | `my_cafes()` | 내가 가입한 카페 목록 |
| | `resolve_id(cafe)` | slug/URL → 숫자 카페 ID |
| `boards` | `all(cafe)` | 게시판 목록 (폴더·구분선 제외) |
| | `articles(cafe, menu, page=, sort_by=)` | 글 목록 한 페이지 (`ArticlePage`) |
| | `iter_articles(cafe, menu, limit=)` | 글을 페이지 넘기며 하나씩 (async for) |
| | `notices(cafe, menu)` | 공지 목록 |
| `articles` | `get(ref)` | 글 상세 (`Article`) |
| | `write(cafe, menu, title, body, images=)` | 글쓰기 → `ArticleRef` |
| | `update(ref, menu, title, body, images=)` | 글 수정 → `ArticleRef` |
| | `delete(ref)` | 글 삭제 |
| `comments` | `all(ref)` / `iter(ref)` | 댓글 전체 (평탄 목록, `build_tree()` 로 트리) |
| | `add(ref, text, image=)` | 댓글 → 댓글 ID |
| | `reply(ref, comment_id, text, image=)` | 답글 → 댓글 ID |
| | `delete(ref, comment_id)` | 댓글 삭제 |
| | `best(ref)` | 베스트 댓글 |
| `likes` | `status(ref)` | 좋아요 수 / 내가 눌렀는지 (`LikeStatus`) |
| | `like(ref)` / `unlike(ref)` | 좋아요 / 취소 → `LikeStatus` |
| | `members(ref)` / `all_members(ref)` | 좋아요 누른 사람 (로그인 필요) |
| `members` | `is_logged_in()` | 서버 기준 로그인 여부 |
| | `my_info(cafe)` | 내 닉네임·등급·활동 통계 |
| | `membership(cafe)` / `grade(cafe)` | 가입 여부 / 등급 |
| `photos` | `upload(cafe, menu, data)` / `upload_many(...)` | 글쓰기용 이미지 업로드 (보통은 `images=` 로 자동) |

**동기 코드에서** 쓰려면 `caffeinate.run()` 을 씁니다.

```python
import caffeinate
boards = caffeinate.run(lambda cafe: cafe.boards.all("remonterace"))
```

---

## 설정 · 예외 · 로깅

### 설정 (`Settings`)

```python
from caffeinate import Caffeinate, Settings
async with Caffeinate(Settings(min_request_interval=1.0, timeout=20)) as cafe:
    ...
```

| 항목 | 기본값 | 설명 |
|---|---|---|
| `min_request_interval` | `0` | 요청 시작 사이 최소 간격(초). 동시 요청에도 적용 |
| `timeout` | `15` | 요청 1회 타임아웃(초) |
| `max_retries` / `retry_backoff` | `3` / `1.5` | 429·네트워크 오류 재시도 |
| `proxy` | `None` | 프록시 (로그인 브라우저에도 같이 적용) |
| `profile_dir` | 위 규칙 | 쿠키·지문 저장 위치 |
| `comment_retry_max` / `comment_retry_delays` | `2` / `(12, 20)` | 댓글 연속 등록 제한(2001) 자동 재시도 |

`min_request_interval` 권장값: 몇 번의 조회는 `0`, 대량 조회는 `0.5 ~ 1.0`, 연속 쓰기는 `1.5` 이상.

### 예외

```
CaffeinateError                 모든 예외의 부모
├── NaverAPIError               서버 오류 (e.status, e.code, e.body)
│   ├── NotLoggedInError        로그인 필요 / 쿠키 만료
│   ├── ArticleNotFoundError    없는 글, 삭제된 글 (4003)
│   ├── CafeNotFoundError       없는 카페 (0010)
│   ├── PermissionDeniedError   멤버 전용 (4004), 비멤버 등급 조회 (40003)
│   └── RateLimitedError        댓글 연속 등록 제한 (2001), 계속되는 429
├── NetworkError                재시도 후에도 연결 실패
├── ParseError                  URL·응답 해석 실패
└── LoginError                  브라우저 로그인 실패
```

모든 예외의 `str(e)` 에 해결 방법(`e.hint`)이 붙어 있습니다.

```python
from caffeinate import ArticleNotFoundError, PermissionDeniedError

try:
    article = await cafe.articles.get(url)
except ArticleNotFoundError:
    ...                      # 삭제된 글
except PermissionDeniedError as e:
    print(e.hint)            # 가입 또는 등급 필요
```

### 로깅

기본으로는 아무것도 출력하지 않습니다. `caffeinate.enable_logging()` 을 부르면 요청 로그가 나옵니다.
쿠키 값과 비밀번호는 로그에 남기지 않습니다.

---

## 동작 원리

네이버는 요청이 사람의 브라우저에서 왔는지를 여러 층에서 볼 수 있습니다. caffeinate 는 각 층을 로그인에 쓴 Camoufox(Firefox 158)와 똑같이 맞춥니다.
모든 항목은 실제 브라우저와 바이트 단위로 비교해 확인했습니다.

| 층 | 맞추는 방법 |
|---|---|
| TLS | 로그인 브라우저의 ja3 를 그대로 사용. 세션 재개는 끔 (재개 시 지문이 달라짐) |
| HTTP/2 | 프레임 설정·우선순위 + **첫 스트림 번호 3, 요청마다 WINDOW_UPDATE** (내장 패치 curl_cffi) |
| 헤더 | 요청 종류(XHR, fetch, 문서 이동, `<script>`)별로 파이어폭스와 같은 순서·값 |
| 쿠키 | 브라우저처럼 직접 관리하고, 쿠키마다 별도 헤더로 전송 |
| Referer / Origin | 네이버의 Referrer-Policy 에 따라 계산, 리다이렉트도 브라우저 규칙대로 |
| 요청 내용 | 실제 카페 화면이 보내는 URL·쿼리 순서·폼 필드 순서·커스텀 헤더(`X-Cafe-Product`)와 동일 |

**왜 curl_cffi 를 내장했나:** 공식 curl_cffi 로는 HTTP/2 의 "첫 스트림 번호"와 "요청마다 보내는 WINDOW_UPDATE"를 바꿀 수 없습니다.
그래서 libcurl 을 패치해 옵션 두 개를 추가하고, 그 빌드를 패키지 안(`caffeinate/_curl_cffi`)에 넣었습니다.

코드 안의 `[실측 YYYY-MM-DD]` 주석이 각 동작을 확인한 날짜와 근거입니다.

---

## 알아야 할 서버 동작

코드를 고치기 전에 알아두면 좋은, 직접 측정해서 확인한 네이버 카페 서버의 특이한 동작입니다.

| 동작 | 내용 |
|---|---|
| 댓글 페이지 | 쿼리 `?page=` 는 무시됨. 경로 `/comments/pages/{n}` 으로 지정해야 함 |
| 글 목록 범위 밖 페이지 | 오류 없이 1페이지를 다시 줌 → 반복자가 이미 본 글로 멈춤 판단 |
| 좋아요 대상 ID | `{카페ID}_{카페 slug}_{글번호}`. slug 가 틀려도 오류 없이 빈 결과가 옴 |
| 좋아요 요청 | `route-like.naver.com` 으로 `<script>` JSONP 방식 |
| 좋아요 누른 사람 다음 페이지 | 페이지 번호가 아니라 `nextTimestamp` 커서 |
| 댓글 연속 등록 | 두 번째부터 2001 오류. 약 12초 뒤 다시 보내면 성공 (자동 재시도) |
| 글 정렬 | 서버가 실제로 적용하는 값은 `TIME`(최신순), `LIKE`(좋아요순) 두 가지 |
| 비회원이 보는 조회수 | `"4만"` 같은 표시 문자열로 옴 |

---

## 프로젝트 구조

```
caffeinate/
├── lib.py          Caffeinate 클라이언트 (서비스들을 묶음)
├── services/       기능별 API: cafes · boards · articles · comments · likes · members · photos
├── models/         응답 데이터 클래스 (Article, Comment, LikeStatus ...)
├── core/           요청 처리의 핵심
│   ├── session.py      HTTP 세션 (재시도, 리다이렉트, 요청 간격)
│   ├── headers.py      파이어폭스와 같은 헤더 구성
│   ├── cookies.py      쿠키 저장소
│   ├── fingerprint.py  TLS 지문
│   ├── endpoints.py    모든 네이버 API 주소
│   └── errors.py       예외와 오류 코드 매핑
├── auth/           Camoufox 브라우저 로그인
├── utils/          URL 해석, 글쓰기 본문(SmartEditor JSON) 생성 등
├── _curl_cffi/     내장 curl_cffi (HTTP/2 패치 포함)
└── profile/        쿠키·지문 저장 (git 에 올리지 않음)
example.py          사용 예제
tests/              오프라인 테스트
native/             패치한 libcurl 빌드 스크립트와 패치 파일
docs/               실측 기록, 배포 문서
```

새 기능을 추가할 때의 흐름: `core/endpoints.py` 에 주소 추가 → `services/` 에 메서드 추가 → 응답은 `models/` 의 `from_api()` 로 파싱.

---

## 개발 · 배포

```bash
pip install -e ".[fallback,dev]"
pytest              # 오프라인 테스트 (네트워크 없음, 실제 쿠키를 건드리지 않음)
ruff check .
mypy caffeinate
```

- **실서버 확인**: `python example.py` (읽기). 쓰기는 본인 카페에서 `--write` 로만 확인합니다.
- **새 버전 배포**: `caffeinate/__init__.py` 의 `__version__` 을 올려 커밋하고, 같은 이름의 태그(`v0.4.1`)를 push 하면
  GitHub Actions 가 세 플랫폼 휠을 빌드·테스트한 뒤 Release 를 만듭니다.
- **직접 빌드, curl_cffi 새 버전으로 올리기**: [`docs/배포와-업그레이드.md`](docs/배포와-업그레이드.md)

코드 규칙: 주석·docstring·오류 메시지는 한국어. 서버에서 확인한 사실은 `[실측 YYYY-MM-DD]`, 확인하지 않은 가정은 `[추정]` 으로 표시합니다.

---

## 주의사항

- **`cookies.json` 은 네이버 로그인 토큰입니다.** 공유하거나 git 에 올리지 마세요. (`profile/` 은 `.gitignore` 와 배포 패키지에서 제외되어 있습니다.)
- **짧은 시간에 많은 요청을 보내면 계정이 제재될 수 있습니다.** 대량 작업에는 `min_request_interval` 을 설정하세요.
- 네이버 화면이 바뀌면 요청 형식도 바뀔 수 있습니다. 동작이 이상하면 실제 브라우저의 요청을 캡처해 비교하세요.

---

## 변경 사항

### 0.4.0

- 카페를 slug·URL 로도 지정 (`CafeLike`), slug 해석 캐시
- 글쓰기 `images=` 에 파일 경로·bytes 를 바로 넘기면 자동 업로드
- `boards.iter_articles()`, `comments.iter()` 반복자
- 오류 코드별 예외 (`ArticleNotFoundError` 등), `Settings.min_request_interval`
- 루트 `login.py` 제거 → `Caffeinate.login()` 사용

**호환성이 깨지는 변경**

| 대상 | 0.3 | 0.4 |
|---|---|---|
| `articles.delete()`, `comments.delete()` | 응답 dict | `None` (실패면 예외) |
| `likes.like()`, `unlike()` | 응답 dict | `LikeStatus` (원본은 `like_raw()`) |
| `articles.update()` | 응답 dict | `ArticleRef` |
| 서버 오류 | 모두 `NaverAPIError` | 하위 클래스 (`except NaverAPIError` 는 그대로 동작) |

### 0.3.0

사진 댓글·답글, 좋아요 요청을 실제 화면 방식(JSONP) 그대로 재현, 좋아요 누른 사람 다음 페이지

### 0.2.0

패치한 curl_cffi 내장, 세 플랫폼 휠 배포
