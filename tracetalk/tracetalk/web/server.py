"""로컬 댓글 분석 API. 화면용 테스트 결과를 실제 모델의 분석 결과로 표시하지 않는다."""
import copy
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tracetalk import VERSION, PROTOCOL
from tracetalk.db import review
from tracetalk.mad.card import MODES as CARD_MODES, CardAnalyzer, card_request
from tracetalk.mad.engine import Analyzer, MODES, ROOT, request_from


def related_examples(result, examples):
    """해석 결과 아래에 표시할 관련 용례를 분석 경로에 맞게 구성한다.

    용례 기반 분석은 모델이 읽은 문장을 출처별로 묶고, 판정에 인용한 문장을 먼저 배치한다.
    각 문장에는 용례 식별 번호를 붙인다. 사전 기반 분석은 채택한 항목의 화면 표시용 예문을
    반환하며, 이 예문은 모델에 보내지 않는다. 그 밖의 분석 경로는 빈 목록을 반환한다.
    """
    routing = result.get("routing") or {}
    lines = routing.get("usage_lines") or []
    if lines:
        cited = (result.get("analysis") or {}).get("supporting_usages", [])
        lines = sorted(lines, key=lambda u: u["id"] not in cited)
        blocks = {}
        for u in lines:
            block = blocks.setdefault(u["source"], {"entry_id": routing["usage_group"]["id"],
                                                    "expression": routing["usage_group"]["expression"], "lines": [],
                                                    "source": u["source"], "license": u["license"], "note": u["note"],
                                                    "added_at": u["added_at"], "cited": []})
            block["lines"].append(f"{u['id']} · {u['text']}")
            block["cited"] += [u["id"]] if u["id"] in cited else []
            block["added_at"] = max(block["added_at"], u["added_at"])
        return list(blocks.values())
    if routing.get("route") not in ("lexicon", "disambiguate"):
        return []
    tau = routing["router"]["tau_sense"]
    return [{"entry_id": c["id"], **{k: examples[c["id"]][k] for k in ("expression", "lines", "source", "license", "note")}}
            for c in routing.get("candidates", [])
            if c.get("p_yes") is not None and c["p_yes"] >= tau and c["id"] in examples]


# 분석 작업의 실행·진행 기록·취소 상태를 관리하며 한 번에 하나의 분석만 허용한다.
class Jobs:
    # 모델과 자료 저장소를 연결하고, 작업 상태를 보호할 잠금과 작업 목록을 초기화한다.
    def __init__(self, client, cache, output_dir, lexicon=None, examples=None, store=None):
        self.client, self.cache, self.output_dir = client, cache, Path(output_dir)
        self.lexicon = lexicon or []
        self.examples = examples or {}
        self.store = store  # 자료가 바뀌면 다시 읽으므로 수집 결과를 서버 재시작 없이 반영한다.
        self.card_config = None  # 모델 처리 여건에 맞춘 카드 분석 설정. 예: {"parallel_items": 1}.
        self.retriever = None  # 실행기의 --retriever auto 옵션으로 연결하는 사전 검색기.
        # (분석 방식, 원문)을 키로 미리 계산한 카드를 저장하며, 화면에도 사전 계산 결과임을 표시한다.
        self.prepared = {}
        self.lock = threading.Lock()
        self.items, self.cancels, self.active = {}, {}, None

    # 요청을 검증해 작업 ID를 발급하고 백그라운드 분석을 시작한다. 이미 분석 중이면 거부한다.
    def create(self, body):
        card = isinstance(body, dict) and body.get("mode") in CARD_MODES
        request = card_request(body) if card else request_from(body)
        with self.lock:
            if self.active:
                raise RuntimeError("다른 분석이 실행 중입니다.")
            job_id = uuid.uuid4().hex[:16]
            self.items[job_id] = {"id": job_id, "status": "running", "events": [],
                                  "result": None, "error": None}
            self.cancels[job_id] = threading.Event()
            self.active = job_id
            if len(self.items) > 20:
                oldest = next(iter(self.items))
                self.items.pop(oldest)
                self.cancels.pop(oldest)

        # 분석기가 보낸 진행 이벤트에 시각을 붙여 해당 작업의 기록에 안전하게 추가한다.
        def emit(event):
            with self.lock:
                self.items[job_id]["events"].append({**event, "at": time.time()})

        # 최신 자료로 분석하거나 준비된 카드를 불러오고, 취소·결과 저장·실패 상태를 처리한다.
        def work():
            outcome = {}
            try:
                lexicon, usages = self.store.current() if self.store else (self.lexicon, [])
                ready = self.prepared.get((request["mode"], request["text"])) if card else None
                if ready:  # 시연용 준비 결과에는 계산 시점을 넣어 실시간 분석과 구분한다.
                    emit({"type": "prepared", **ready["prepared"]})
                    result = copy.deepcopy(ready)
                elif card:
                    runner = CardAnalyzer(self.client, emit, self.cancels[job_id], lexicon=lexicon, usages=usages,
                                          config=self.card_config, retriever=self.retriever,
                                          corpus=self.store.posts() if self.store else None)
                    result = runner.run(**request)
                else:
                    runner = Analyzer(self.client, self.cache, emit, self.cancels[job_id], lexicon=lexicon, usages=usages)
                    result = runner.run(**request)
                if self.cancels[job_id].is_set() and result["status"] in ("completed", "partial"):
                    result.update(status="cancelled", analysis=None, input_spans=[], rewrite=None, card=None,
                                  error="분석이 취소되었습니다.")
                result["examples"] = (related_examples(result, self.examples)
                                      if result["status"] == "completed" and not card else [])
                result["created_at"] = datetime.now(timezone.utc).isoformat()
                if card and not ready and self.store and result["status"] in ("completed", "partial"):
                    self.store.collect(result)  # 검수 후보 파일이 설정되어 있을 때만 새 표현을 수집한다.
                outcome.update(status=result["status"], result=result, error=result["error"])
                self.output_dir.mkdir(parents=True, exist_ok=True)
                path = self.output_dir / f"frontier-{job_id}.json"
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"id": job_id, **result}, ensure_ascii=False,
                                                allow_nan=False, indent=2), encoding="utf-8")
                temporary.replace(path)
                outcome["saved_as"] = path.name
            except Exception as exc:
                outcome.update(status="failed", error=str(exc))
            finally:
                with self.lock:
                    self.items[job_id].update(outcome)
                    self.active = None

        threading.Thread(target=work, daemon=True).start()
        return job_id

    # 작업 상태와 지정한 커서 이후의 이벤트를 복사해 반환한다. 없는 작업이면 None을 반환한다.
    def snapshot(self, job_id, after=0):
        with self.lock:
            item = self.items.get(job_id)
            if item is None:
                return None
            result = copy.deepcopy({k:v for k,v in item.items() if k != "events"})
            result.update(events=copy.deepcopy(item["events"][after:]), next_cursor=len(item["events"]))
            return result

    def interpret(self, body):
        """댓글과 선택적 팀 DB 자료를 받아 분석이 끝날 때까지 기다린 뒤 결과 카드를 반환한다.
        화면 작업과 같은 실행 잠금을 사용해 두 분석이 동시에 모델을 호출하지 않게 한다."""
        request = card_request({"mode": "card", **body})
        with self.lock:
            if self.active:
                raise RuntimeError("다른 분석이 실행 중입니다.")
            self.active = "interpret"
        try:
            lexicon, usages = self.store.current() if self.store else (self.lexicon, [])
            result = CardAnalyzer(self.client, lexicon=lexicon, usages=usages, config=self.card_config,
                                  retriever=self.retriever, corpus=self.store.posts() if self.store else None).run(**request)
            if self.store and result["status"] in ("completed", "partial"):
                self.store.collect({**result, "created_at": datetime.now(timezone.utc).isoformat()})  # 새 표현을 검수 후보로 수집한다.
            return result
        finally:
            with self.lock:
                self.active = None

    # 실행 중인 작업에 취소 신호를 보내고, 취소 요청을 접수했는지 반환한다.
    def cancel(self, job_id):
        with self.lock:
            if job_id != self.active or job_id not in self.cancels:
                return False
            self.cancels[job_id].set()
            return True


def store_summary(store):
    """화면의 DB 상태에 필요한 자료 수, 최신 근거 날짜, 수집 상태와 최근 추가 항목을 반환한다."""
    lexicon, usages = store.current()
    added = [{"kind": "뜻", "expression": e["expression"], "added_at": e["added_at"], "source": e["source"]}
             for e in lexicon if "added_at" in e]
    added += [{"kind": "용례", "expression": g["expression"], "added_at": u["added_at"], "source": u["source"]}
              for g in usages for u in g["lines"] if u["row"].startswith("live-")]
    from tracetalk.evidence.corpus import post_date
    posts = store.posts()
    dates = [d for d in map(post_date, posts.posts) if d]  # 제목에만 날짜가 있는 트렌드어워드 글도 처리한다.
    return {"lexicon_entries": len(lexicon), "usage_groups": len(usages),
            "usage_lines": sum(len(g["lines"]) for g in usages), "posts": len(posts),
            "posts_newest": max(dates) if dates else "",  # 근거 글의 최신 날짜.
            "update": store.update_state() if hasattr(store, "update_state") else None,  # 마지막 새 글 확인 상태.
            "latest": sorted(added, key=lambda a: a["added_at"], reverse=True)[:8]}


# 로컬 주소에 웹 서버를 만들고 정적 화면과 분석·검수 API를 연결한다. 요청 대기는 별도로 시작한다.
def make_server(client, cache=None, port=8765, output_dir=ROOT / "runs", lexicon=None, examples=None, store=None,
                live=None):
    jobs = Jobs(client, cache or [], output_dir, lexicon, examples, store)
    live = Path(live) if live else None  # 수집기가 기록하고 검수 화면이 사용하는 최신 자료 폴더.

    # 허용된 로컬 요청을 받아 화면 파일 또는 JSON API 응답으로 전달한다.
    class Handler(BaseHTTPRequestHandler):
        # 데이터를 UTF-8 JSON으로 보내고 캐시 금지 및 콘텐츠 유형 보호 헤더를 설정한다.
        def respond(self, data, status=200):
            raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        # 요청의 Host 헤더가 현재 포트의 localhost 또는 127.0.0.1인지 확인한다.
        def local(self):
            return self.headers.get("Host", "") in (f"localhost:{self.server.server_port}",
                                                       f"127.0.0.1:{self.server.server_port}")

        # 모델·DB·검수·작업 상태 조회를 처리하고, 등록된 HTML·JS·CSS 파일을 제공한다.
        def do_GET(self):
            if not self.local():
                return self.respond({"error": "localhost 접속만 지원합니다."}, 403)
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                health = client.health()
                with jobs.lock:
                    health["active_job"] = jobs.active
                return self.respond(health)
            if parsed.path == "/api/store":
                if not jobs.store:
                    return self.respond({"error": "DB 파일 없이 실행 중입니다."}, 404)
                try:
                    return self.respond(store_summary(jobs.store))
                except Exception as exc:  # 수동 편집한 자료에 오류가 있어도 연결을 끊지 않고 오류를 응답한다.
                    return self.respond({"error": f"DB 파일을 읽지 못했습니다: {exc}"}, 500)
            if parsed.path == "/api/review":
                if not (jobs.store and live):
                    return self.respond({"error": "검수 대기열은 DB 폴더(--live)와 함께 실행할 때만 씁니다."}, 404)
                try:
                    return self.respond(review.listing(live, jobs.store.current()[0]))
                except Exception as exc:  # 수동 편집한 자료에 오류가 있어도 연결을 끊지 않고 오류를 응답한다.
                    return self.respond({"error": f"검수 대기열을 읽지 못했습니다: {exc}"}, 500)
            if parsed.path == "/api/config":
                return self.respond({"version": VERSION, "protocol": PROTOCOL,
                                     "modes": list(MODES) + list(CARD_MODES), "model": client.config.model,
                                     "default_request": {"mode": "routed", "total_output_tokens": 2560,
                                                         "max_seconds": 120}})
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                try:
                    after = int(parse_qs(parsed.query).get("after", [0])[0])
                    if after < 0:
                        raise ValueError()
                except ValueError:
                    return self.respond({"error": "잘못된 이벤트 커서입니다."}, 400)
                item = jobs.snapshot(parts[2], after)
                return self.respond(item or {"error": "분석 작업을 찾을 수 없습니다."}, 200 if item else 404)
            routes = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                      "/styles.css": ("styles.css", "text/css"), "/workspace.css": ("workspace.css", "text/css"),
                      "/review": ("review.html", "text/html"),
                      "/review.js": ("review.js", "text/javascript")}
            if parsed.path not in routes:
                return self.respond({"error": "Not found"}, 404)
            name, mime = routes[parsed.path]
            raw = (ROOT / "tracetalk/web/static" / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)

        # 출처·본문 크기·JSON 형식을 검증한 뒤 분석 시작, 동기 해석, 검수 결정, 취소 요청을 처리한다.
        def do_POST(self):
            if not self.local():
                return self.respond({"error": "localhost 접속만 지원합니다."}, 403)
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://localhost:{self.server.server_port}",
                                          f"http://127.0.0.1:{self.server.server_port}"):
                return self.respond({"error": "다른 사이트의 분석 요청은 거부됩니다."}, 403)
            try:
                size = int(self.headers.get("Content-Length", 0))
                limit = 200000 if self.path == "/api/interpret" else 20000  # 동기 해석 요청에는 팀 DB 자료도 포함될 수 있다.
                if not 0 < size <= limit or self.headers.get_content_type() != "application/json":
                    raise ValueError(f"{limit // 1000}KB 이내 JSON 요청이 필요합니다.")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("JSON 객체가 필요합니다.")
                if self.path == "/api/analyze":
                    return self.respond({"job_id": jobs.create(body)}, 202)
                if self.path == "/api/interpret":  # 분석 완료를 기다린 뒤 카드 결과를 한 번에 반환한다.
                    return self.respond(jobs.interpret(body))
                if self.path == "/api/review":  # 사용자가 표현 하나에 대해 내린 검수 결정을 반영한다.
                    if not (jobs.store and live):
                        raise ValueError("검수 대기열은 DB 폴더(--live)와 함께 실행할 때만 씁니다.")
                    return self.respond(review.decide(live, body))
                parts = self.path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "cancel":
                    return self.respond({"cancel_requested": jobs.cancel(parts[2])})
                return self.respond({"error": "Not found"}, 404)
            except (ValueError, TypeError, UnicodeError) as exc:
                return self.respond({"error": str(exc)}, 400)
            except RuntimeError as exc:
                return self.respond({"error": str(exc)}, 409)

        # 기본 HTTP 접근 로그 출력을 생략해 분석 실행 로그만 확인하기 쉽게 한다.
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.jobs = jobs
    return server


def load_prepared(paths):
    """벤치마크 출력에서 완료·부분 완료 카드를 읽고 (분석 방식, 원문)별로 사전 계산 정보를 붙인다."""
    out = {}
    for path in map(Path, paths):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line) if line.strip() else None
            result = record and record.get("result")
            if not result or not result.get("card") or result.get("status") not in ("completed", "partial"):
                continue
            made = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="minutes")
            out[(record["method"], result["request"]["text"])] = {
                **result, "prepared": {"from": path.name, "made_at": made, "seconds_then": result["elapsed_seconds"],
                                       "model": result["model_config"]["model"], "protocol": result["protocol"]}}
    return out


# 서버에 분석 설정을 연결해 요청 처리를 시작하고, 종료 신호가 오면 작업 취소를 요청한 뒤 서버를 닫는다.
def serve(client, cache, port=8765, lexicon=None, examples=None, store=None, card_config=None, retriever=None,
          prepared=None, live=None):
    server = make_server(client, cache, port, lexicon=lexicon, examples=examples, store=store, live=live)
    server.jobs.card_config = card_config
    server.jobs.retriever = retriever
    server.jobs.prepared = prepared or {}
    print(f"TraceTalk {VERSION}: http://localhost:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        with server.jobs.lock:
            for event in server.jobs.cancels.values():
                event.set()
    finally:
        server.server_close()
