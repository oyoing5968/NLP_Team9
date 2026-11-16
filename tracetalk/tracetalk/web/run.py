#!/usr/bin/env python3
"""댓글 한 건을 분석하는 TraceTalk 실행기. 사용할 실제 모델을 명시해야 한다."""
import argparse
import json
import sys
from pathlib import Path

from tracetalk.mad.engine import load_cache
from tracetalk.db.lexicon import DEFAULT_EXAMPLES, DEFAULT_LEXICON, load_examples
from tracetalk.web.server import load_prepared, serve, store_summary
from tracetalk.db.usage import DEFAULT_USAGES, LIVE_DIR, LiveStore
from tracetalk.model import add_model_arguments, config_from
from tracetalk.model import make_client


# 실행 옵션에 지정된 주소·임베딩 모델·색인 경로로 사전 검색기를 구성한다.
def make_retriever(args):
    from tracetalk.db.retriever import build
    return build(args.base_url, args.embed_model, args.chroma, log=lambda m: print(m, flush=True))


# 실행 옵션과 파일을 검증하고 모델·사전·용례를 연결한 뒤 상태 확인 또는 웹 서버 실행을 수행한다.
def main():
    parser = add_model_arguments(argparse.ArgumentParser(description=__doc__))
    parser.set_defaults(model=None, context_size=8192)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cache", default=None)
    parser.add_argument("--lexicon", nargs="+", default=[str(DEFAULT_LEXICON)],
                        help="routed 모드의 검색 사전(jsonl, 여러 개 가능: 시연 사전 + 최신 사전). 팀 검수 전 자료입니다.")
    parser.add_argument("--usages", nargs="*", default=[str(DEFAULT_USAGES)],
                        help="관측 용례(jsonl). 사전에 뜻이 없을 때 용례 MAD의 근거가 됩니다.")
    parser.add_argument("--live", default=str(LIVE_DIR),
                        help="tracetalk/db/update.py가 쓰는 폴더. 그 안의 entries.jsonl·usages.jsonl은 재시작 없이 반영됩니다.")
    parser.add_argument("--easy-draft", nargs="*", default=[],
                        help="교사가 DB 뜻만 보고 쓴 쉬운 표현 초안(jsonl). 팀 쉬운 표현이 우선, 카드에 '교사 초안 · 검수 전' 표시.")
    parser.add_argument("--examples", nargs="*", default=[str(DEFAULT_EXAMPLES)],
                        help="화면의 '관련 예시' 줄(jsonl). 모델에 주지 않고 사람에게만 보여 줍니다.")
    parser.add_argument("--parallel-items", type=int, default=1,
                        help="결과 카드에서 동시에 푸는 표현 수. 노트북의 Ollama가 요청을 하나씩 받으면 1(기본).")
    parser.add_argument("--prepared", nargs="*", default=[],
                        help="시연 대비: 미리 계산한 카드(run_bench 결과 jsonl, 예: mac/measure.sh 출력). 같은 문장·방식이면 "
                             "모델을 부르지 않고 보여 주되 화면에 '미리 계산한 결과'로 표시합니다.")
    parser.add_argument("--no-slang-probe", action="store_true",
                        help="결과 카드: 기록만 하는 '신조어가 있나' 탐침을 건너뜀(요청을 하나씩 받는 노트북에서 카드당 몇 초 절약).")
    parser.add_argument("--retriever", choices=["off", "auto"], default="off",
                        help="결과 카드의 DB 검색기(tracetalk/db/retriever.py): auto = 이 기기에 있는 단계(형태소·오타·의미 검색)를 씀.")
    parser.add_argument("--embed-model", default="bge-m3", help="의미 검색(관련 용례 순서) 임베딩 모델(Ollama).")
    parser.add_argument("--chroma", default=None, help="의미 검색 색인 폴더(기본: _mac_runtime/chroma).")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--setup", action="store_true")
    args = parser.parse_args()
    if not args.model or not args.model.strip():
        parser.error("--model에 설치한 모델 이름을 지정하세요. 최종 모델은 아직 선정하지 않았습니다.")
    if not 1024 <= args.port <= 65535:
        parser.error("port는 1024~65535입니다.")
    if args.provider == "llama-cpp" and not Path(args.model_path).is_file():
        parser.error("--model-path에 GGUF 파일이 필요합니다. 이 어댑터는 CPU 전용입니다.")
    config = config_from(args)
    if args.setup:  # 이전 실행기의 모델 설치 기능은 포함하지 않으므로 별도 설치 스크립트를 안내한다.
        parser.error("--setup은 이 폴더에 없습니다. 모델은 mac/setup.sh와 mac/import_student.sh로 설치·등록합니다.")
    client = make_client(config)
    if args.check:
        health = client.health()
        print(json.dumps(health, ensure_ascii=False, indent=2))
        return 0 if health["ready"] else 1
    for name in args.lexicon + args.usages + args.easy_draft:
        if not Path(name).is_file():
            parser.error(f"파일이 없습니다: {name}")
    live = Path(args.live)
    store = LiveStore(args.lexicon + [str(live / "entries.jsonl")], args.usages + [str(live / "usages.jsonl")],
                      args.easy_draft, candidates_path=live / "candidates.jsonl")  # 새 표현을 기록할 검수 후보 파일을 연결한다.
    lexicon, _ = store.current()
    examples = load_examples(args.examples, {e["id"] for e in lexicon})
    summary = store_summary(store)
    print(f"검색 사전 {summary['lexicon_entries']}개 항목 · 용례 {summary['usage_groups']}개 표현 "
          f"{summary['usage_lines']}문장 · 최신 추가 {len(summary['latest'])}건 (폴더 {live}) · 예시가 있는 항목 {len(examples)}개",
          flush=True)
    retriever = make_retriever(args) if args.retriever == "auto" else None
    for name in args.prepared:
        if not Path(name).is_file():
            parser.error(f"파일이 없습니다: {name}")
    if args.prepared:
        print(f"미리 계산한 카드 {len(load_prepared(args.prepared))}개 (화면에 '미리 계산한 결과'로 표시)", flush=True)
    serve(client, load_cache(args.cache), args.port, lexicon, examples, store,
          card_config={"parallel_items": max(1, args.parallel_items), "slang_probe": not args.no_slang_probe},
          retriever=retriever, prepared=load_prepared(args.prepared), live=live)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, ImportError, OSError) as exc:
        print(f"실행 오류: {exc}", file=sys.stderr)
        sys.exit(1)
