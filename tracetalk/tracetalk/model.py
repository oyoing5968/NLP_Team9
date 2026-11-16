"""Model adapters, the model command-line options and the cancel signal (from the 0.1 packages,
unchanged). No synthetic response fallback is provided."""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelConfig:
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:1.7b"
    timeout: int = 180
    temperature: float = 0.35
    context_size: int = 8192
    model_path: str = ""
    threads: int = 4
    api_key_env: str = ""
    omit_sampling: bool = False
    completion_parameter: str = "max_tokens"
    reasoning_effort: str = ""


class ModelClient:
    def __init__(self, config: ModelConfig):
        self.config = config

    def _request(self, path, payload=None, timeout=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key_env:
            key = os.environ.get(self.config.api_key_env)
            if not key:
                raise ModelError(f"환경 변수 {self.config.api_key_env}에 API 키가 없습니다.")
            headers["Authorization"] = "Bearer " + key
        base = self.config.base_url.rstrip("/")
        if base.endswith("/v1") and path.startswith("/v1/"):
            path = path[3:]
        request = urllib.request.Request(base + path, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.config.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            # Do not persist arbitrary upstream errors that might echo secrets.
            raise ModelError(f"모델 서버 HTTP {exc.code}: 엔드포인트·모델·지원 파라미터를 확인하세요.") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise ModelError(f"모델 서버 연결/응답 오류: {exc}") from exc

    def names(self):
        """Spellings the server may list for the configured model.

        Ollama lists a model created without a tag as NAME:latest and serves it under either
        spelling (11-01 roundtrip: "tt-roundtrip" was reported missing while it answered).
        """
        names = {self.config.model}
        if self.config.provider == "ollama" and ":" not in self.config.model.rsplit("/", 1)[-1]:
            names.add(self.config.model + ":latest")
        return names

    def health(self):
        path = "/api/tags" if self.config.provider == "ollama" else "/v1/models"
        try:
            data = self._request(path, timeout=3)
            if self.config.provider == "ollama":
                models = [m.get("name", "") for m in data.get("models", [])]
            else:
                models = [m.get("id", "") for m in data.get("data", [])]
            ready = bool(self.names() & set(models))
            return {"connected": True, "ready": ready, "models": models,
                    "model": self.config.model, "provider": self.config.provider,
                    "message": "모델 준비 완료" if ready else "설정한 모델이 서버에 없습니다."}
        except ModelError as exc:
            return {"connected": False, "ready": False, "models": [],
                    "model": self.config.model, "provider": self.config.provider,
                    "message": str(exc)}

    def generate(self, messages, schema, seed, max_tokens):
        start = time.perf_counter()
        if self.config.provider == "ollama":
            data = self._request("/api/chat", {
                "model": self.config.model, "messages": messages,
                "format": schema, "stream": False, "think": False, "keep_alive": "10m",
                "options": {"temperature": self.config.temperature, "seed": seed,
                            "num_predict": max_tokens, "num_ctx": self.config.context_size},
            })
            raw = data.get("message", {}).get("content", "")
            prompt_tokens, completion_tokens = data.get("prompt_eval_count"), data.get("eval_count")
            finish_reason = data.get("done_reason", "unknown")
        else:
            payload = {
                "model": self.config.model, "messages": messages,
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "interpretation", "strict": True, "schema": schema}},
                self.config.completion_parameter: max_tokens, "stream": False,
            }
            if not self.config.omit_sampling:
                payload.update(temperature=self.config.temperature, seed=seed)
            if self.config.api_key_env:
                if self.config.reasoning_effort:
                    payload["reasoning_effort"] = self.config.reasoning_effort
            else:
                payload["chat_template_kwargs"] = {"enable_thinking": False}
            data = self._request("/v1/chat/completions", payload)
            choice = (data.get("choices") or [{}])[0]
            raw = choice.get("message", {}).get("content", "")
            usage = data.get("usage", {})
            prompt_tokens, completion_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
            finish_reason = choice.get("finish_reason", "unknown")
        return {"raw": raw, "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "ollama_timings_ns": ({key: data.get(key) for key in
                    ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")}
                    if self.config.provider == "ollama" else None),
                "returned_model": data.get("model"),
                "system_fingerprint": data.get("system_fingerprint"),
                "reasoning_tokens": ((data.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens"),
                "seconds": round(time.perf_counter() - start, 3),
                "finish_reason": finish_reason}


    def _one_token(self, messages, seed):
        """One token with its top probabilities: (token, top_logprobs, prompt_tokens, completion_tokens)."""
        if self.config.provider == "ollama":
            data = self._request("/api/chat", {
                "model": self.config.model, "messages": messages, "stream": False, "think": False,
                "logprobs": True, "top_logprobs": 10, "keep_alive": "10m",
                "options": {"temperature": 0, "seed": seed, "num_predict": 1,
                            "num_ctx": self.config.context_size},
            })
            positions = data.get("logprobs") or []
            top = (positions[0].get("top_logprobs") or []) if positions else []
            return (data.get("message", {}).get("content", ""), top,
                    data.get("prompt_eval_count"), data.get("eval_count"))
        payload = {"model": self.config.model, "messages": messages, "stream": False,
                   self.config.completion_parameter: 1, "logprobs": True, "top_logprobs": 10,
                   "temperature": 0, "seed": seed}
        if not self.config.api_key_env:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        data = self._request("/v1/chat/completions", payload)
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("logprobs") or {}).get("content") or []
        usage = data.get("usage", {})
        return (choice.get("message", {}).get("content", ""), (content[0].get("top_logprobs") or []) if content else [],
                usage.get("prompt_tokens"), usage.get("completion_tokens"))

    def yes_no(self, messages, seed):
        """One-token yes/no answer with token probabilities. Returns p_yes or None if unreadable."""
        start = time.perf_counter()
        token, top, prompt_tokens, completion_tokens = self._one_token(messages, seed)
        return {"p_yes": yes_probability(top, token), "token": token,
                "top_logprobs": [{"token": t.get("token"), "logprob": t.get("logprob")} for t in top],
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                "seconds": round(time.perf_counter() - start, 3)}

    def choose(self, messages, labels, seed):
        """0.9: a one-token answer among labels ("1", "2", ...): {probs: {label: p} over the labels (None if unreadable), ...}"""
        start = time.perf_counter()
        token, top, prompt_tokens, completion_tokens = self._one_token(messages, seed)
        return {"probs": label_probabilities(top, labels, token), "token": token,
                "top_logprobs": [{"token": t.get("token"), "logprob": t.get("logprob")} for t in top],
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                "seconds": round(time.perf_counter() - start, 3)}


YES = {"yes", "y", "예", "네"}
NO = {"no", "n", "아니오", "아니", "아니요"}


def yes_probability(top, token=""):
    """Normalize P(yes) over yes/no tokens; fall back to the emitted token; None if neither."""
    yes = no = 0.0
    for item in top:
        word = str(item.get("token", "")).strip().lower()
        prob = math.exp(item["logprob"]) if isinstance(item.get("logprob"), (int, float)) else 0.0
        if word in YES:
            yes += prob
        elif word in NO:
            no += prob
    if yes + no > 0:
        return round(yes / (yes + no), 4)
    word = str(token).strip().lower()
    return 1.0 if word in YES else 0.0 if word in NO else None


def label_probabilities(top, labels, token=""):
    """Normalize the top tokens' probabilities over the labels; the emitted token alone when none is listed; else None."""
    mass = {label: 0.0 for label in labels}
    for item in top:
        word = str(item.get("token", "")).strip()
        if word in mass and isinstance(item.get("logprob"), (int, float)):
            mass[word] += math.exp(item["logprob"])
    total = sum(mass.values())
    if total > 0:
        return {label: round(value / total, 4) for label, value in mass.items()}
    word = str(token).strip()
    return {label: 1.0 if label == word else 0.0 for label in labels} if word in mass else None


class NativeLlamaClient:
    """Optional direct GGUF execution; used for the included CPU smoke run."""
    def __init__(self, config: ModelConfig):
        from llama_cpp import Llama
        self.config = config
        self.llm = Llama(model_path=config.model_path, n_ctx=config.context_size,
                         n_threads=config.threads, n_batch=512, n_gpu_layers=0,
                         chat_format="chatml", verbose=False)

    def health(self):
        return {"connected": True, "ready": True, "models": [self.config.model],
                "model": self.config.model, "provider": "llama-cpp",
                "message": "GGUF CPU 모델 준비 완료"}

    def generate(self, messages, schema, seed, max_tokens):
        start = time.perf_counter()
        data = self.llm.create_chat_completion(
            messages=messages, response_format={"type": "json_object", "schema": schema},
            temperature=self.config.temperature, seed=seed, max_tokens=max_tokens,
        )
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return {"raw": choice["message"].get("content", ""),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "finish_reason": choice.get("finish_reason", "unknown"),
                "seconds": round(time.perf_counter() - start, 3)}


def make_client(config):
    return NativeLlamaClient(config) if config.provider == "llama-cpp" else ModelClient(config)


def parse_decision(raw: str, choices: list[str], evidence_ids: set[str]):
    """Validate model output without inventing an answer or a missing citation."""
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned).strip()
    data = json.loads(cleaned)
    if not isinstance(data, dict) or data.get("choice") not in choices:
        raise ValueError("유효한 의미 후보를 선택하지 않았습니다.")
    for key in ["interpretation", "reason"]:
        if not isinstance(data.get(key), str) or len(data[key]) > 1500:
            raise ValueError(f"잘못된 {key} 필드")
    citations = data.get("evidence_ids")
    if not isinstance(citations, list) or not all(isinstance(x, str) for x in citations):
        raise ValueError("잘못된 evidence_ids 필드")
    invalid = [x for x in citations if x not in evidence_ids]
    data["evidence_ids"] = list(dict.fromkeys(x for x in citations if x in evidence_ids))
    data["invalid_evidence_ids"] = invalid
    data["valid"] = True
    return data


class Cancelled(RuntimeError):
    pass


def add_model_arguments(p):
    p.add_argument("--provider", choices=["ollama", "openai", "llama-cpp"], default="ollama")
    p.add_argument("--base-url", default="http://127.0.0.1:11434")
    p.add_argument("--model", default="qwen3:1.7b")
    p.add_argument("--model-path", default="")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--context-size", type=int, default=16384)
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--api-key-env", default="", help="Environment variable name, never the API secret")
    p.add_argument("--omit-sampling", action="store_true")
    p.add_argument("--completion-parameter", choices=["max_tokens", "max_completion_tokens"], default="max_tokens")
    p.add_argument("--reasoning-effort", default="")
    p.add_argument("--temperature", type=float, default=0.35)
    return p


def config_from(args):
    url = urlparse(args.base_url)
    if url.scheme not in ["http", "https"] or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("인증 정보와 쿼리가 없는 HTTP(S) base URL이 필요합니다.")
    if not 1 <= args.threads <= 64 or not 4096 <= args.context_size <= 131072 or not 5 <= args.timeout <= 600:
        raise ValueError("threads, context-size 또는 timeout 범위를 확인하세요.")
    temperature = getattr(args, "temperature", 0.35)
    if not 0 <= temperature <= 2:
        raise ValueError("temperature는 0~2 범위입니다.")
    return ModelConfig(provider=args.provider, base_url=args.base_url, model=args.model,
        model_path=args.model_path, threads=args.threads, context_size=args.context_size,
        timeout=args.timeout, api_key_env=args.api_key_env, omit_sampling=args.omit_sampling,
        completion_parameter=args.completion_parameter, reasoning_effort=args.reasoning_effort,
        temperature=temperature)
