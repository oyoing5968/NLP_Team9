#!/usr/bin/env python3
"""Why calls failed the original-text citation check: what the model quoted that is not in the comment.

Read-only, run_bench outputs only (no gold). Every quote or expression in a failed call that is not
an exact substring of the comment is sorted into one kind, first match wins:
  empty     blank string
  wrapped   in the comment once surrounding quote marks, brackets, spaces or end punctuation go
  spacing   in the comment once all whitespace is ignored on both sides
  dialogue  copied from the call's own synthetic dialogue/contrast or from another agent's output
  other     anything else (base form, paraphrase, typo ...)
Examples show the comment and the quote only for files whose name lacks "koneo": KoNeoBench is
evaluation data and is not copied out, so for it only counts are printed.

    python3 eval/quote_misses.py runs/pilot/student_pilot20_t2560.jsonl runs/pilot/student_koneo10_t2560.jsonl
"""
import argparse
import json
from collections import Counter
from pathlib import Path

WRAP = " \t\n'\"‘’“”「」『』()[]<>.,!?~…"


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def kind(quote, text, synthetic):
    if not quote.strip():
        return "empty"
    bare = quote.strip(WRAP)
    if bare and bare in text:
        return "wrapped"
    if "".join(quote.split()) in "".join(text.split()):
        return "spacing"
    if any(quote in s for s in synthetic):
        return "dialogue"
    return "other"


def misses(rows, show=True, per_kind=3):
    counts, examples = Counter(), {}
    for row in rows:
        result = row["result"]
        text = result["request"]["text"]
        for call in result.get("calls", []):
            if "인용은 원문" not in (call.get("error") or ""):
                continue
            try:
                data = json.loads(call["raw"])
                material = json.loads(call["messages"][1]["content"]).get("unverified_hypotheses")
            except (TypeError, ValueError, KeyError, IndexError):
                counts[(row["method"], call["stage"], "-", "unparsed")] += 1
                continue
            synthetic = list(strings(material)) + list(strings([data.get("synthetic_dialogue"), data.get("contrast")]))
            for field in ("input_quotes", "expressions"):
                for quote in data.get(field) or []:
                    if quote.strip() and quote in text:
                        continue
                    k = kind(quote, text, synthetic)
                    counts[(row["method"], call["stage"], field, k)] += 1
                    if show and len(examples.setdefault(k, [])) < per_kind:
                        examples[k].append((row["method"], call["stage"], field, text, quote))
    return counts, examples


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("runs", nargs="+")
    p.add_argument("--examples", type=int, default=3, help="examples per kind (non-KoNeoBench files only)")
    args = p.parse_args(argv)
    counts, examples = Counter(), {}
    for name in args.runs:
        rows = [json.loads(s) for s in Path(name).read_text(encoding="utf-8").splitlines() if s.strip()]
        c, e = misses(rows, show="koneo" not in Path(name).name, per_kind=args.examples)
        counts.update(c)
        for k, items in e.items():
            examples.setdefault(k, []).extend(items[:args.examples - len(examples.get(k, []))])
    by_kind = Counter()
    for (_, _, _, k), n in counts.items():
        by_kind[k] += n
    print(f"원문에 없는 인용 {sum(counts.values())}개 (실패 호출 안의 인용 단위). 종류별 {dict(by_kind.most_common())}")
    for (method, stage, field, k), n in sorted(counts.items()):
        print(f"    {method:<10} {stage:<12} {field:<13} {k:<9} {n}")
    for k, items in examples.items():
        for method, stage, field, text, quote in items:
            print(f"예[{k}] {method}/{stage}/{field}: 원문 {text[:80]!r} → 인용 {quote[:80]!r}")
    return counts


if __name__ == "__main__":
    main()
