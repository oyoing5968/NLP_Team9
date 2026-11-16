"""Input-only benchmark loading and execution-quality reporting; no automatic gold labels."""
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import median

from tracetalk.mad.engine import METHODS, request_from


def read_inputs(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    seen, families = set(), {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "text", "family", "split"}:
            raise ValueError("입력 파일에는 id, text, family, split만 허용합니다. 정답은 별도 파일에 보관하세요.")
        if any(not isinstance(row[k], str) or not row[k].strip() for k in row):
            raise ValueError("모든 입력 필드는 비어 있지 않은 문자열이어야 합니다.")
        request_from({"text": row["text"]})
        if row["id"] in seen:
            raise ValueError("중복 사례 id입니다.")
        seen.add(row["id"])
        if row["split"] not in ("train", "validation", "test", "diagnostic"):
            raise ValueError("잘못된 split입니다.")
        if row["family"] in families and families[row["family"]] != row["split"]:
            raise ValueError("같은 표현 계열이 여러 split에 걸쳐 있습니다.")
        families[row["family"]] = row["split"]
    if not rows:
        raise ValueError("평가 입력이 없습니다.")
    return rows


def record_for(case, seed, method, result):
    return {"case_id": case["id"], "family": case["family"], "split": case["split"],
            "seed": seed, "method": method,
            "input_sha256": hashlib.sha256(case["text"].encode("utf-8")).hexdigest(),
            "status": result["status"], "result": result}


def summarize(rows):
    groups, identities, seen = defaultdict(list), {}, set()
    for row in rows:
        result = row["result"]
        model = result["model_config"]["model"]
        identity = (row["input_sha256"], row["family"], row["split"])
        if row["case_id"] in identities and identities[row["case_id"]] != identity:
            raise ValueError("같은 사례 id에 다른 입력 또는 분할 정보가 있습니다.")
        identities[row["case_id"]] = identity
        setup = {"model_config":result["model_config"], "protocol":result["protocol"],
                 "total_output_tokens":result["request"]["total_output_tokens"],
                 "max_seconds":result["request"]["max_seconds"]}
        config_hash = hashlib.sha256(json.dumps(setup, sort_keys=True).encode()).hexdigest()[:12]
        key = f"{model}/{config_hash}/{row['method']}"
        repeat = (key, row["case_id"], row["seed"])
        if repeat in seen:
            raise ValueError("동일 조건·사례·seed의 중복 결과입니다.")
        seen.add(repeat)
        groups[key].append(row)
    report = {}
    for key, group in groups.items():
        times = sorted(row["result"]["elapsed_seconds"] for row in group)
        valid = [row for row in group if row["status"] == "completed"]
        proposed = [row for row in valid if row["result"]["analysis"]["status"] == "proposed"]
        report[key] = {
            "attempts": len(group), "completed": len(valid),
            "failure_rate": 1 - len(valid)/len(group),
            "proposal_coverage": len(proposed)/len(group),
            "latency_median_seconds": median(times),
            "latency_p95_seconds": times[max(0, math.ceil(len(times)*.95)-1)],
            "latency_note": "실패 포함 관측 지연; 소규모 pilot의 p95를 일반화하지 마세요.",
            "total_model_calls": sum(row["result"]["metrics"]["call_count"] for row in group),
            "invalid_calls": sum(row["result"]["metrics"]["invalid_calls"] for row in group),
            "semantic_accuracy": None,
            "semantic_note": "독립 검수 정답과 블라인드 채점이 필요합니다. 구조 성공률은 정확도가 아닙니다.",
        }
        for token_kind in ("prompt_tokens", "completion_tokens"):
            values = [row["result"]["metrics"][token_kind] for row in group]
            report[key][token_kind] = sum(values) if all(type(v) is int for v in values) else None
    return report
