"""Security audit for crawled files (docs/CRAWLER.md), run where they are fetched and again where they arrive.

audit_page: one fetched page against its manifest row - size and sha256 as recorded, not a program or an archive
(magic bytes), no NUL, UTF-8 text, and the page's own address (canonical) on the allowlist and on the host it was
fetched from. Scripts, frames, forms and event handlers are counted for the report; they are never run and never
leave the fetch machine (only the plain text blocks and the team sheet do).

audit_out: what is carried to the Mac - the team sheet (exactly the sheet's columns, short plain text, no cell a
spreadsheet would run as a formula, an address only in the source column and only an allowlisted one) and the text
blocks (plain text, capped). Anything else in the folder is refused.
"""
import csv
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from tracetalk.crawl.extract import MAX_PAGE, allowed, read_page

MAGIC = {b"MZ": "Windows 실행 파일", b"\x7fELF": "리눅스 실행 파일", b"\xcf\xfa\xed\xfe": "맥 실행 파일",
         b"\xca\xfe\xba\xbe": "맥 실행 파일", b"PK\x03\x04": "압축 파일", b"\x1f\x8b": "gzip", b"%PDF": "PDF",
         b"7z\xbc\xaf": "7z", b"Rar!": "RAR", b"#!": "스크립트"}
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f‪-‮⁦-⁩]")
TAG = re.compile(r"<\s*/?\s*[a-zA-Z][^>]{0,200}>")
ADDRESS = re.compile(r"https?://|www\.", re.IGNORECASE)
FORMULA = re.compile(r"^[=+\-@\t\r]")
SHEET = ("kind", "expression", "variants", "meaning", "easy", "origin", "pos", "usage", "context", "source")
LIMITS = {"expression": 40, "meaning": 300, "usage": 300, "source": 400}
OUT_FILES = {"sheet.csv", "blocks.jsonl", "manifest.jsonl", "audit.jsonl", "report.jsonl", "SHA256SUMS"}


def audit_page(path, row, sources):
    """{file, verdict ok|refused, problems, counts} for one fetched page."""
    path = Path(path)
    problems, counts = [], {}
    raw = path.read_bytes() if path.is_file() and not path.is_symlink() else b""
    if not raw:
        problems.append("파일 없음·빈 파일·링크")
    if len(raw) > MAX_PAGE or len(raw) != row.get("bytes"):
        problems.append(f"크기 {len(raw)} (기록 {row.get('bytes')}, 상한 {MAX_PAGE})")
    if hashlib.sha256(raw).hexdigest() != row.get("sha256"):
        problems.append("지문이 기록과 다름")
    for magic, what in MAGIC.items():
        if raw.lstrip()[:len(magic)] == magic:
            problems.append(f"글이 아님: {what}")
    if b"\x00" in raw:
        problems.append("NUL 바이트")
    text = raw.decode("utf-8", errors="replace")
    if text.count("�") > 20:
        problems.append("UTF-8 글이 아님")
    low = text.lower()
    counts = {"script": low.count("<script"), "iframe": low.count("<iframe"), "object_embed": low.count("<object")
              + low.count("<embed"), "form": low.count("<form"), "on_handler": len(re.findall(r"\son[a-z]+\s*=", low)),
              "javascript_url": low.count("javascript:"), "data_url": low.count("data:")}
    if not allowed(row.get("url", ""), sources) or not allowed(row.get("final_url", row.get("url", "")), sources):
        problems.append("기록된 주소가 허용 목록 밖")
    if raw and not problems:
        own = read_page(path)["url"]
        if own and (not allowed(own, sources)
                    or urlsplit(own).hostname != urlsplit(row.get("final_url", row["url"])).hostname):
            problems.append(f"페이지가 스스로 밝힌 주소가 다른 곳: {urlsplit(own).hostname}")
    return {"file": path.name, "url": row.get("url"), "verdict": "refused" if problems else "ok",
            "problems": problems, "counts": counts}


def _text_problems(value, field, limit):
    out = []
    if CONTROL.search(value):
        out.append(f"{field}: 제어 문자")
    if TAG.search(value):
        out.append(f"{field}: HTML 태그")
    if len(value) > limit:
        out.append(f"{field}: {len(value)}자 > {limit}")
    if FORMULA.match(value):
        out.append(f"{field}: 수식으로 읽힐 첫 글자")
    return out


def audit_out(folder, sources):
    """[problem, ...] for the folder carried to the Mac (empty = clean)."""
    folder = Path(folder)
    problems = []
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if p.is_symlink() or (p.is_file() and rel not in OUT_FILES) or (p.is_dir()):
            problems.append(f"넘기면 안 되는 것: {rel}")
    sheet = folder / "sheet.csv"
    if sheet.is_file():
        with sheet.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != SHEET:
                problems.append("sheet.csv: 열이 팀 표와 다름")
            for n, row in enumerate(reader, start=2):
                if row.get("kind") not in ("뜻", "용례"):
                    problems.append(f"sheet.csv {n}: kind")
                for field in SHEET:
                    value = row.get(field) or ""
                    problems += [f"sheet.csv {n} {p}" for p in _text_problems(value, field, LIMITS.get(field, 120))]
                    if field != "source" and ADDRESS.search(value):
                        problems.append(f"sheet.csv {n} {field}: 주소가 들어 있음")
                for url in re.findall(r"https?://[^\s·]+", row.get("source") or ""):
                    if not allowed(url, sources):
                        problems.append(f"sheet.csv {n}: 허용 목록 밖 출처 {urlsplit(url).hostname}")
    for name in ("manifest.jsonl", "audit.jsonl", "report.jsonl"):  # records: JSON lines, addresses on the list only
        path = folder / name
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines() if path.is_file() else [], start=1):
            try:
                row = json.loads(line)
            except ValueError:
                problems.append(f"{name} {n}: JSON 아님")
                continue
            if CONTROL.search(line) or TAG.search(line):
                problems.append(f"{name} {n}: 제어 문자·태그")
            for key in ("url", "final_url"):
                if row.get(key) and not allowed(row[key], sources) and name != "manifest.jsonl":
                    problems.append(f"{name} {n}: 허용 목록 밖 주소")
    blocks = folder / "blocks.jsonl"
    if blocks.is_file():
        for n, line in enumerate(blocks.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                page = json.loads(line)
            except ValueError:
                problems.append(f"blocks.jsonl {n}: JSON 아님")
                continue
            if set(page) != {"file", "url", "date", "blocks"} or not allowed(page["url"], sources):
                problems.append(f"blocks.jsonl {n}: 형식 또는 주소")
                continue
            for b in page["blocks"]:
                if set(b) != {"kind", "text"} or b["kind"] not in ("h", "p"):
                    problems.append(f"blocks.jsonl {n}: 블록 형식")
                    break
                problems += [f"blocks.jsonl {n} {p}" for p in _text_problems(b["text"], "text", 2000)
                             if "수식" not in p]
    return problems
