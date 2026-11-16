#!/usr/bin/env python3
"""A local model alone on a commercial-AI question sheet (docs/DESIGN.md 추가 시험): the sheet's own rules, one comment at a time (a
small model given 18 or 118 comments at once loses the line format), the answer as fixed JSON, written as the commercial answers'
`no | 표현 | 뜻 | 유래 | 확신` lines so the same blind judging takes it. temperature 0, seed 42, no thinking, once; a finished file is not redone.

    python3 eval/ask_local.py --model exaone35-78b --sheet data/eval/fresh_v5/ask_alone.txt --out data/eval/fresh_v5/answers_local_exaone.txt
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

SCHEMA = {"type": "object", "properties": {
    "expression": {"type": "string"}, "meaning": {"type": "string"}, "origin": {"type": "string"},
    "confidence": {"type": "string", "enum": ["확실", "추정", "모름", "-"]}},
    "required": ["expression", "meaning", "origin", "confidence"]}
LINE_RULE = re.compile(r"^- 댓글마다 한 줄로만.*$", re.M)
NONE_RULE = re.compile(r"^- 신조어·밈이 없으면:.*$", re.M)


def parse_sheet(text):
    """(rules, [(no, comment)]): the rule lines as the sheet words them, and the numbered comments."""
    rules = "\n".join(line for line in text.splitlines() if line.startswith("- "))
    items = [(int(m.group(1)), m.group(2)) for m in re.finditer(r"^(\d+)\. (.*)$", text, re.M)]
    return rules, items


def prompt(rules, comment):
    rules = LINE_RULE.sub("- 답은 JSON 하나: expression(표현), meaning(이 문장에서의 뜻), origin(유래: 어디서 나왔는지, 노래·드라마·사람·사건 이름. "
                          "모르면 모름), confidence(확실/추정/모름)", rules)
    rules = NONE_RULE.sub("- 신조어·밈이 없으면: expression은 '없음', 나머지는 '-'", rules)
    return f"아래는 인터넷 댓글 하나입니다. 이 댓글에 나오는 신조어·유행어·밈 표현을 풀이해 주세요.\n규칙:\n{rules}\n\n댓글: {comment}"


def ask(base, model, text, timeout=300):
    body = {"model": model, "messages": [{"role": "user", "content": text}], "format": SCHEMA, "stream": False, "think": False,
            "keep_alive": "10m", "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 400}}
    req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())["message"]["content"]


def field(x):
    return re.sub(r"\s+", " ", str(x or "")).replace("|", "/").strip()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", required=True)
    p.add_argument("--sheet", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--base-url", default="http://127.0.0.1:11435")
    args = p.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} 이(가) 이미 있습니다. 덮어쓰지 않습니다.")
    rules, items = parse_sheet(Path(args.sheet).read_text(encoding="utf-8"))
    lines = [f"# {args.model} 단독 (로컬, {time.strftime('%Y-%m-%d %H:%M')}), {args.sheet}의 규칙을 댓글 하나씩, temperature 0, seed 42"]
    started = time.time()
    for no, comment in items:
        try:
            a = json.loads(ask(args.base_url, args.model, prompt(rules, comment)))
            row = [a.get("expression"), a.get("meaning"), a.get("origin"), a.get("confidence")]
        except Exception as exc:  # recorded as no answer: held, like a commercial "모름"
            row = ["모름", "모름", "모름", "모름"]
            print(f"   {no}: 실패 {exc}", file=sys.stderr)
        lines.append(f"{no} | " + " | ".join(field(x) or "-" for x in row))
        print(lines[-1][:160], flush=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"== {len(items)}문장 {time.time() - started:.0f}초 -> {out}")


if __name__ == "__main__":
    main()
