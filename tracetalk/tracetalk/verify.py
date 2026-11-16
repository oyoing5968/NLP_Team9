#!/usr/bin/env python3
"""Inspect local Ollama; optionally exercise the real TraceTalk HTTP API (6 calls).

No package installation, model download, GPU training or external model fallback.
Preflight checks connectivity only. --run-smoke checks transport and output contracts,
not whether a slang interpretation is correct. Reports never overwrite another run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from tracetalk import VERSION, PROTOCOL
from tracetalk.mad.engine import ROOT, request_from
from tracetalk.web.server import make_server
from tracetalk.model import ModelClient, ModelConfig


def hardware():
    data = {"system": platform.system(), "machine": platform.machine(),
            "os_release": platform.release(), "python_version": platform.python_version(),
            "is_macos": platform.system() == "Darwin", "cpu": platform.processor(),
            "memory_bytes": None, "project_disk_free_bytes": shutil.disk_usage(ROOT).free}
    if data["is_macos"]:
        for name, field in (("hw.memsize", "memory_bytes"), ("machdep.cpu.brand_string", "cpu")):
            try:
                value = subprocess.check_output(["sysctl", "-n", name], text=True, timeout=3).strip()
                data[field] = int(value) if field == "memory_bytes" else value
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        data["macos_version"] = platform.mac_ver()[0]
    else:
        try:
            data["memory_bytes"] = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (ValueError, OSError, AttributeError):
            pass
    data["note"] = "이 명령을 실행한 장비 정보입니다. 다른 장비의 시연 성능으로 사용하지 마세요."
    return data


def inspect_model(client):
    state = {"health": client.health(), "ollama_version": None,
             "model_metadata": None, "loaded_models": None, "inspection_errors": []}
    if not state["health"].get("connected"):
        return state
    try:
        state["ollama_version"] = client._request("/api/version", timeout=3).get("version")
    except Exception as exc:
        state["inspection_errors"].append(str(exc))
    try:
        tags = client._request("/api/tags", timeout=3).get("models", [])
        entry = next((m for m in tags if m.get("name") in client.names()), None)
        if entry:
            state["model_metadata"] = {k: entry.get(k) for k in ("name", "digest", "size", "details")}
    except Exception as exc:
        state["inspection_errors"].append(str(exc))
    try:
        state["loaded_models"] = [{k: m.get(k) for k in
                                   ("name", "digest", "size", "size_vram", "context_length")}
                                  for m in client._request("/api/ps", timeout=3).get("models", [])]
    except Exception as exc:
        state["inspection_errors"].append(str(exc))
    return state


def local_json(base, path, body=None):
    raw = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(base + path, data=raw, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=8) as response:
        return response.status, json.load(response)


def run_http_smoke(client, text, output_dir, total_output_tokens=2560, max_seconds=120):
    """Exercise real HTTP routing and the supplied adapter. Tests supply a labeled fixture backend."""
    server = make_server(client, cache=[], port=0, output_dir=output_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    results = []
    try:
        with urllib.request.urlopen(base, timeout=8) as response:
            page = response.read().decode()
            if response.status != 200 or "app.js" not in page:
                raise RuntimeError("UI 정적 페이지 응답을 확인하지 못했습니다.")
        for method, expected_calls in (("direct", 1), ("debate", 5)):
            code, created = local_json(base, "/api/analyze", {
                "text": text, "mode": method, "total_output_tokens": total_output_tokens,
                "max_seconds": max_seconds})
            if code != 202:
                raise RuntimeError("분석 시작 API가 HTTP 202를 반환하지 않았습니다.")
            path = "/api/jobs/" + created["job_id"]
            end = time.monotonic() + max_seconds + client.config.timeout + 15
            while True:
                _, state = local_json(base, path)
                if state["status"] != "running":
                    break
                if time.monotonic() >= end:
                    local_json(base, path + "/cancel", {})
                    state.update(status="observer_timeout", error="검증 프로세스의 대기 상한을 넘었습니다. 중지를 요청했습니다.")
                    break
                time.sleep(.15)
            result = state.get("result") or {}
            count = (result.get("metrics") or {}).get("call_count")
            passed = state["status"] == "completed" and count == expected_calls
            results.append({"method": method, "transport_and_schema_passed": passed,
                            "expected_model_calls": expected_calls, "actual_model_calls": count,
                            "semantic_accuracy": None, "job": state,
                            "model_state_after": inspect_model(client)})
            # Establish a working direct path before spending five calls on debate.
            if not passed:
                break
        return results
    finally:
        with server.jobs.lock:
            for event in server.jobs.cancels.values():
                event.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-smoke", action="store_true")
    parser.add_argument("--text", default="야르")
    parser.add_argument("--context-size", type=int, default=8192)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--total-output-tokens", type=int, default=2560)
    parser.add_argument("--max-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    url = urlparse(args.base_url)
    if (url.scheme != "http" or url.hostname not in ("localhost", "127.0.0.1", "::1")
            or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")):
        parser.error("tracetalk.verify는 로컬 HTTP Ollama 주소만 지원합니다.")
    if not args.model.strip() or not 4096 <= args.context_size <= 131072 or not 5 <= args.timeout <= 600:
        parser.error("model, context-size, timeout을 확인하세요.")
    try:
        request_from({"text": args.text, "total_output_tokens": args.total_output_tokens,
                      "max_seconds": args.max_seconds})
    except ValueError as exc:
        parser.error(str(exc))
    output = Path(args.output)
    jobs_dir = output.with_name(output.stem + "-jobs")
    if output.exists() or jobs_dir.exists():
        parser.error("출력 또는 작업 로그 경로가 존재합니다. 새 이름을 지정하세요.")
    client = ModelClient(ModelConfig(model=args.model, base_url=args.base_url,
                                    context_size=args.context_size, timeout=args.timeout))
    preflight = inspect_model(client)
    report = {"version": VERSION, "protocol": PROTOCOL,
              "created_at": datetime.now(timezone.utc).isoformat(), "hardware": hardware(),
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                for name in ("tracetalk/mad/engine.py", "tracetalk/mad/contracts.py", "tracetalk/model.py", "tracetalk/verify.py")},
              "preflight": preflight, "run_smoke_requested": args.run_smoke,
              "evidence_kind": "fixture_backend" if "TEST-FIXTURE" in args.model else "local_backend",
              "smoke": [], "error": None, "semantic_quality": "not_evaluated",
              "browser_visual_check": "not_performed",
              "note": "단일 입력의 실행 검증입니다. 의미 정확도·MAD 우위·일반적인 응답 속도의 증거가 아닙니다."}
    exit_code = 0 if preflight["health"].get("ready") else 2
    if args.run_smoke and exit_code == 0:
        try:
            report["smoke"] = run_http_smoke(client, args.text, jobs_dir,
                                             args.total_output_tokens, args.max_seconds)
            if len(report["smoke"]) != 2 or not all(r["transport_and_schema_passed"] for r in report["smoke"]):
                exit_code = 2
        except KeyboardInterrupt:
            report["error"] = "사용자가 검증을 중단했습니다."
            exit_code = 130
        except Exception as exc:
            report["error"] = str(exc)
            exit_code = 2
    elif args.run_smoke:
        report["error"] = "모델 연결 또는 선택한 모델 준비가 확인되지 않아 추론을 실행하지 않았습니다."
    report["exit_code"] = exit_code
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"report": str(output), "exit_code": exit_code,
                      "model_ready": bool(preflight["health"].get("ready")),
                      "smoke_conditions": len(report["smoke"]), "semantic_quality": "not_evaluated"}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
