# caffeinate - 네이버 카페 자동화 (curl_cffi AsyncSession 내장)

로그인은 Camoufox(파이어폭스 기반) 브라우저로 하고, 이후 요청은 그 브라우저와 같은
TLS/HTTP2 지문, 헤더 순서로 보내는 네이버 카페 비동기 파이썬 라이브러리.

## 설치

Python 3.11+. 파이어폭스 h2 패치를 넣은 curl_cffi 가 **패키지 안에 내장**(`caffeinate._curl_cffi`)되어 있어 별도
curl_cffi 설치가 필요 없다. 네이티브 확장(패치한 libcurl-impersonate 링크)이 들어 있는 **플랫폼 휠**을
[GitHub Releases](https://github.com/deongdion/caffeinate/releases) 에서 설치한다 (CPython 3.11 이상 공용 abi3):

```
# Windows x64
pip install "caffeinate @ https://github.com/deongdion/caffeinate/releases/download/v0.2.0/caffeinate-0.2.0-cp311-abi3-win_amd64.whl"
# Linux x86_64 (glibc 2.17+)
pip install "caffeinate @ https://github.com/deongdion/caffeinate/releases/download/v0.2.0/caffeinate-0.2.0-cp311-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl"
# macOS arm64 (11.0+)
pip install "caffeinate @ https://github.com/deongdion/caffeinate/releases/download/v0.2.0/caffeinate-0.2.0-cp311-abi3-macosx_11_0_arm64.whl"

python -m camoufox fetch           # Camoufox 브라우저 받기 (약 2.5GB, 대부분 글꼴) - 로그인할 때만 필요
python -c "import caffeinate.core.curl as c; print(c.BUNDLED)"   # True 면 내장 확장 사용 중
```

(정확한 파일 이름은 Releases 페이지 참고. 다시 설치할 때는 `--force-reinstall`.)

### 폴백 (소스 체크아웃 / 그 밖의 플랫폼)

소스에서 설치(`pip install -e .`, sdist, `git+https://...`)하면 네이티브 확장 없이 순수 파이썬으로 설치되고,
`caffeinate.core.curl` 이 **설치된 공식 curl_cffi 로 폴백**한다. 이때는 `fallback` extra 로 curl_cffi 를 함께 설치한다:

```
pip install -e ".[fallback,dev]"   # 개발: + curl_cffi / pytest / ruff / mypy
```

폴백에서는 h2 의 두 가지(첫 요청 스트림 ID 3, 요청마다 HEADERS 뒤 스트림 WINDOW_UPDATE)를 브라우저와 맞추지 못한다
(아래 "브라우저 동일 인식" 표). `CafeSession` 이 처음 만들어질 때 `caffeinate` 로거에 경고를 한 번 남기고 그대로 동작한다.

### 직접 빌드 (네이티브 확장 포함 휠)

`native/` 에 패치와 빌드 스크립트가 있다. upstream curl_cffi 0.16.3 ↔ libcurl-impersonate v2.2.2 (curl 8.21.0).

| 파일 | 내용 |
|---|---|
| `native/patches/curl-caffeinate.patch` | curl: `CURLOPT_HTTP2_INITIAL_STREAM_ID`(1900), `CURLOPT_HTTP2_STREAM_WINDOW_UPDATE`(1901) |
| `native/patches/*-msvc.patch` | Windows MSVC 빌드 수정 (superbuild 패치가 위 패치들을 CMake ExternalProject 패치 단계에 연결) |
| `native/build_windows.ps1` | Windows x64: curl-impersonate 빌드(MSVC+cmake+ninja+NASM) → 휠 → delvewheel 로 DLL 포함 |
| `native/build_unix.sh` | Linux/macOS: upstream CI 와 같은 방법(Linux 는 zig, glibc 2.17)으로 정적 `libcurl-impersonate.a` 생성 |
| `native/build_ffi.py` | cffi 확장 `caffeinate._curl_cffi._wrapper` 빌드 (setup.py 가 `CAFFEINATE_LIBCURL_DIR` 있을 때만 사용) |
| `native/smoke_test.py` | 설치된 휠 검사: 내장 확장 사용, 옵션 1900/1901, tls.peet.ws 에서 HEADERS(3) → WINDOW_UPDATE(3, 12451840) → DATA |

```
# Windows x64 (필요: VS 2022+ C++ 빌드 도구, cmake, ninja, Git for Windows. 디스크 약 3 GB, 약 6 분)
powershell -ExecutionPolicy Bypass -File native\build_windows.ps1 -WorkDir D:\cafbuild -CleanIntermediates
pip install --force-reinstall D:\cafbuild\dist\caffeinate-0.2.0-cp311-abi3-win_amd64.whl

# Linux / macOS (필요 도구는 스크립트 머리말 참고)
native/build_unix.sh native/out/lib
CAFFEINATE_LIBCURL_DIR=$PWD/native/out/lib pip wheel . --no-deps -w dist   # Linux 배포용은 cibuildwheel(manylinux) 사용
```

### 릴리스 (GitHub Actions `.github/workflows/wheels.yml`)

- `native/**`, `setup.py`, `pyproject.toml`, `caffeinate/_curl_cffi/**` 등을 바꿔 push 하면 휠 빌드 + 테스트가 돈다
  (Windows x64 / Linux x86_64 manylinux2014 / macOS arm64, 각 휠을 Python 3.11·3.13 에 설치해 smoke test + 오프라인 pytest).
  libcurl-impersonate 빌드 결과는 패치/스크립트 해시로 캐시된다.
- 새 릴리스: `caffeinate/__init__.py` 의 `__version__` 을 올려 커밋하고 같은 버전의 태그 `v<버전>` 을 push 한다
  (`git tag v0.2.1 && git push origin v0.2.1`). 태그와 버전이 다르면 실패한다. 성공하면 휠 + sdist 가 붙은 Release 가 만들어진다.
- 빠진 플랫폼: Linux aarch64 / macOS x86_64 / musl 은 아직 CI 에 없다 (build_unix.sh 는 aarch64 도 처리하므로 행렬만 추가하면 됨).
  그 밖의 플랫폼은 폴백.

### upstream 을 올릴 때 (curl_cffi / libcurl-impersonate 새 버전)

1. 새 curl_cffi 태그의 `curl_cffi/` 패키지로 `caffeinate/_curl_cffi/` 를 교체하고 다시 적용: `cli/`·`__main__.py` 제외,
   `requests/session.py` 의 `from curl_cffi.requests import` → `from . import`, `__version__.py` 는 버전 고정,
   `const.py` 의 `CurlOpt.HTTP2_INITIAL_STREAM_ID = 1900`, `HTTP2_STREAM_WINDOW_UPDATE = 1901`,
   `requests/impersonate.py`·`utils.py` 의 `extra_fp` 필드 2개 (`git diff` 로 이전 교체 커밋 참고).
   `ffi/*` 는 `native/ffi/` 로 복사.
2. 그 curl_cffi 가 쓰는 libcurl-impersonate 태그(curl_cffi `scripts/build.py` 의 `__version__`)로 워크플로/스크립트의
   `CURL_IMPERSONATE_TAG` 를 바꾸고, `curl-caffeinate.patch` 를 새 curl 소스(curl-impersonate `curl.patch` 적용 후)에 맞춰
   갱신한다. CURLOPT 번호 1900/1901 이 upstream 과 겹치지 않는지 확인한다. Windows 는 `*-msvc.patch` 도 확인.
3. `THIRD_PARTY_NOTICES` 의 라이선스 문구 갱신 (curl-impersonate 빌드 결과 `LICENSE*`).

### 프로필 폴더 (쿠키 = 세션 토큰 저장 위치)

쿠키/지문/로그인 브라우저 프로필은 `Settings.profile_dir` 에 저장된다. 기본 위치 결정 순서:

1. `Settings(profile_dir=...)` 직접 지정 (문자열도 됨)
2. 환경변수 `CAFFEINATE_PROFILE_DIR`
3. 소스 체크아웃(`pip install -e .` 포함)이거나 패키지 안 `caffeinate/profile/` 이 이미 있으면 그 폴더 (기존 동작)
4. site-packages 에 일반 설치된 경우 사용자 데이터 폴더
   (Windows `%LOCALAPPDATA%\caffeinate`, macOS `~/Library/Application Support/caffeinate`,
   Linux `~/.local/share/caffeinate`) - 재설치 때 지워지거나 쓰기 권한이 없는 site-packages 를 피한다

## 구조

```
caffeinate/
├── __init__.py        공개 API (Caffeinate, 모델, enum, 예외)
├── lib.py             Caffeinate 고수준 비동기 클라이언트
├── core/              config(Settings) · endpoints · errors · session(AsyncSession) · curl(내장/폴백 선택)
│                      headers(파이어폭스 헤더 순서) · cookies(CookieStore) · fingerprint(지문)
├── enums/             browser · http · cafe (MenuType, BoardType, SortBy ...)
├── models/            dataclass: Cafe, Board, Article, ArticleSummary, Comment, LikeStatus,
│                      Identifier/Membership/MyInfo, Cookie, Fingerprint
├── services/          cafes · boards · articles · comments · likes · members · photos
├── auth/              login (Camoufox 로그인 -> 쿠키 + 지문)
├── utils/             parsing(URL/JSON) · html · editor(contentJson) · multipart
├── _curl_cffi/        내장 curl_cffi 0.16.3 (+ h2 패치 옵션). 확장 _wrapper 는 플랫폼 휠에만 있음
└── profile/           cookies.json / fingerprint.json / camoufox_preset.json / login_firefox/  (공유·커밋 금지)
login.py               로그인 러너 (python login.py [--manual])
example.py             비로그인 읽기 예제
tests/                 오프라인 pytest
pyproject.toml         패키지/의존성/ruff·mypy·pytest 설정
setup.py               네이티브 확장 빌드 배선 (CAFFEINATE_LIBCURL_DIR)
native/                libcurl-impersonate 패치 · 빌드 스크립트 · cffi 소스 · 휠 smoke test
.github/workflows/     wheels.yml (플랫폼 휠 빌드/테스트/Release)
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

루트 러너로도 실행할 수 있다 (소스 체크아웃 기준. 자격증명은 NAVER_ID / NAVER_PASSWORD 환경변수, 없으면 프롬프트):

```
python login.py                         # 자동 입력 모드
python login.py --manual                # 수동 모드 (창만 띄우고 직접 로그인)
python login.py --debug                 # 폴링마다 화면 상태 덤프 (미지 화면 실측용)
python login.py --profile-dir D:/naver  # 저장 위치 지정 (기본은 위 "프로필 폴더" 규칙)
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

이후에는 `Caffeinate()` 가 저장된 쿠키와 지문을 읽는다. 쿠키가 만료되면 로그인이 필요한 API 가
`NotLoggedInError` 를 내고(메시지에 재로그인 안내 포함), `python login.py` 또는 `Caffeinate.login()` 으로 다시 로그인하면 된다.
`cafe.has_login_cookies` 는 로컬 쿠키 유무만, `await cafe.is_logged_in()` 은 서버에 물어 실제 로그인 상태를 본다.

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
        best = await cafe.comments.best(article.ref)                  # list[Comment] 베스트 댓글 (미선정이면 [])
        likers = await cafe.likes.members(article.ref)                # LikeMembers (로그인 필요, .users / .total_count)
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
        await cafe.articles.update(ref, 1, "새 제목", "새 본문", images=[img])  # 응답 원본 (dict)
        await cafe.likes.like(ref)                                    # unlike(ref) 로 취소
        info = await cafe.members.my_info(cafe_id)                     # MyInfo 닉네임/등급/활동통계 (로그인 필요)

asyncio.run(main())
```

설정은 `Settings(timeout=..., max_retries=..., proxy=..., profile_dir=...)` (키워드 전용) 로 바꿔 `Caffeinate(settings)` 에 넘긴다.
전체 예제: `python example.py` (`--debug` 로 디버그 로그)

### 동기 코드에서

```python
import caffeinate

boards = caffeinate.run(lambda cafe: cafe.boards.all(18886295))   # 열고 -> 실행 -> 닫기

async def job(cafe: caffeinate.Caffeinate) -> list[str]:
    return [a.subject for a in await cafe.boards.articles(18886295, 2)]
subjects = caffeinate.run(job)
```

Jupyter 처럼 이미 이벤트 루프가 도는 곳에서는 `run()` 대신 `async with Caffeinate() as cafe:` 로 직접 await 한다.

### 예외

```
CaffeinateError                 모든 예외의 부모 (except CaffeinateError 로 한 번에)
├── NaverAPIError               서버 응답 오류: e.status (HTTP), e.code (본문 에러코드, 예 "2001"), e.body
│   └── NotLoggedInError        비로그인/쿠키 만료 (0004, 10004, 401) -> 다시 로그인
├── NetworkError                재시도 후에도 연결/타임아웃 실패
├── ParseError (ValueError)     URL/식별자/응답 해석 실패
└── LoginError                  브라우저 로그인 실패 (자격증명 오류, 보호조치, 시간 초과 등)
```

`str(e)` 에는 해결 방법(`e.hint`)이 함께 붙는다.

### 로깅

라이브러리는 `logging.getLogger("caffeinate")` 를 쓰고 기본으로는 아무것도 출력하지 않는다(NullHandler).
`caffeinate.enable_logging()` (기본 DEBUG) 또는 앱의 `logging.basicConfig(level=logging.DEBUG)` 로 켠다.
쿠키 값/비밀번호는 로그에 남기지 않는다.

### 공개 API

`from caffeinate import ...` 로 `Caffeinate`, `Settings`, `LoginOptions`, 모든 모델(`Article`, `ArticleRef`,
`ArticlePage`, `Comment`, `LikeStatus`, `LikeMembers`, `MyInfo` ...), enum(`SortBy`, `ViewType`, `ReactionType` ...),
예외, 헬퍼(`build_tree`, `parse_cafe_url`, `html_to_text`, `run`, `enable_logging`)를 바로 가져올 수 있다.
타입 힌트가 포함된 패키지다 (`py.typed`).

## 개발

```
pip install -e ".[fallback,dev]"
pytest                 # 오프라인 단위 테스트 (네트워크 없음, 실제 프로필을 건드리지 않음)
ruff check .
mypy caffeinate
```

실서버 동작은 `python example.py` (비로그인 읽기)로 확인한다. 쓰기 기능은 실제 계정에 반영되므로 주의.

## 브라우저 동일 인식 (2026-11-13 실측, Camoufox = Firefox 158)

| 항목 | 방법 | 실측 결과 |
|---|---|---|
| TLS | curl_cffi `firefox147` + 로그인 브라우저 ja3 덮어쓰기, TLS 세션 재개 끔 | ja3 / JA4 / peetprint 동일. 재개를 켜면 재접속 ClientHello 에 확장 35 가 더 붙어 파이어폭스에 없는 JA4 가 되므로 끔 |
| HTTP2 | curl_cffi 파이어폭스 타겟 + 요청별 HEADERS weight + 내장 패치 libcurl 로 첫 스트림 ID 3, 요청마다 스트림 WINDOW_UPDATE 12451840 | akamai 지문 동일, weight 문서 42 / XHR·fetch 22. 플랫폼 휠이면 tls.peet.ws sent_frames 가 브라우저와 동일 |
| 헤더 순서/값 | `default_headers=False` + 종류별 순서 구성 | 네이버(Referrer-Policy 명시)·fetch: referer 가 accept-encoding 바로 뒤 → content-type → x-cafe-product → content-length → origin → cookie. 정책 없는 페이지·교차 사이트 강등·리다이렉트 hop 은 referer 가 origin 뒤. 카페 UI 의 댓글 작성/답글/삭제·글쓰기 캡처와 순서 동일. form 본문 공백 `%20`(axios) |
| priority | XMLHttpRequest 없음, fetch `u=4`, 문서 `u=0, i` | 카페 API 는 XMLHttpRequest(axios) |
| 쿠키 | curl jar 미사용, CookieStore 가 Set-Cookie 원본을 직접 파싱 | h2 에서 쿠키마다 별도 `cookie:` 헤더 (path 긴 것 먼저, 같으면 생성 순). Expires/Max-Age/HttpOnly 보존 |
| Referer/Origin | 네이버는 `Referrer-Policy: unsafe-url` 이라 교차 출처(apis, gw)에도 전체 URL (교차 사이트 XHR/fetch 는 출처로 강등). 게시글/댓글 XHR 은 iframe URL(`?fromNext=true`) | 리다이렉트 [실측]: sec-fetch-site 체인 누적, 교차 출처를 거치면 Origin null, 301/302 POST·303 은 GET 으로 바뀌고 content-* 제거 |
| x-cafe-product | apis.naver.com / article.cafe.naver.com XHR 전부 `pc` | 프론트 캡처와 일치 |
| 남은 차이 | 폴백(공식 curl_cffi) 시: 첫 h2 스트림 ID(브라우저 3, 우리 1), 요청 스트림 WINDOW_UPDATE 없음 | 플랫폼 휠(내장 확장)로 해결 (위 "설치"). 브라우저는 GET 포함 모든 요청에서 HEADERS 직후 보냄 [실측 2026-11-13 로컬 h2 서버] |

## 상태 메모

- 사람 세션 실측 (2026-11-13, Aside 브라우저 로그인 세션에서 카페 작업 수행 + 트래픽 캡처):
  카페 홈/메인/게시글 로드/목록/댓글 작성/좋아요 등록·취소의 실제 요청이 endpoints.py 구현과
  엔드포인트·헤더 수준에서 일치함을 확인 (CommentPost.json 현행 재확인).
  좋아요 content ID: {cafeId}_{slug}_{articleId}, slug 는 그 카페의 참 slug (소문자).
  [실측 2026-11-13 정정] 예전 메모의 "loyaltylife 네임스페이스"는 카페 30857348 의 slug 였을 뿐이다.
  틀린 slug 로 조회해도 서버는 빈 결과가 아니라 reactions=[] 콘텐츠를 돌려주므로, status() 는 반응이 비면
  게시글 상세의 cafe.url 로 재조회하고 like/unlike 는 항상 참 slug 를 쓴다.
  좋아요 등록/취소는 route-like /v1/services/CAFE/contents/{cid}?_method=POST|DELETE (JSONP) 확인.
  신규: likes.members() (gw/v5 likeIt/members, 라이브 응답으로 LikeMembers/LikeUser 모델 확정),
  comments.best() (gw/v1 best-comments, 응답 키 result.comments - 베스트 미선정 시 실제 빈 목록),
  comments.delete() (CommentDelete.json, [실측 2026-11-13: E2E 성공, 응답 {"msg": "Success"},
  삭제 댓글은 목록에서 완전 사라짐]). comments.add/reply 는 comment_id 를 반환
  (응답은 플랫 {"commentId", "refCommentId"} - 실측).
- 실측 검증 (2026-11-12): 게시판 목록, 게시글 목록, 게시글 읽기, 댓글/대댓글 조회, 좋아요 조회,
  로그인 식별자, slug -> cafeId, 내 카페 목록, 내 정보.
- 2026-11-13 재실측 정정:
  - 내 카페 목록: homepc 응답 목록은 `message.result.myCafe.cafes` (예전 코드가 경로를 잘못 읽어 항상
    GNB 폴백으로 빠졌음). GNB 폴백은 이제 순차 요청.
  - 댓글 페이지: 쿼리 `?page=` 는 무시되고 경로 `/comments/pages/{n}` 으로 지정 (`size` 쿼리는 적용).
    마지막을 넘는 번호는 마지막 페이지를 다시 준다.
  - 게시글 목록 페이지: `lastNavigationPageNumber` 는 현재 10페이지 묶음의 끝, `visibleNextButton` 은 다음
    묶음 유무. `PageInfo.has_next` 는 `page < last_page` 로 계산 (원래 값은 `has_next_block`).
    범위를 넘는 page 는 오류 없이 1페이지를 준다.
  - 비회원 요약 글의 `readCount` 는 "4만" 같은 표시 문자열 (`as_count` 로 해석).
  - 오류 코드: 없는 글 404/4003, 없는 카페 400/0010, 멤버 전용 댓글 403/4004, 비멤버 등급 500/40003,
    비로그인 likeIt/members 401/0004 (`NotLoggedInError`).
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

- 프로필 폴더의 `cookies.json` 에는 네이버 세션 토큰이 들어있다. 공유/업로드 금지 (배포 패키지에서는 제외되도록 pyproject 에 설정).
- 짧은 시간 대량 요청은 계정 제재 위험이 있다. `Settings.max_retries` / `retry_backoff` 참고.
