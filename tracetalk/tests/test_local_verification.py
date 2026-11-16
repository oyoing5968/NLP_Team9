"""End-to-end transport tests. The Ollama-shaped backend is a labeled fixture."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from tracetalk import verify as verify_local
from frontier_fixture import FixtureClient


class OllamaFixture:
    def __init__(self, truncated=False):
        self.client=FixtureClient()
        self.calls=0
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def send_json(self,body):
                data=json.dumps(body,ensure_ascii=False).encode()
                self.send_response(200);self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
            def do_GET(self):
                if self.path=="/api/version":return self.send_json({"version":"TEST FIXTURE"})
                if self.path=="/api/tags":
                    return self.send_json({"models":[{"name":owner.client.config.model,"digest":"FIXTURE-DIGEST","size":1,
                                                      "details":{"quantization_level":"FIXTURE"}}]})
                if self.path=="/api/ps":return self.send_json({"models":[]})
                self.send_error(404)
            def do_POST(self):
                if self.path!="/api/chat":return self.send_error(404)
                payload=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.calls+=1
                result=owner.client.generate(payload["messages"],payload["format"],payload["options"]["seed"],payload["options"]["num_predict"])
                return self.send_json({"model":owner.client.config.model,"message":{"content":result["raw"]},
                                      "done_reason":"length" if truncated else "stop", "prompt_eval_count":30,"eval_count":20,
                                      "total_duration":1000,"load_duration":100,"prompt_eval_duration":200,"eval_duration":700})
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
    def __enter__(self):
        self.thread.start();return self
    def __exit__(self,*args):
        self.server.shutdown();self.server.server_close();self.thread.join(2)
    def args(self,path):
        return ["--model",self.client.config.model,"--base-url",f"http://127.0.0.1:{self.server.server_port}","--output",str(path)]


class LocalVerificationTests(unittest.TestCase):
    def test_preflight_never_generates_and_records_model_digest(self):
        with tempfile.TemporaryDirectory() as temp, OllamaFixture() as backend, contextlib.redirect_stdout(io.StringIO()):
            path=Path(temp)/"preflight.json"
            self.assertEqual(verify_local.main(backend.args(path)),0)
            report=json.loads(path.read_text())
            self.assertEqual(backend.calls,0)
            self.assertEqual(report["preflight"]["model_metadata"]["digest"],"FIXTURE-DIGEST")
            self.assertEqual(report["smoke"],[])
            self.assertEqual(report["semantic_quality"],"not_evaluated")

    def test_actual_http_adapter_and_app_complete_six_fixture_calls(self):
        with tempfile.TemporaryDirectory() as temp, OllamaFixture() as backend, contextlib.redirect_stdout(io.StringIO()):
            path=Path(temp)/"smoke.json"
            self.assertEqual(verify_local.main(backend.args(path)+["--run-smoke"]),0)
            report=json.loads(path.read_text())
            self.assertEqual(backend.calls,6)
            self.assertEqual(report["evidence_kind"],"fixture_backend")
            self.assertEqual([r["actual_model_calls"] for r in report["smoke"]],[1,5])
            self.assertTrue(all(r["transport_and_schema_passed"] for r in report["smoke"]))
            first=report["smoke"][0]["job"]["result"]["calls"][0]
            self.assertEqual(first["ollama_timings_ns"]["eval_duration"],700)
            self.assertEqual(len(list((Path(temp)/"smoke-jobs").glob('frontier-*.json'))),2)

    def test_invalid_direct_output_stops_before_debate_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as temp, OllamaFixture(truncated=True) as backend, contextlib.redirect_stdout(io.StringIO()):
            path=Path(temp)/"failure.json"
            self.assertEqual(verify_local.main(backend.args(path)+["--run-smoke"]),2)
            report=json.loads(path.read_text())
            self.assertEqual(backend.calls,1)
            self.assertFalse(report["smoke"][0]["transport_and_schema_passed"])
            self.assertEqual(report["smoke"][0]["job"]["status"],"failed")

    def test_offline_backend_produces_report_without_fake_answer(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            path=Path(temp)/"offline.json"
            with patch("tracetalk.verify.ModelClient.health",return_value={"connected":False,"ready":False}), \
                 patch("tracetalk.verify.ModelClient.generate",side_effect=AssertionError("must not call")):
                self.assertEqual(verify_local.main(["--model","MISSING","--output",str(path),"--run-smoke"]),2)
            report=json.loads(path.read_text())
            self.assertEqual(report["smoke"],[])
            self.assertTrue(report["error"])

    def test_existing_result_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()):
            path=Path(temp)/"existing.json";path.write_text("original")
            with self.assertRaises(SystemExit) as caught:
                verify_local.main(["--model","MISSING","--output",str(path)])
            self.assertEqual(caught.exception.code,2)
            self.assertEqual(path.read_text(),"original")


if __name__=="__main__":unittest.main()
