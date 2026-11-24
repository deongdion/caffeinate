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
| `cafes` | `my_cafes()` | 내가 가입한 카페 목록 (`Cafe.is_manager`: 운영 카페 여부) |
| | `resolve_id(cafe)` | slug/URL → 숫자 카페 ID |
| | `create(options, icon=)` | 카페 만들기 → `CreatedCafe` ([카페 만들기](#카페-만들기)) |
| | `validate(field, value)` / `is_url_available(url)` | 이름·주소·소개·키워드 서버 검증 |
| | `random_url()` / `sub_directories(theme)` / `creation_info()` | 무작위 주소, 주제 소분류, 개설 화면 정보 |
| | `upload_icon(image)` | 카페 아이콘 업로드 (보통은 `create(icon=)` 로 자동) |
| | `regions(parent=, overseas=)` | 카페 지역 목록 (`Region.code` → `region_code`) |
| | `manage_info(cafe)` | 내가 운영하는 카페의 설정 (공개 유형, 실명 가입, 주제, 지역, 키워드) |
| `boards` | `all(cafe)` | 게시판 목록 (폴더·구분선 제외) |
| | `articles(cafe, menu, page=, sort_by=)` | 글 목록 한 페이지 (`ArticlePage`) |
| | `iter_articles(cafe, menu, limit=)` | 글을 페이지 넘기며 하나씩 (async for) |
| | `notices(cafe, menu)` | 공지 목록 |
| `articles` | `get(ref)` | 글 상세 (`Article`) |
| | `write(cafe, menu, title, body, images=)` | 글쓰기 → `ArticleRef` (body 는 문자열 또는 [블록](#글-블록)) |
| | `update(ref, menu, title, body, images=)` | 글 수정 → `ArticleRef` |
| | `delete(ref)` | 글 삭제 |
| `comments` | `all(ref)` / `iter(ref)` | 댓글 전체 (평탄 목록, `build_tree()` 로 트리) |
| | `add(ref, body, image=, sticker_id=)` | 댓글 → 댓글 ID (body 는 문자열 / [블록](#댓글-블록) / `CommentDraft`) |
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
| `editor` | `sticker_packs(cafe, menu)` / `stickers(cafe, menu, pack)` | 스티커 묶음 (`StickerPack`) / 스티커 (`Sticker`) |
| | `all_stickers(cafe, menu)` | 모든 묶음의 스티커 `{packCode: [Sticker]}` |
| | `link_card(cafe, menu, url)` | 링크 미리보기 블록 (`LinkCard`, 서버 서명 포함) |
| | `embed(cafe, menu, url)` | 외부 임베드 블록 (`Embed`, YouTube 등 oembed) |
| | `places(cafe, menu, query)` | 장소 검색 -> `Place` 목록 (`Map` 재료) |
| | `materials(cafe, menu, query, kinds=)` | 글감 검색 -> `Material` 목록 (책·영화·방송·음악·쇼핑·뉴스·공연전시·스포츠·부동산) |
| | `upload_file` / `upload_video` / `upload_vote_image` | 파일·동영상·투표 사진 업로드 (보통은 작성 때 자동) |
| | `render_formulas(cafe, menu, formulas)` | 수식 html·이미지 만들기 (headless Camoufox, 작성 때 자동, 같은 수식은 캐시) |

### 글 블록

`articles.write/update` 의 body 에 문자열 대신 블록 목록이나 `Document` 를 넣는다. 블록은 전부 dataclass 이고
`to_dict()` / `Block.from_dict()` / `Document.from_json()` 으로 SmartEditor contentJson 과 오간다.

```python
from caffeinate import (Align, Cell, Code, CodeLayout, Divider, Document, Heading, Image, ImageGroup, LineLayout,
                        Paragraph, QuotationLayout, Quote, RawBlock, Span, Table, Text)

packs = await cafe.editor.sticker_packs(cid, 1)           # StickerPack 16개 (cafe_001, cafe20_002, ...)
sticker = (await cafe.editor.stickers(cid, 1, packs[0]))[0]
card = await cafe.editor.link_card(cid, 1, "https://www.naver.com")
doc = Document([
    Heading("소제목"),
    Text(["첫 문단", [Span("굵게", bold=True), " ", Span("빨강", color="#ff0000"), " ", Span("링크", link="https://naver.com")],
          Paragraph([Span("가운데")], Align.CENTER)]),
    Image("a.png", caption="사진 설명"),  # 올리지 않은 사진은 자동 업로드 (첫 사진이 대표)
    "사진 사이 글",                       # 문자열 = Text
    Quote("인용", source="출처", layout=QuotationLayout.BUBBLE),
    Divider(LineLayout.LINE3),
    Table([["이름", "값"], [Cell("합친 칸", col_span=2, background="#eeeeee")]]),
    Code("print('hi')", CodeLayout.BLACK),
    ImageGroup(["b.png", "c.png"]),
    sticker, card,
])
await cafe.articles.write(cid, 1, "제목", doc)
await cafe.comments.add(ref, "", sticker_id=sticker)   # 댓글 스티커
```

| 블록 | contentJson | 기본값 | 실측 (2026-11-24) |
|---|---|---|---|
| `Text(content)` | `text` | 줄마다 문단 | ✅ |
| `Span(text, bold=, italic=, underline=, strike=, color=, background=, size=, font=, link=)` | `textNode` + `nodeStyle` | 서식 없음 | ✅ 전부 렌더, 서체 10종 |
| `Paragraph(spans, align, line_height)` | `paragraph` | 정렬·줄 간격 없음 | ✅ 양끝 정렬, 줄 간격 |
| `ParagraphDefaults(style=, align=, line_height=)` | (직렬화 때 채움) | | ✅ 문서·블록 전체 기본 서식 |
| `Heading(content)` | `sectionTitle` | | ✅ |
| `Quote(content, source=, layout=)` | `quotation` | `DEFAULT` | ✅ 6가지 모양 |
| `Divider(layout)` | `horizontalLine` | `DEFAULT` | ✅ 8가지 모양 |
| `Code(code, layout, font_size)` | `code` (`codeContents`) | `DEFAULT` | ✅ 3가지 모양 |
| `Table(rows, width=100)` / `Cell(...)` | `table` / `tableRow` / `tableCell` | 칸 너비 = 100 / 칸 수 | ✅ (표 `width` 없으면 500) |
| `Image(source, represent=, link=, caption=)` | `image` | 첫 사진이 대표 | ✅ 글 사이사이 여러 장, 캡션 |
| `ImageGroup(items, layout)` | `imageGroup` | `SLIDE` | ✅ (`COLLAGE` 는 뷰어 JS 가 그림) |
| `ImageStrip(items)` | `imageStrip` | | ✅ |
| `Sticker(pack_code, seq, w, h)` | `sticker` / 댓글 `stickerId` | 185×160, 움직임 = `STICKER_PACKS` | ✅ 글·댓글, 움직이는/정지 묶음 |
| `LinkCard(url, ..., layout=)` | `oglink` | `LARGE_IMAGE` | ✅ 4가지 모양 (서명 없어도 저장) |
| `RawBlock(dict)` | 아무 컴포넌트 | id 자동 | ✅ |

- **완전 커스텀**: 모든 블록에 `extra={...}` 를 주면 기본값을 덮어쓰거나 키를 더한다. `from_dict` 는 모르는 키를
  `extra` 에, 모르는 `@ctype` 은 `RawBlock` 에 담아서 `to_dict()` 가 받은 그대로 돌려준다. layout 은 enum 밖 문자열도 받는다.

#### 서식 (웹 에디터와 같은 범위)

카페 에디터 글자 툴바의 서식을 전부 코드로 줄 수 있다 [실측 2026-11-24: 툴바 목록 확인 → 저장 → 보기 화면 계산 스타일 확인].

```python
from caffeinate import Align, FontFamily, FontSize, ParagraphDefaults, TextStyle

doc = Document([
    Heading("소제목"),
    Text([[Span("명조", font=FontFamily.NANUM_MYEONGJO), " 보통"],
          Paragraph([Span("가운데 빨강 굵게", color="#e03131", bold=True)], Align.CENTER, line_height=2.1)],
         defaults=ParagraphDefaults(style=TextStyle(size=FontSize.FS19), line_height=1.8)),   # 이 블록 전체
    Quote("인용", source="출처"),
], defaults=ParagraphDefaults(style=TextStyle(font=FontFamily.MARUBURI, color="#1971c2"),
                              align=Align.JUSTIFY, line_height=1.6))                          # 글 전체
```

- 글자: 굵게·기울임·밑줄·취소선, 글자색·배경색 (`#rrggbb`/`rgb()` 아무 색), 크기 10단계 (`FontSize` 11~38),
  서체 10종 (`FontFamily`: 기본서체·나눔고딕·나눔명조·나눔바른고딕·나눔스퀘어·나눔스퀘어 네오·마루부리·다시시작해·바른히피·우리딸손글씨), 링크.
- 문단: 정렬 4가지 (`Align` 왼쪽·가운데·오른쪽·양끝), 줄 간격 (`1.6` = 160%. 에디터 메뉴는 1.5~2.1, 서버는 아무 양수나 `line-height` 로 넣는다).
- 전체 기본 서식: `ParagraphDefaults` 를 `Document(defaults=)` (글 전체 본문·소제목·인용구) 나 `Text`/`Heading`/`Quote(defaults=)` (그 블록) 에 준다.
  우선순위는 글자·문단에 직접 준 값 > 블록 기본 > 글 기본. 직렬화 때만 채우고 객체는 바꾸지 않는다.
- spec 에서는 글자 `font`, 문단 `line_height`, 블록·문서 `defaults` (`{"font", "size", "color", ..., "align", "line_height"}`).
- 서버 [실측]: 목록 밖 서체(`bogusfont`)도 저장되지만 CSS 가 없어 기본 서체로 보인다 (그래서 로컬에서 막는다. 꼭 필요하면 `extra`).
  에디터 툴바의 "문단 서식" 메뉴는 본문/인용구 전환뿐이라 `Quote` 로 된다.

#### 파일 · 동영상 · 지도 · 수식 · 글감 · 임베드 · 투표 · 일정

카페 글쓰기 툴바의 나머지 버튼도 전부 블록이 있다. headless Camoufox 로 실제 에디터를 조작해 만든 컴포넌트와
요청을 캡처하고, Python 으로 만든 블록을 저장해 글 보기 화면에서 그려지는 것까지 확인했다 (2026-11-24).

```python
from datetime import datetime
from caffeinate import File, Formula, Map, Schedule, Video, Vote, VoteItem, VoteResultView

places = await cafe.editor.places(cid, 1, "서울역")
doc = Document([
    File("보고서.pdf"),                                       # 작성 때 업로드 (50MB 까지)
    Video("clip.mp4", title="제목", description="설명"),       # 작성 때 업로드 + 인코딩 대기
    Map(places[:2]),                                           # 지도 이미지 주소는 에디터와 같게 만든다
    Formula(r"\frac{-b \pm \sqrt{b^2-4ac}}{2a}"),             # 작성 때 네이버 수식 편집기로 렌더
    Vote("점심", ["김밥", VoteItem("라면", image="ramen.png")], multiple=2, secret=False,
         result_view=VoteResultView.ALWAYS, close_voters=10),  # 저장하면 서버가 투표를 만든다
    Schedule("정기 모임", datetime(2026, 12, 1, 19), place=places[0]),   # 서버가 카페 일정을 만든다
    await cafe.editor.embed(cid, 1, "https://www.youtube.com/watch?v=..."),
    (await cafe.editor.materials(cid, 1, "해리포터", ["book"]))[0],
])
await cafe.articles.write(cid, 1, "제목", doc)
```

| 블록 | contentJson | 실측 (2026-11-24) |
|---|---|---|
| `File(source)` / `UploadedFile` | `file` | ✅ upapi `editor/files` 업로드 → `se-file` |
| `Video(source, title=, description=, tags=)` / `UploadedVideo` | `video` | ✅ 토큰 → nexus 세션 → 5MB 조각 업로드 → 인코딩 대기 → 대표 장면. 9MB(조각 2개) 확인. 표시 크기는 문서 폭 800 으로 줄이고 재생 시간은 내림 (에디터와 같음) |
| `Map(places)` / `Place` | `placesMap` | ✅ 1곳·여러 곳 지도 이미지 주소가 에디터와 같음 |
| `Formula(latex, font_size=)` | `formula` | ✅ 글자 크기 11~38 (편집기에서 골라 렌더, 24 → 53×80 에디터와 같음). 수식 3개 렌더 41.3s → 13.2s (고정 기기 프리셋 + 영구 프로필 `editor_firefox` 의 번들 캐시 + 미리보기 대기). 보기 화면은 `html`(mathquill 마크업)을 그린다. `<img>` 는 글자로 나오고 MathML·`<script>` 는 저장 거부(20103)라 직접 만들지 않고 실제 수식 편집기를 돌린다. html·thumbnail 둘 다 필수 |
| `Material` (`cafe.editor.materials`) | `material` | ✅ 9종 저장·렌더. 에디터 컨버터(날짜·쉼표·부동산 정규화·뉴스 상세 재조회·썸네일 크기 측정)를 그대로 옮김 |
| `Embed` (`cafe.editor.embed`) | `oembed` | ✅ `/oglink` 의 oembed + oembedSign. 보기 화면에서 YouTube 플레이어 로드 확인 |
| `Vote(title, items, ...)` / `VoteItem` | `custom` / `vote` | ✅ 저장 시 서버가 voteId·itemId 발급. 여러 개 선택·인원 종료·결과 공개·정렬·항목 사진 확인 |
| `Schedule(title, start, end=, ...)` | `custom` / `schedule` | ✅ `uuid` 가 있어야 서버가 일정을 만든다 (자동). 하루 종일이면 서버가 시간대를 비우고 하루 경계로 맞춘다 (에디터도 같음) |

- 작성 때 `cafe.editor.prepare()` 가 업로드·렌더링·`cafeId`/작성자 채우기를 하고 블록 객체를 결과로 바꾼다 (다시 넘기면 재업로드 안 함).
- 카페에서 안 되는 것 [실측]: **오디오** (`audio-uploader/session-key` 가 406 `Audio Infra ServiceId Config fail : serviceId = cafe`).
  **MYBOX** 사진·파일·동영상은 지원하지 않는다.
- 서버 검증에 안 맞는 투표·일정 데이터나 모르는 `subtype` 은 `RawBlock` 으로 그대로 보존한다.
- **로컬에서 막는 것** (`ValueError`/`TypeError`): 빈 문서, 업로드 안 된 `Image` 의 `to_dict()`, 형식이 틀린 색(`#rrggbb`·`rgb()`),
  목록 밖 글자 크기, http(s) 가 아닌 링크, 빈 표, 1 미만 `col_span`, 사진 1장짜리 묶음, 잘못된 스티커.
- **서버 동작** [실측]: 모르는 `@ctype`·id 없는 컴포넌트·외부 주소 사진 → 500 (99999), 없는 스티커 → 500 (31021),
  layout 은 검사 안 함, 틀린 글자 크기·색은 조용히 버림, `javascript:` 링크는 비움, 텍스트 HTML 은 이스케이프.

### 스키마 · AI 채우기

블록은 사람·AI 가 쓰기 쉬운 단순 JSON(spec)과 JSON Schema 로도 오간다. (`to_dict` 는 서버용 무손실 형식)

```python
# 1) 템플릿 채우기: 구조(블록 종류·순서·모양·사진·스티커)는 고정, 내용 칸만 AI 가 채운다
tpl = Document([Heading("", hint="글 제목"), Text("", hint="세 문단 본문"), Image("a.png", hint="사진 설명"),
                Table([["", ""], ["", ""]], hint="장단점 표"), sticker])
schema = tpl.fill_schema()        # {"0_heading": {"content"}, "1_text": {...}, "2_image": {"caption"}, "3_table": {"rows"}}
ai_json = ...                     # 이 스키마로 AI(structured output)에 요청한 결과
doc = tpl.fill(ai_json)           # 같은 id·모양·사진·스티커에 내용만 채운 새 Document (원본 그대로)
await cafe.articles.write(cid, 1, "제목", doc)

# 2) 자유 작성: AI 가 블록 목록을 통째로 만든다
schema = Document.json_schema()   # {"blocks": [{"type": "text" | "heading" | "quote" | "table" | ...}]}
doc = Document.from_spec(ai_json)
doc.to_spec()                     # 반대 방향 (예시로 AI 에 보여줄 때)

# 댓글
CommentDraft.json_schema()        # {"text", "sticker"?}
draft = CommentDraft.from_spec(ai_json, image="a.png")
```

- `hint` 는 스키마의 `description` 으로만 들어가고 contentJson 에는 나가지 않는다.
- 채울 칸: 글·소제목·인용(출처)·코드·표(줄·칸 수 고정)·hint 가 있는 사진의 캡션. 나머지 블록은 스키마에서 빠지고 그대로 남는다.
- `fill_schema(rich=True)` 면 글 칸에 서식 있는 문단 배열도 받는다 (기본은 문자열, 줄바꿈 = 문단).
- 모든 칸 필수·추가 키 금지 스키마라 structured output 에 그대로 쓸 수 있다. `fill(strict=False)` 는 일부만 채워도 된다.
- AI 출력이 틀리면 (모르는 type, 빠진 칸, 표 크기 불일치, 틀린 색·링크 등) 전부 `SpecError` (`ValueError`·`TypeError` 겸용).
- 투표·일정·수식은 빈 칸(`Vote("", ["", ""])`, `Schedule("", start)`, `Formula("", hint=...)`)으로 템플릿을 만들 수 있다.
  빈 제목·항목·수식은 보낼 때(`to_dict`)·렌더할 때 `ValueError`.
- 스티커는 로그인 없이 `Sticker("cafe_001", 3)` 으로 만들어도 된다. 카페 기본 16묶음의 움직임 여부·개수(`STICKER_PACKS`,
  모두 185×160)를 실측해 넣어 두었다. 움직이는 묶음을 정지(png)로 보내면 저장은 되지만 보기 화면에 "존재하지 않는 스티커" 로 나온다 [실측].
  범위 밖 번호는 미리 `ValueError`. 스키마 설명에도 묶음별 번호 범위가 들어간다.
- 스키마는 `"$schema": draft 2020-12` 를 선언한다. 이 선언을 모르는 검사기(claude CLI `--json-schema` 등)에는 그 키만 빼고 보낸다.
- [실측 2026-11-24] 템플릿 → 채우기 → 글 수정 저장, spec 댓글(글 + 스티커) 등록 확인.

#### `test.py` - 로그인 없이 템플릿 → AI 채우기 → JSON 저장

```bash
python test.py                  # AI = claude CLI (claude -p --json-schema, 기본 sonnet)
python test.py --model haiku
python test.py --dummy          # AI 없이 스키마에서 만든 가짜 값으로 흐름만
```

게시글 템플릿(소제목·본문·인용구·구분선·표·투표·일정·코드·스티커 + 글/블록 기본 서식)과 댓글 스키마를 AI 로 채우고
`test_out/` 에 저장한다 (템플릿 spec, fill 스키마, AI 응답, 채운 spec, 채운 contentJson, 댓글 폼).
스키마 적합, 구조·id·서식 유지, 원본 불변, 저장한 JSON 재로드 왕복 동일을 검사한다.
[실측 2026-11-24] 저장한 `article_filled.content.json`·`comment_filled.json` 을 그대로 읽어 글 수정·댓글 등록 → 보기 화면에서 전 블록·스티커 렌더 확인.

### 댓글 블록

댓글도 글과 같은 블록으로 쓴다. 댓글 폼이 받는 것은 글 + 스티커 1개 + 사진 1장이라 `Text`·문자열·`Sticker`·`Image`
만 받는다. 스티커 목록은 글과 같은 `cafe.editor.sticker_packs()` / `stickers()` 를 쓴다 (댓글에서도 실측 확인).

```python
sticker = (await cafe.editor.stickers(cid, 1, "cafe_001"))[0]
cid_ = await cafe.comments.add(ref, [Text("첫 줄\n둘째 줄"), sticker, Image("a.png")])
await cafe.comments.reply(ref, cid_, CommentDraft("답글", sticker=sticker))
await cafe.comments.add(ref, sticker_id=sticker)           # 스티커만
draft = CommentDraft.from_dict(form); draft.to_dict()      # 폼 필드와 왕복, extra 로 필드 추가
```

| 상황 | 서버 [실측 2026-11-24] | 라이브러리 |
|---|---|---|
| 여러 줄·빈 줄 | 그대로 저장 | 그대로 |
| 글 + 스티커 + 사진 | 함께 저장 | 그대로 |
| 빈 댓글 | 403 (9999 내용이 없는 댓글) | `ValueError` |
| 6000바이트 초과 (CP949: 한글 2, 영문·이모지 1) | 400 (9999 댓글 길이 초과) | `ValueError` (`COMMENT_MAX_BYTES`) |
| 서식·링크 `Span`, 캡션 있는 사진 | 서식 필드 없음 | `ValueError` |
| 스티커 2개, 사진 2장 | 필드가 하나뿐 | `ValueError` |
| 다른 블록 (`Heading`, `Table` ...) | — | `TypeError` |

### 카페 만들기

```python
from caffeinate import CafeCreateOptions, CafeOpenType, ThemeDirectory

opts = CafeCreateOptions(
    name="온울", url="onoulapp",                       # url 을 빼면 서버가 무작위 주소를 준다
    theme=ThemeDirectory.TRAVEL, sub_theme=192,         # sub_theme 을 빼면 대분류의 첫 소분류
    introduction="패키지, 항공권, 숙소 B2B서비스",
    keywords=["패키지", "항공권", "숙소"],
)
created = await cafe.cafes.create(opts, icon="icon.png")
print(created.link, created.cafe_id)
# 간단히: await cafe.cafes.create(name="온울")
```

| 옵션 | 기본값 | 서버 값 | 근거 |
|---|---|---|---|
| `name` | (필수) | `clubName` | 60바이트 이하 (한글 2바이트) |
| `url` | `None` → 무작위 주소 | `clubUrl` | 영문 소문자+숫자, 20바이트 이하, `-` `_` 불가 [실측] |
| `theme` | `ThemeDirectory.LIFE` (생활) | `currentThemeDir` | |
| `sub_theme` | `None` → 첫 소분류 | `currentThemeDir2` | `sub_directories(theme)` |
| `introduction` | `None` → 카페 이름 | `introduction` | 100바이트 이하 |
| `keywords` | `()` | `keywords` | 최대 10개, 각 20바이트 |
| `open_type` | `CafeOpenType.OPEN` | `openType` | `O` 공개+바로가입 / `C` 승인 가입 / `H` 비공개 [실측] |
| `use_real_name` | `False` | `useName` `N` | 바로가입(`OPEN`)에선 불가 |
| `open_member_list` | `False` | `openMemberList` | 화면 기본값 |
| `region_code` | `None` (생략) | `rcode` | 공개 카페만. `regions()` 의 코드 (`"06290"` 대구 달서구) [실측] |
| `agree_to_privacy_policy` | `True` | `agreeToPrivacyPolicy` | |
| — | 개설 화면 값 | `agreeToTerms`, `clubTempId`, `alimCode`, `groupId=999` | 프론트와 같게 자동 |

- 비공개(`HIDDEN`) 카페는 서버가 주제·소개를 저장하지 않는다 [실측].
- 만든 결과는 `manage_info(created.cafe_id)` 로 확인할 수 있다.
- 흐름: 화면 정보 → (주소 생성) → 입력 검증 → 소분류 → 아이콘 → 음성 캡차 → 생성 → 카페 ID 조회.
  검증에서 걸리면 캡차 전에 `CafeValidationError(field, result)` 로 멈춘다.
- 캡차는 기본으로 음성 캡차를 OCR 서버(`Settings.sound_captcha_ocr_url`)로 푼다. 틀리면 서버가 준 새 키로
  `Settings.captcha_max_attempts`(5)번까지, 그래도 안 되면 `CaptchaError`. 직접 풀려면 `captcha_solver=` 에
  `async (session, CaptchaChallenge) -> str` 함수를 넘긴다. 이미지 캡차는 OCR 서버가 읽지 못해서
  (`ImageCaptchaOcr` 실측 실패) 사람이 푸는 함수에 `captcha_type = CaptchaType.IMAGE` 를 붙여 쓴다.

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
| 카페 주소 검증 | 짧은 주소(`o`, `oi`)도 `DUPLICATED`, `-` `_` 는 `INVALIDCHARACTER` |
| 카페 만들기 캡차 | 오답이면 `INVALIDCHARACTER` + 새 `csKey`. 통과한 키·답을 `create-cafes` 에 그대로 다시 보냄 |
| 카페 만들기 검증 길이 | 서버 검증은 길이를 보지 않음 (긴 이름도 `CLEAR`) → 로컬에서 바이트 검사 |
| homepc 내 카페 | `manageCafe`(내가 만든 카페 true), `openType`(O/C/H) 이 옴 → `Cafe.is_manager`, `Cafe.open_type` |

---

## 프로젝트 구조

```
caffeinate/
├── lib.py          Caffeinate 클라이언트 (서비스들을 묶음)
├── services/       기능별 API: cafes · boards · articles · comments · likes · members · photos · editor
├── models/         데이터 클래스 (Article, Comment ... / 글 블록 blocks·media / spec)
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
- **AI 채우기 확인** (로그인 불필요): `python test.py` (`--dummy` 는 AI 없이).
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

### 미배포

- `test.py` (로그인 없이 템플릿 → AI 채우기 → JSON 저장), 빈 칸 투표·일정·수식 템플릿, `STICKER_PACKS` (로그인 없이 맞는 스티커)
- 카페 만들기 `cafes.create()` (아이콘 업로드, 음성 캡차 OCR 자동 풀이, 입력 검증)
- `Cafe.is_manager` (homepc `manageCafe`)
- 글 블록: `Document`, `Text`, `Span`, `Heading`, `Quote`, `Divider`, `Code`, `Table`, `Image`, `ImageGroup`, `ImageStrip`, `Sticker`, `LinkCard`, `RawBlock` (to_dict/from_dict)
- 서식: `Span(font=)`/`TextStyle.font` (`FontFamily` 10종), `Paragraph(line_height=)`, `ParagraphDefaults` (글·블록 전체 기본 서식)
- 글 블록 추가: `File`, `Video`, `Map`/`Place`, `Formula`, `Material`, `Embed`, `Vote`/`VoteItem`, `Schedule` (spec·스키마·채우기 포함)
- `cafe.editor`: `places`, `materials`, `embed`, `upload_file`, `upload_video`, `upload_vote_image`, `render_formulas`, `prepare`
- `cafe.editor` (`StickerPack`, 스티커, 링크 미리보기), `Comment.sticker`
- 댓글 블록: `comments.add/reply` 가 블록 목록·`CommentDraft` 를 받음 (글 + 스티커 + 사진, 6000바이트 검사)
- spec·JSON Schema: `Document.to_spec/from_spec/json_schema/fill_schema/fill`, 블록 `hint`, `CommentDraft.json_schema`, `SpecError`
- `RequestKind.IFRAME` / `RequestKind.AUDIO` 헤더 (iframe 폼 제출, `<audio>` 미디어 요청)

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
