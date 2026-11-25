"""로그인 없이: 게시글·댓글 블록 구성 -> AI 로 채움 -> JSON 저장 -> 다시 읽어 확인

    python test.py                 # AI = claude CLI (claude -p --json-schema)
    python test.py --model haiku   # 모델 바꾸기
    python test.py --dummy         # AI 없이 스키마에서 만든 가짜 값으로 흐름만 확인

결과는 test_out/ 에 저장된다.
  article_template.spec.json   템플릿 (구조 + hint)
  article_fill_schema.json     AI 에 준 JSON Schema
  article_ai.json              AI 가 돌려준 JSON
  article_filled.spec.json     채운 문서 (spec - 사람·AI 용)
  article_filled.content.json  채운 문서 (contentJson - 서버에 보내는 그대로)
  comment_*.json               댓글 같은 순서
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jsonschema

from caffeinate import (
    Align,
    Code,
    CodeLayout,
    CommentDraft,
    Divider,
    Document,
    FontFamily,
    Heading,
    LineLayout,
    ParagraphDefaults,
    QuotationLayout,
    Quote,
    Schedule,
    Sticker,
    Table,
    Text,
    TextStyle,
    Vote,
)
from caffeinate.models.spec import fill_keys

KST = timezone(timedelta(hours=9))
OUT = Path(__file__).with_name("test_out")
STICKERS = ["cafe_001-1-185-160", "cafe_001-2-185-160", "cafe_001-3-185-160"]   # AI 에 고르게 할 스티커


# ---------------------------------------------------------------- 블록 구성 (로그인 필요 없음)


def article_template() -> Document:
    """구조·모양·서식은 사람이 정하고, 내용 칸은 비워 두고 hint 로 무엇을 채울지 적는다"""
    return Document([
        Heading("", hint="글 제목 (20자 이내)"),
        Text("", hint="서울 성수동 카페 탐방 후기 본문 3문단. 문단은 줄바꿈으로 나눈다",
             defaults=ParagraphDefaults(line_height=1.8)),
        Quote("", source="", layout=QuotationLayout.BUBBLE, hint="카페 사장님이 한 인상적인 말 한마디"),
        Divider(LineLayout.LINE3),
        Table([["메뉴", "가격", "한줄평"], ["", "", ""], ["", "", ""]], hint="마신 메뉴 2개 (가격은 원 단위)"),
        Vote("", ["", "", ""], hint="다음에 가 볼 동네 투표 (항목 3개)"),
        Schedule("", datetime(2026, 12, 5, 14, tzinfo=KST), hint="같이 가는 번개 모임"),
        Code("", CodeLayout.BLACK, hint="카페 위치를 담은 짧은 JSON 예시"),
        Sticker("cafe_001", 1),
    ], defaults=ParagraphDefaults(style=TextStyle(font=FontFamily.NANUM_SQUARE), align=Align.JUSTIFY))


# ---------------------------------------------------------------- AI


def ask_claude(prompt: str, schema: dict[str, Any], model: str) -> Any:
    exe = shutil.which("claude")
    if not exe:
        sys.exit("claude CLI 가 없습니다 (--dummy 로 흐름만 확인할 수 있습니다)")
    # claude CLI 의 검사기는 "$schema": draft 2020-12 선언을 모른다 -> 선언만 빼고 보낸다 (내용은 같음)
    sent = {k: v for k, v in schema.items() if k != "$schema"}
    cmd = [exe, "-p", prompt, "--output-format", "json", "--json-schema", json.dumps(sent, ensure_ascii=False),
           "--model", model, "--no-session-persistence", "--tools", ""]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=600, check=False)
    except subprocess.TimeoutExpired:
        sys.exit("claude 응답이 600초 안에 오지 않았습니다")
    out = r.stdout.decode("utf-8", "replace")
    err = r.stderr.decode("utf-8", "replace")[:500]
    try:
        res = json.loads(out)
    except ValueError:
        sys.exit(f"claude 응답을 읽지 못했습니다 (exit {r.returncode}):\n{out[:500]}\n{err}")
    if not isinstance(res, dict):
        sys.exit(f"claude 응답 형식이 다릅니다 (exit {r.returncode}): {out[:300]}")
    if res.get("is_error") or "structured_output" not in res:
        sys.exit(f"claude 오류: {res.get('subtype')} {str(res.get('result'))[:300]}")
    return res["structured_output"]


def dummy(schema: dict[str, Any]) -> Any:
    """스키마만 보고 가짜 값을 만든다 (AI 없이 흐름 확인용). 선택 칸도 채우고, 만든 값은 스키마로 다시 검사한다"""
    value = _dummy(schema, schema.get("$defs", {}))
    jsonschema.validate(value, schema)
    return value


def _dummy(schema: dict[str, Any], defs: dict[str, Any]) -> Any:
    if "$ref" in schema:
        return _dummy(defs[schema["$ref"].rsplit("/", 1)[-1]], defs)
    if "const" in schema:
        return schema["const"]
    for key in ("anyOf", "allOf", "oneOf"):
        if key in schema:
            return _dummy({**schema[key][0], **{k: v for k, v in schema.items() if k != key}}, defs)
    t = schema.get("type")
    if t == "object":
        return {k: _dummy(v, defs) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        if "prefixItems" in schema:
            return [_dummy(s, defs) for s in schema["prefixItems"]]
        n = schema.get("minItems", 1)
        return [_dummy(schema.get("items", {"type": "string"}), defs) for _ in range(n)]
    if "enum" in schema:
        return schema["enum"][0]
    if t in ("integer", "number"):
        return schema.get("minimum", 1)
    if t == "boolean":
        return False
    if "pattern" in schema and re.fullmatch(schema["pattern"], STICKERS[0]):   # 스티커 id 칸
        return STICKERS[0]
    if "pattern" in schema:
        raise ValueError(f"dummy 가 이 pattern 의 값을 만들 줄 모릅니다: {schema['pattern']}")
    text = f"가짜 {schema.get('description', '값')}"
    return text[: schema.get("maxLength", 20)]


# ---------------------------------------------------------------- 실행


def save(name: str, data: Any) -> Path:
    p = OUT / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def check_schema(data: Any, schema: dict[str, Any], what: str) -> None:
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        check(False, f"{what} - {e.message}")
    check(True, what)


def check(cond: bool, what: str) -> None:
    print(("  OK   " if cond else "  FAIL ") + what)
    if not cond:
        raise SystemExit(1)


def run_article(fill_ai: Any) -> None:
    print("[게시글]")
    tpl = article_template()
    schema = tpl.fill_schema()
    save("article_template.spec.json", tpl.to_spec(ids=True))
    save("article_fill_schema.json", schema)
    print(f"  채울 칸: {list(schema['properties'])}")

    data = fill_ai("카페 커뮤니티에 올릴 게시글 내용을 스키마 칸에 맞춰 한국어로 채워줘. "
                   "각 칸의 description 을 따르고, 빈 문자열 없이 자연스럽게.", schema)
    save("article_ai.json", data)
    check_schema(data, schema, "AI 응답이 fill 스키마에 맞음")

    doc = tpl.fill(data)          # 같은 구조·id·모양·서식에 내용만 채운 새 문서 (strict: 칸 누락·초과면 오류)
    spec = doc.to_spec(ids=True)
    content = doc.to_dict()
    sp = save("article_filled.spec.json", spec)
    cp = save("article_filled.content.json", content)
    print(f"  저장: {sp.name}, {cp.name}")

    # 구조 유지
    check([type(b) for b in doc.blocks] == [type(b) for b in tpl.blocks], "블록 종류·순서 그대로")
    check([b.id for b in doc.blocks] == [b.id for b in tpl.blocks], "블록 id 그대로")
    # 위치를 숫자로 박지 않고 종류로 찾는다 (템플릿 순서를 바꿔도 그대로 돈다)
    def at(kind: type) -> int:
        return next(i for i, b in enumerate(tpl.blocks) if isinstance(b, kind))

    def key(kind: type) -> str:
        return next(k for k, i in fill_keys(tpl) if i == at(kind))

    h, t, v = at(Heading), at(Text), at(Vote)
    comps = content["document"]["components"]
    check(tpl.blocks[h].content[0].text == "", "템플릿 원본은 바뀌지 않음")
    check(doc.blocks[h].content[0].text == data[key(Heading)]["content"], "제목이 AI 값으로 채워짐")
    check(len(doc.blocks[v].items) == 3 and all(i.name for i in doc.blocks[v].items), "투표 항목 3개 채워짐")
    check(comps[t]["value"][0]["style"]["lineHeight"] == 1.8, "블록 기본 서식 유지")
    check(comps[h]["title"][0]["nodes"][0]["style"]["fontFamily"] == "nanumsquare", "문서 기본 서식(서체) 유지")

    # 저장한 JSON 을 다시 읽어 같은 문서가 되는지
    back = Document.from_dict(json.loads(cp.read_text(encoding="utf-8")))
    check(back.to_dict() == content, "contentJson 저장 -> from_dict -> to_dict 동일")
    back2 = Document.from_spec(json.loads(sp.read_text(encoding="utf-8")))
    check(back2.to_spec(ids=True) == spec, "spec 저장 -> from_spec -> to_spec 동일")


def run_comment(fill_ai: Any) -> None:
    print("[댓글]")
    schema = CommentDraft.json_schema(hint="위 성수동 카페 글에 다는 짧은 공감 댓글 (2문장)")
    save("comment_schema.json", schema)
    data = fill_ai(f"카페 게시글에 달 댓글을 스키마에 맞춰 채워줘. 스티커는 다음 중 하나: {', '.join(STICKERS)}", schema)
    save("comment_ai.json", data)
    check_schema(data, schema, "AI 응답이 댓글 스키마에 맞음")

    draft = CommentDraft.from_spec(data)
    form = draft.to_dict()
    p = save("comment_filled.json", {"spec": draft.to_spec(), "form": form})
    print(f"  저장: {p.name}")
    check(bool(draft.text.strip()), "댓글 글 채워짐")
    check(form["content"] == draft.text, "댓글 폼 content = 글")
    check(not draft.sticker or form["stickerId"] == draft.sticker.comment_id, "스티커 id 폼 반영")
    back = CommentDraft.from_dict(json.loads(p.read_text(encoding="utf-8"))["form"])
    check(back.to_dict() == form, "댓글 폼 저장 -> from_dict -> to_dict 동일")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--dummy", action="store_true", help="AI 없이 가짜 값")
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):   # 콘솔이 cp949 등이어도 한글·기호가 깨지거나 죽지 않게
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    OUT.mkdir(exist_ok=True)

    def fill_ai(prompt: str, schema: dict[str, Any]) -> Any:
        if a.dummy:
            return dummy(schema)
        print(f"  AI 호출 ({a.model}) ...", flush=True)
        return ask_claude(prompt, schema, a.model)

    run_article(fill_ai)
    run_comment(fill_ai)
    print(f"완료 - {OUT}")


if __name__ == "__main__":
    main()
