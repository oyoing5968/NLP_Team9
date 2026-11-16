#!/usr/bin/env python3
"""UI integration only. Every answer is fabricated TEST FIXTURE data, never a real model.

Serves the real demo lexicon, usages and example lines, plus data/db/live (tracetalk/db/update.py), so the screen
shows the routed flow:
    python3 tests/serve_frontier_fixture.py               # no candidate is accepted: MAD
    python3 tests/serve_frontier_fixture.py --sense-yes   # dictionary candidates are accepted (사전 근거 풀이)
    python3 tests/serve_frontier_fixture.py --usage-yes   # usages are accepted when no entry is (용례 MAD)
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracetalk.db.lexicon import DEFAULT_EXAMPLES, DEFAULT_LEXICON, load_examples
from tracetalk.web.server import serve
from tracetalk.db.usage import DEFAULT_USAGES, LIVE_DIR, LiveStore
from frontier_fixture import FixtureClient


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port",type=int,default=8765)
    p.add_argument("--sense-yes",action="store_true",help="fixture probes accept every dictionary candidate")
    p.add_argument("--usage-yes",action="store_true",help="fixture probes accept usages but no dictionary candidate")
    args=p.parse_args()
    print("TEST-FIXTURE-NOT-A-MODEL: UI 연결 확인용이며 성능/시연 결과로 사용하지 마세요.",flush=True)
    client=FixtureClient()
    if args.sense_yes:client.probe=lambda payload:0.9
    if args.usage_yes:client.probe=lambda payload:0.1 if payload["probe"]=="sense" else 0.9
    store=LiveStore([DEFAULT_LEXICON,LIVE_DIR/"entries.jsonl"],[DEFAULT_USAGES,LIVE_DIR/"usages.jsonl"])
    lexicon,_=store.current()
    serve(client,[],args.port,lexicon,load_examples([DEFAULT_EXAMPLES],{e["id"] for e in lexicon}),store)
