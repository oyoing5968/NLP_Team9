import copy
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tracetalk.mad.benchmark import read_inputs, record_for, summarize
from tracetalk.mad.contracts import FINAL_SCHEMA, cite, parse, quote_spans
from tracetalk.mad.engine import Analyzer, METHODS, cached, caps_for, request_from
from tracetalk.web.server import Jobs, make_server
from frontier_fixture import FixtureClient


class FrontierTests(unittest.TestCase):
    def setUp(self):
        self.text = "🚌 오늘은 팀플 버스 운전까지 했네."

    def final(self):
        return Analyzer(FixtureClient()).run(text=self.text,mode="direct")["analysis"]

    def cache_entry(self):
        now = datetime.now(timezone.utc)
        return {"text":self.text, "approved":True, "reviewer":"TEST REVIEWER",
                "reviewed_at":(now-timedelta(days=1)).isoformat(),
                "expires_at":(now+timedelta(days=1)).isoformat(), "analysis":self.final()}

    def test_single_comment_needs_no_target_or_usage(self):
        result = Analyzer(FixtureClient()).run(text=self.text)
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["method"],"debate")
        self.assertEqual(result["metrics"]["call_count"],5)
        self.assertEqual(result["request"]["text"],self.text)

    def test_independent_start_and_synchronous_peer_review(self):
        client=FixtureClient(); Analyzer(client).run(text=self.text,mode="debate")
        self.assertEqual([r["stage"] for r in client.requests],["propose","propose","review","review","final"])
        self.assertTrue(all(not r["unverified_hypotheses"] for r in client.requests[:2]))
        for request in client.requests[2:4]:
            self.assertEqual(set(request["unverified_hypotheses"]),{"own","peer"})
            self.assertIn("meaning",request["unverified_hypotheses"]["peer"])
            self.assertNotIn("revised_meaning",request["unverified_hypotheses"]["peer"])

    def test_independent_ablation_has_no_peer_but_same_initial_prompts(self):
        debate, independent=FixtureClient(),FixtureClient()
        Analyzer(debate).run(text=self.text,mode="debate")
        Analyzer(independent).run(text=self.text,mode="independent")
        self.assertEqual(debate.requests[:2],independent.requests[:2])
        for request in independent.requests[2:4]:
            self.assertEqual(set(request["unverified_hypotheses"]),{"own"})
        self.assertEqual(debate.requests[-1]["role"],independent.requests[-1]["role"])

    def test_no_dialogue_ablation_cannot_create_dialogues(self):
        result=Analyzer(FixtureClient()).run(text=self.text,mode="no_dialogue")
        self.assertEqual(result["status"],"completed")
        self.assertTrue(all(c["analysis"]["synthetic_dialogue"] == [] for c in result["calls"][:2]))
        client=FixtureClient()
        client.hook=lambda payload,data:data.update(synthetic_dialogue=["허용되지 않는 대화"])
        failed=Analyzer(client).run(text=self.text,mode="no_dialogue")
        self.assertEqual(failed["status"],"failed")

    def test_self_review_sees_only_its_own_previous_answer(self):
        client=FixtureClient();result=Analyzer(client).run(text=self.text,mode="self_review")
        self.assertEqual(result["metrics"]["call_count"],5)
        self.assertEqual(client.requests[0]["unverified_hypotheses"],{"previous":[]})
        self.assertEqual(len(client.requests[1]["unverified_hypotheses"]["previous"]),1)
        self.assertNotIn("peer",client.requests[2]["unverified_hypotheses"])

    def test_output_allocations_share_same_total_upper_bound(self):
        for method in METHODS:
            caps=caps_for(method,2561)
            self.assertEqual(sum(caps),2561)
            result=Analyzer(FixtureClient()).run(text=self.text,mode=method,total_output_tokens=2561)
            self.assertEqual(result["metrics"]["allocated_output_tokens"],2561)
            self.assertEqual(result["metrics"]["completion_tokens"],20*len(caps))

    def test_synthetic_quote_cannot_become_input_evidence(self):
        client=FixtureClient()
        client.hook=lambda payload,data:data.update(input_quotes=["A: 이것은 가상 상황입니다."])
        result=Analyzer(client).run(text=self.text)
        self.assertEqual(result["status"],"failed")
        self.assertIsNone(result["analysis"])
        self.assertEqual(result["metrics"]["call_count"],1)
        self.assertIn("합성",result["error"])

    def test_agreement_is_never_labeled_verified(self):
        result=Analyzer(FixtureClient()).run(text=self.text)
        self.assertEqual(result["analysis"]["status"],"proposed")
        self.assertIsNone(result["review"])
        self.assertFalse(result["synthetic_material_is_evidence"])

    def test_uncertain_output_never_publishes_a_rewrite(self):
        client=FixtureClient()
        def hook(payload,data):
            if payload["stage"]=="final": data.update(status="uncertain",uncertainty=" ")
        client.hook=hook
        failed=Analyzer(client).run(text=self.text)
        self.assertEqual(failed["status"],"failed")
        self.assertIsNone(failed["analysis"])
        def valid_hook(payload,data):
            if payload["stage"]=="final":data["status"]="uncertain"
        client.hook=valid_hook
        valid=Analyzer(client).run(text=self.text)
        self.assertEqual(valid["analysis"]["status"],"uncertain")
        self.assertTrue(valid["analysis"]["replacements"])
        self.assertEqual(valid["rewrite"],{"text":None,"spans":[],"skipped":[]})

    def test_cache_requires_current_exact_human_approval(self):
        entry=self.cache_entry()
        self.assertIsNotNone(cached(self.text,[entry]))
        self.assertIsNone(cached("추가 문맥: "+self.text,[entry]))
        self.assertIsNone(cached(self.text,[{**entry,"approved":False}]))
        self.assertIsNone(cached(self.text,[{**entry,"reviewer":""}]))
        self.assertIsNone(cached(self.text,[{**entry,"expires_at":"2020-01-01T00:00:00+00:00"}]))
        self.assertIsNone(cached(self.text,[entry,copy.deepcopy(entry)]))
        client=FixtureClient()
        result=Analyzer(client,[entry]).run(text=self.text)
        self.assertEqual(result["route"],"reviewed_cache")
        self.assertEqual(result["metrics"]["call_count"],0)
        self.assertEqual(result["metrics"]["completion_tokens"],0)

    def test_research_modes_always_bypass_cache(self):
        for method in METHODS:
            result=Analyzer(FixtureClient(),[self.cache_entry()]).run(text=self.text,mode=method)
            self.assertEqual(result["route"],"model")
            self.assertGreater(result["metrics"]["call_count"],0)

    def test_input_validation_and_unicode_offsets(self):
        for body in ({"text":" "},{"text":self.text,"target":"버스"},
                     {"text":self.text,"seed":True},{"text":self.text,"total_output_tokens":100},
                     {"text":self.text,"mode":[]}):
            with self.assertRaises(ValueError):request_from(body)
        text="🚌 버스, 버스"
        spans=quote_spans(text,["버스"])
        self.assertEqual([s["start"] for s in spans],[2,6])
        self.assertTrue(all(text[s["start"]:s["end"]]==s["quote"] for s in spans))

    def test_v6_quote_marks_and_spacing_resolve_to_the_comment_only(self):
        text="ㄱ- 와... 나 지금 리트만 4번 했음. 든든하겠다"
        self.assertEqual(cite(text,'"ㄱ-"'),"ㄱ-")
        self.assertEqual(cite(text,"‘와...’"),"와...")
        self.assertEqual(cite(text,"리트만 4 번 했음"),"리트만 4번 했음")
        self.assertEqual(cite("공중제비 도는줄 진심","도는 줄 진심"),"도는줄 진심")
        self.assertIsNone(cite("아버지가 방에 들어가신다","가방"))
        self.assertEqual(cite("와 대박 축하드려요! 대박 나세요",'"와 대박 축하드려요!", '),"와 대박 축하드려요")
        for wrong in ("든든겠다","깐부","",'""',"리트만4번했음","리트만4번했음.x"):
            self.assertIsNone(cite(text,wrong))
        raw=json.dumps({"status":"proposed","expressions":['"ㄱ-"'],"interpretation":"TEST",
                        "replacements":[{"expression":"“ㄱ-”","easy":"TEST"}],"nuance":"TEST",
                        "input_quotes":["4 번"],"alternatives":[],"uncertainty":"TEST"},ensure_ascii=False)
        data=parse(raw,FINAL_SCHEMA,text)
        self.assertEqual((data["expressions"],data["input_quotes"],data["replacements"][0]["expression"]),(["ㄱ-"],["4번"],"ㄱ-"))
        with self.assertRaises(ValueError):parse(raw.replace("4 번","든든겠다"),FINAL_SCHEMA,text)

    def test_transport_failure_and_truncation_preserve_failed_attempts(self):
        client=FixtureClient()
        def failure(*args):raise RuntimeError("TEST transport failure")
        client.generate=failure
        result=Analyzer(client).run(text=self.text)
        self.assertEqual(result["status"],"failed")
        self.assertEqual(result["metrics"]["invalid_calls"],1)
        self.assertIsNone(result["metrics"]["completion_tokens"])
        client=FixtureClient();generate=client.generate
        client.generate=lambda *args:{**generate(*args),"finish_reason":"length"}
        result=Analyzer(client).run(text=self.text)
        self.assertEqual(result["status"],"failed")
        self.assertTrue(result["calls"][0]["raw"])

    def test_cancellation_between_calls_stops_further_work(self):
        client=FixtureClient();cancel=threading.Event()
        client.hook=lambda *_:cancel.set()
        result=Analyzer(client,cancel=cancel).run(text=self.text)
        self.assertEqual(result["status"],"cancelled")
        self.assertEqual(result["metrics"]["call_count"],1)

    def test_soft_deadline_stops_after_inflight_call(self):
        client=FixtureClient();clock=[0.0]
        client.hook=lambda *_:clock.__setitem__(0,6.0)
        with patch("tracetalk.mad.engine.time.monotonic",side_effect=lambda:clock[0]):
            result=Analyzer(client).run(text=self.text,max_seconds=5)
        self.assertEqual(result["status"],"timed_out")
        self.assertEqual(result["metrics"]["call_count"],1)
        self.assertEqual(result["elapsed_seconds"],6.0)

    def test_bad_final_and_duplicate_json_keys_are_rejected(self):
        final=self.final();final["input_quotes"]=[]
        with self.assertRaises(ValueError):parse(json.dumps(final),FINAL_SCHEMA,self.text)
        with self.assertRaisesRegex(ValueError,"중복"):
            parse('{"status":"proposed","status":"uncertain"}',FINAL_SCHEMA,self.text)

    def test_input_file_rejects_gold_fields_and_family_leakage(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"input.jsonl"
            row={"id":"a","text":self.text,"family":"bus","split":"train"}
            path.write_text(json.dumps(row),encoding="utf-8")
            self.assertEqual(len(read_inputs(path)),1)
            path.write_text(json.dumps({**row,"gold":"answer"}),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"정답"):read_inputs(path)
            path.write_text(json.dumps(row)+"\n"+json.dumps({**row,"id":"b","split":"test"}),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"계열"):read_inputs(path)

    def test_report_counts_failures_and_does_not_invent_accuracy(self):
        case={"id":"a","text":self.text,"family":"bus","split":"diagnostic"}
        good=Analyzer(FixtureClient()).run(text=self.text,mode="direct")
        bad=copy.deepcopy(good);bad.update(status="failed",analysis=None)
        rows=[record_for(case,42,"direct",good),record_for({**case,"id":"b"},42,"direct",bad)]
        report=next(iter(summarize(rows).values()))
        self.assertEqual(report["attempts"],2)
        self.assertEqual(report["failure_rate"],.5)
        self.assertEqual(report["proposal_coverage"],.5)
        self.assertIsNone(report["semantic_accuracy"])
        with self.assertRaisesRegex(ValueError,"중복"):summarize([rows[0],rows[0]])


class FrontierHTTPTests(unittest.TestCase):
    def test_real_http_job_lifecycle_and_origin_check_with_fixture_model(self):
        with tempfile.TemporaryDirectory() as temp:
            server=make_server(FixtureClient(),port=0,output_dir=temp)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            def request(path,body=None,origin=None):
                headers={"Content-Type":"application/json"}
                if origin:headers["Origin"]=origin
                req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
                with urllib.request.urlopen(req,timeout=3) as response:return response.status,json.load(response)
            try:
                status,created=request("/api/analyze",{"text":"야르"})
                self.assertEqual(status,202)
                for _ in range(100):
                    _,job=request("/api/jobs/"+created["job_id"])
                    if job["status"]!="running":break
                    time.sleep(.01)
                self.assertEqual(job["status"],"completed")
                self.assertEqual(len(job["result"]["calls"]),5)
                self.assertTrue((Path(temp)/job["saved_as"]).exists())
                _,empty=request("/api/jobs/"+created["job_id"]+"?after="+str(job["next_cursor"]))
                self.assertEqual(empty["events"],[])
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    request("/api/analyze",{"text":"야르"},"https://example.invalid")
                self.assertEqual(caught.exception.code,403)
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    request("/api/analyze",{"text":"야르","target":"야르"})
                self.assertEqual(caught.exception.code,400)
                with urllib.request.urlopen(base,timeout=3) as response:
                    self.assertIn('role="tablist"'.encode(),response.read())
                with urllib.request.urlopen(base+"/workspace.css",timeout=3) as response:
                    self.assertIn(b"--olive:#4A4D43",response.read())
            finally:
                server.shutdown();server.server_close();thread.join(2)

    def test_cancelled_job_releases_lock_and_saves_partial_calls(self):
        entered,gate=threading.Event(),threading.Event();client=FixtureClient()
        def hook(*_):entered.set();gate.wait(2)
        client.hook=hook
        with tempfile.TemporaryDirectory() as temp:
            jobs=Jobs(client,[],temp)
            job_id=jobs.create({"text":"야르"})
            self.assertTrue(entered.wait(1))
            with self.assertRaises(RuntimeError):jobs.create({"text":"다른 댓글"})
            self.assertTrue(jobs.cancel(job_id));gate.set()
            for _ in range(100):
                job=jobs.snapshot(job_id)
                if job["status"]!="running":break
                time.sleep(.01)
            self.assertEqual(job["status"],"cancelled")
            self.assertIsNone(jobs.active)
            saved=json.loads((Path(temp)/job["saved_as"]).read_text())
            self.assertEqual(len(saved["calls"]),1)
            self.assertIsNone(saved["analysis"])


if __name__=="__main__":unittest.main()
