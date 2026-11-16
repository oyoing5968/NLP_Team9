#!/usr/bin/env python3
"""Parallel version of benchmark_frontier.py (a GPU machine or this Mac).

Same record and event formats, so report_frontier.py and eval/grade.py read
the output unchanged. Runs (case, seed, method) jobs on a thread pool; the
model server must allow that many parallel requests (OLLAMA_NUM_PARALLEL).
"""
import argparse
import dataclasses
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracetalk.mad.benchmark import read_inputs, record_for  # noqa: E402
from tracetalk.mad.card import CARD, MODES as CARD_MODES, CardAnalyzer  # noqa: E402
from tracetalk.mad.engine import Analyzer, MODES, ROUTER, caps_for, request_from  # noqa: E402
from tracetalk.db.lexicon import load_easy_drafts, load_lexicon, with_easy_drafts  # noqa: E402
from tracetalk.db.usage import load_usages  # noqa: E402
from tracetalk.model import add_model_arguments, config_from  # noqa: E402
from tracetalk.model import make_client  # noqa: E402


def card_config(args):
    return {"parallel_items": args.parallel_items, "slang_probe": not args.no_slang_probe, "gate": args.gate,
            "unknown": args.unknown, "judge": args.judge, "oov": not args.no_oov, "one_sense": args.one_sense,
            "decide": args.decide, "pick": args.decide == "witness",  # the 0.8 card (roles) had no one-part question
            "post_read": args.post_read, "headwords": not args.no_headwords, "judge_examples": args.judge_examples,
            "tau_literal": args.tau_literal,  # v13 stated + headwords; 0.9 summary, no headwords
            "contrast": args.contrast, "tau_contrast_check": args.tau_contrast_check, "tau_contrast_literal": args.tau_contrast_literal,
            "debate": args.debate, "tau_verify": args.tau_verify, "tau_concede": args.tau_concede,  # v16 토론
            "mad_first": args.mad_first, "debate_mode": args.debate_mode}


def main():
    p = add_model_arguments(argparse.ArgumentParser(description=__doc__))
    p.set_defaults(model=None, context_size=8192)
    p.add_argument("--inputs", nargs="+", required=True)
    p.add_argument("--methods", nargs="+", choices=[m for m in MODES if m != "auto"] + list(CARD_MODES), default=["direct"])
    p.add_argument("--lexicon", nargs="*", default=[],
                   help="rag·vote_rag·debate_v2·routed·card가 쓰는 사전(여러 파일 가능). 평가에는 lexicon_eval_v1을 쓴다.")
    p.add_argument("--easy-draft", nargs="*", default=[],
                   help="card: 교사가 DB 뜻만 보고 쓴 쉬운 표현 초안(eval/draft_easy.py). 팀 쉬운 표현이 우선, 카드에 초안 표시.")
    p.add_argument("--stratum", nargs="*", default=[], help="--gold의 이 층(registered 등) 사례만 돌림(관문 실행).")
    p.add_argument("--gold", default=None)
    p.add_argument("--parallel-items", type=int, default=1,
                   help="card: 한 댓글에서 동시에 푸는 표현 수. 1이면 사례당 동시 요청이 MAD와 같은 2개.")
    p.add_argument("--no-slang-probe", action="store_true", help="card: 기록만 하는 has_slang 탐침을 건너뜀(맥).")
    # 0.8 (tracetalk/mad/card.py CARD): the 0.7 behavior is gate=probe, unknown=guess, judge=v9, --no-oov
    p.add_argument("--gate", choices=["review", "probe"], default=CARD["gate"], help="card: 검수 전 뜻을 MAD로(review)")
    p.add_argument("--unknown", choices=["read", "mad", "guess"], default=CARD["unknown"],
                   help="card: DB에 없는 말을 문맥 읽기로(read, 0.9) 또는 MAD로(mad, 0.8)")
    p.add_argument("--decide", choices=["witness", "roles"], default=CARD["decide"],
                   help="card: DB 뜻 판정. witness = 보기 판정 + 문맥 읽기(0.9), roles = 5호출 MAD(0.8)")
    p.add_argument("--judge", choices=["v9", "v10"], default=CARD["judge"], help="card: MAD 판정 역할")
    p.add_argument("--no-oov", action="store_true", help="card: 형태소 분석기가 모르는 낱말을 후보로 올리지 않음")
    p.add_argument("--second-model", default="", help="card: 글을 따로 읽는 두 번째 모델 (서로 다른 모델 비교, docs/DESIGN.md)")
    p.add_argument("--corpus", default=None, help="card: 근거 글(jsonl, tracetalk/evidence/corpus.py). 없으면 글을 읽지 않음")
    p.add_argument("--tau-literal", type=float, default=0.7, help="card: 표준어 판정에 필요한 몫(v13 0.7, 0.9는 0)")
    p.add_argument("--judge-examples", action="store_true", help="card: DB 용례를 판정에 참고로 보여 줌(v13 시험)")
    p.add_argument("--contrast", action=argparse.BooleanOptionalAction, default=CARD["contrast"],
                   help="card: v15 반대 근거(보이려는 뜻 대 글자 그대로, 두 쪽만). --no-contrast = v14까지")
    p.add_argument("--tau-contrast-check", type=float, default=CARD["tau_contrast_check"], help="card: 글자 그대로 몫이 이만큼이면 뜻 확인 필요")
    p.add_argument("--tau-contrast-literal", type=float, default=CARD["tau_contrast_literal"], help="card: 글자 그대로 몫이 이만큼이면 표준어로 읽음(1.01 = 기록만)")
    p.add_argument("--debate", action=argparse.BooleanOptionalAction, default=CARD["debate"],
                   help="card: v16 토론(E가 B에게 글의 문장을 요구, D의 반박에 뜻을 낸 쪽이 단서로 답하거나 물러남)")
    p.add_argument("--tau-verify", type=float, default=CARD["tau_verify"], help="card: E가 인용을 받아들이는 '그렇다' 몫")
    p.add_argument("--tau-concede", type=float, default=CARD["tau_concede"], help="card: 물러날 때 표준어로 읽는 D의 몫")
    p.add_argument("--debate-mode", choices=["select", "quote"], default=CARD["debate_mode"],
                   help="card: v16 토론에서 B의 뜻을 받치는 문장을 E가 후보 중에서 고름(select) / B가 베껴 옴(quote, v16d)")
    p.add_argument("--mad-first", action=argparse.BooleanOptionalAction, default=CARD["mad_first"],
                   help="card: v16 MAD 우선(모든 낱말에 B·C, 근거가 없으면 C가 문맥으로 해석)")
    p.add_argument("--no-headwords", action="store_true", help="card: 근거 글 표제어를 후보로 올리지 않음(0.9)")
    p.add_argument("--post-read", choices=["stated", "summary"], default="stated", help="card: v13 글 읽기(stated: 글이 적은 풀이 우선) / 0.9(summary)")
    # 0.8.1: MAD over a word with one DB sense: DB 뜻 쪽 vs 반대 쪽 (check) or the 0.8.0 candidate comparison (compare)
    p.add_argument("--one-sense", choices=["check", "compare"], default=CARD["one_sense"],
                   help="card: DB 뜻이 하나인 말의 MAD 역할")
    p.add_argument("--retriever", choices=["off", "auto"], default="off",
                   help="card: DB 검색기(tracetalk/db/retriever.py). auto = 이 기기에 있는 단계. 이전 실험은 off(v9 비교 유지).")
    p.add_argument("--embed-model", default="bge-m3")
    p.add_argument("--chroma", default=None)
    p.add_argument("--usages", nargs="*", default=[],
                   help="v7 관측 용례(jsonl). usage_direct·usage_mad에 필요하고, routed는 있으면 용례 MAD 경로를 씁니다.")
    p.add_argument("--tau-sense", type=float, default=ROUTER["tau_sense"])
    p.add_argument("--tau-plain", type=float, default=ROUTER["tau_plain"])
    p.add_argument("--seeds", type=int, nargs="+", default=[42])
    p.add_argument("--total-output-tokens", type=int, default=2560)
    p.add_argument("--max-seconds", type=int, default=600)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--output", required=True)
    p.add_argument("--plan-only", action="store_true")
    args = p.parse_args()
    if not args.model or not args.model.strip():
        p.error("--model을 명시하세요.")
    if len(set(args.methods)) != len(args.methods) or len(set(args.seeds)) != len(args.seeds):
        p.error("methods와 seeds에는 중복을 넣지 마세요.")
    if not 1 <= args.workers <= 64:
        p.error("workers는 1~64입니다.")
    for seed in args.seeds:
        request_from({"text": "예산 확인", "seed": seed,
                      "total_output_tokens": args.total_output_tokens, "max_seconds": args.max_seconds})
    cases = []
    for name in args.inputs:
        cases.extend(read_inputs(name))
    if len({c["id"] for c in cases}) != len(cases):
        p.error("입력 파일들 사이에 중복 사례 id가 있습니다.")
    if args.stratum:
        if not args.gold:
            p.error("--stratum에는 --gold가 필요합니다.")
        gold = [json.loads(s) for s in Path(args.gold).read_text(encoding="utf-8").splitlines() if s.strip()]
        keep = {g["case_id"] for g in gold if g.get("stratum") in args.stratum}
        cases = [c for c in cases if c["id"] in keep]
        if not cases:
            p.error("--stratum에 해당하는 사례가 없습니다.")
    if args.limit:
        cases = cases[:args.limit]
    config = config_from(args)
    lexicon = [e for path in args.lexicon for e in load_lexicon(path, missing_ok=False)]
    if len({e['id'] for e in lexicon}) != len(lexicon):
        p.error("사전 파일들 사이에 같은 id가 있습니다.")
    easy_used = easy_stale = 0
    if args.easy_draft:
        lexicon, easy_used, easy_stale = with_easy_drafts(lexicon, load_easy_drafts(args.easy_draft))
    if {"rag", "vote_rag", "debate_v2", "routed"} & set(args.methods) and not lexicon:
        p.error("rag·vote_rag·debate_v2·routed에는 --lexicon이 필요합니다(평가: data/db/lexicon/lexicon_eval_v1.jsonl).")
    usages = load_usages(args.usages, missing_ok=False) if args.usages else []
    if {"usage_direct", "usage_mad"} & set(args.methods) and not usages:
        p.error("usage_direct·usage_mad에는 --usages가 필요합니다(평가: data/db/usage/usages_eval_v1.jsonl).")
    router = {**ROUTER, "tau_sense": args.tau_sense, "tau_plain": args.tau_plain}
    jobs = [(case, seed, method) for case in cases for seed in args.seeds for method in args.methods]
    plan = {"cases": len(cases), "seeds": args.seeds, "methods": args.methods, "workers": args.workers,
            "model": config.model, "temperature": config.temperature,
            "lexicon": args.lexicon, "lexicon_entries": len(lexicon),
            "usages": args.usages, "usage_groups": len(usages),
            "easy_draft": args.easy_draft, "easy_draft_used": easy_used, "easy_draft_stale": easy_stale,
            "strata": args.stratum,
            "router": router,
            "generation_calls_upper_bound": sum(1 if m in ("direct", "rag", "usage_direct") else 5 for _, _, m in jobs
                                                if m not in CARD_MODES),
            "output_caps_per_method": {m: CARD["caps"] if m in CARD_MODES else caps_for(m, args.total_output_tokens)
                                       for m in args.methods},
            "card_parallel_items": args.parallel_items, "retriever": args.retriever,
            "card_config": card_config(args),
            "slang_probe": not args.no_slang_probe}
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if args.plan_only:
        return 0
    output = Path(args.output)
    events = output.with_name(output.name + ".events.jsonl")
    if output.exists() or events.exists():
        p.error("결과 또는 이벤트 파일이 이미 존재합니다. 새 경로를 지정하세요.")
    client = make_client(config)
    health = client.health()
    if not health.get("ready"):
        p.error(f"모델이 준비되지 않았습니다: {health.get('message')}")
    second = None
    if args.second_model:
        second = make_client(dataclasses.replace(config, model=args.second_model))
        if not second.health().get("ready"):
            p.error(f"두 번째 모델이 준비되지 않았습니다: {args.second_model}")
    retriever = None
    if args.retriever == "auto":
        from tracetalk.db.retriever import build
        retriever = build(args.base_url, args.embed_model, args.chroma, log=lambda m: print(m, flush=True))
    posts = None
    if args.corpus:
        from tracetalk.evidence.corpus import load
        posts = load(args.corpus)
        print(f"근거 글 {len(posts)}개 ({args.corpus})", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    done = {"n": 0, "failed": 0}
    with output.open("x", encoding="utf-8") as handle, events.open("x", encoding="utf-8") as journal:
        def save_event(event):
            line = json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
            with lock:
                journal.write(line)
                journal.flush()

        def run(case, seed, method):
            meta = {"case_id": case["id"], "seed": seed, "method": method}
            save_event({**meta, "type": "scheduled", "text": case["text"], "plan": plan})
            emit = lambda event: save_event({**meta, **event})
            if method in CARD_MODES:
                runner = CardAnalyzer(client, emit=emit, lexicon=lexicon, usages=usages,
                                      config=card_config(args), retriever=retriever, corpus=posts, second=second)
                result = runner.run(text=case["text"], mode=method, seed=seed, max_seconds=args.max_seconds)
            else:
                runner = Analyzer(client, emit=emit, lexicon=lexicon, router=router, usages=usages)
                result = runner.run(text=case["text"], mode=method, seed=seed,
                                    total_output_tokens=args.total_output_tokens, max_seconds=args.max_seconds)
            record = record_for(case, seed, method, result)
            line = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
            with lock:
                handle.write(line)
                handle.flush()
                done["n"] += 1
                done["failed"] += result["status"] != "completed"
                print(json.dumps({**meta, "status": result["status"], "seconds": result["elapsed_seconds"],
                                  "progress": f"{done['n']}/{len(jobs)}", "failed": done["failed"]},
                                 ensure_ascii=False), flush=True)

        with ThreadPoolExecutor(args.workers) as pool:
            futures = [pool.submit(run, *job) for job in jobs]
            try:
                for future in as_completed(futures):
                    future.result()
            except KeyboardInterrupt:
                for future in futures:
                    future.cancel()
                save_event({"type": "interrupted"})
                return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
