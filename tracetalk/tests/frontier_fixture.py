"""TEST-FIXTURE-NOT-A-MODEL. Protocol tests only; no semantic evaluation."""
import copy
import json
from tracetalk.model import ModelConfig


# The 0.11 card, before the agents answered each other (0.12 turned both on): tests of the 0.9-0.11 behaviour pin it.
V011 = {"debate": False, "mad_first": False}


class FixtureClient:
    def __init__(self):
        self.config = ModelConfig(model="TEST-FIXTURE-NOT-A-MODEL")
        self.requests = []
        self.hook = None
        # probe(payload) -> P(yes). Default: slang present, no lexicon sense matches.
        self.probe = lambda payload: 0.9 if payload["probe"] in ("has_slang", "easy_fit") else 0.1
        # v9 card detection: comment -> spans the "model" flags. Default: none (only DB hits are analyzed).
        self.detect = lambda text: []
        # 0.9 judge: (payload, labels) -> {label: p}. Default: the first listed reading whatever the rotation.
        self.pick = lambda payload, labels: {label: 1.0 if i == 0 else 0.0 for i, label in enumerate(labels)}
        self.pick_span = ""  # 0.9: the one part the "model" names
        self.post_meaning = "없음"  # 0.9: what the "model" reads in the passages
        self.post_origin = ""
        self.post_pick = None  # v13: the sentence number the "model" picks; default the first, or "0" when it reads nothing
        self.object_to = ""  # 0.9: what the "model" says instead of an unreviewed row; empty = it accepts the row
        self.quote_answers = []  # v16 debate: B's answers to E in turn ({stance, quote, meaning}); none left = B gives way
        self.cue_answer = None  # v16 debate: the chosen meaning's agent answering D ({stance, cue}); None = it gives way
        self.revise_answers = []  # v16 select: B's answers after E objects ({stance, meaning}); none left = B gives way

    def health(self):
        return {"connected": True, "ready": True, "model": self.config.model,
                "message": "TEST FIXTURE", "provider": "fixture"}

    def generate(self, messages, schema, seed, max_tokens):
        try:
            payload = json.loads(messages[-1]["content"])
        except ValueError:  # 0.9 pick: the comment itself
            payload = {"original_text": messages[-1]["content"]}
        self.requests.append(copy.deepcopy(payload))
        quote = payload.get("original_text", "")[:16] if isinstance(payload, dict) else ""
        props = schema["properties"]
        given = [u["id"] for u in payload.get("observed_usages", [])]
        checks = [{"id": i, "fits": "yes", "note": "테스트용 대입 결과"} for i in given[:4]]
        material = payload.get("unverified_hypotheses") or {}
        first = (material.get("db_candidates") or [{"id": "N"}])[0]["id"]
        if set(props) == {"situation", "meaning"}:  # 0.9 card: the reading with the word hidden
            data = {"situation": "테스트용 상황", "meaning": "테스트용 짐작"}
        elif set(props) == {"stance", "quote", "meaning"}:  # v16 card: B answers E with the post's own sentence
            data = self.quote_answers.pop(0) if self.quote_answers else {"stance": "withdraw", "quote": "", "meaning": ""}
        elif set(props) == {"stance", "cue"}:  # v16 card: the chosen meaning's agent answers D with a cue from the comment
            data = self.cue_answer or {"stance": "concede", "cue": ""}
        elif set(props) == {"stance", "meaning"}:  # v16 select: B, objected to, corrects the meaning or gives way
            data = self.revise_answers.pop(0) if self.revise_answers else {"stance": "withdraw", "meaning": ""}
        elif set(props) == {"span"}:  # 0.9 card: name one part
            data = {"span": self.pick_span}
        elif set(props) == {"meaning", "origin"}:  # 0.9 card: what the posts say
            data = {"meaning": self.post_meaning, "origin": self.post_origin}
        elif set(props) == {"pick", "meaning", "origin"}:  # v13 card: the sentence that explains the word, and what it says
            ids = props["pick"]["enum"]
            pick = self.post_pick or (ids[0] if self.post_meaning not in ("", "없음") else "0")
            data = {"pick": pick, "meaning": self.post_meaning, "origin": self.post_origin}
        elif set(props) == {"meaning"}:  # 0.9 card: what the stored comments have in common
            data = {"meaning": self.post_meaning}
        elif set(props) == {"choice", "meaning"}:  # 0.9 card: the row shown, can the model object
            data = {"choice": self.object_to and "N" or props["choice"]["enum"][0], "meaning": self.object_to or "테스트용 뜻풀이입니다."}
        elif set(props) == {"expressions", "note"}:  # v9 card: detection
            data = {"expressions": self.detect(payload["original_text"]), "note": "테스트용 탐지"}
        elif "candidate_checks" in props:  # v9 card: proposal
            data = {"choice": first, "meaning": "테스트용 후보 가설",
                    "candidate_checks": [{"id": c["id"], "fits": "yes" if c["id"] == first else "no", "note": "테스트"}
                                         for c in material["db_candidates"][:8]],
                    "clues": [quote], "uncertainty": "검수 필요"}
            if "usage_checks" in props:
                data["usage_checks"] = checks
        elif "peer_choice_holds" in props:  # v9 card: review
            data = {"objections": ["테스트용 반례 없음"], "peer_choice_holds": "yes",
                    "revised_choice": material["peer"]["choice"], "revised_meaning": "수정된 테스트 가설",
                    "clues": [quote], "uncertainty": "검수 필요"}
            if "peer_usage_checks" in props:
                data["peer_usage_checks"] = [{"id": i, "fits": "yes", "note": "테스트"} for i in given[:6]]
        elif "choice" in props:  # v9 card: single decision or judge
            data = {"status": "proposed", "choice": first, "meaning": "테스트용 뜻풀이입니다.", "easy": "쉬운 말",
                    "clues": [quote], "alternatives": [], "uncertainty": "의미 정확성을 검증한 응답이 아닙니다."}
            if "supporting_usages" in props:
                data["supporting_usages"] = given[:2]
        elif set(props) == {"easy"}:  # v9.3 card: easy words rewritten for the decided meaning
            data = {"easy": "고친 쉬운 말"}
        elif "sentence" in props:  # v9 card: the comment in plain words
            sentence = payload["original_text"]
            for item in material["items"]:
                if item["status"] == "proposed":
                    sentence = sentence.replace(item["expression"], item["easy"])
            data = {"sentence": sentence, **({"note": "테스트"} if "note" in props else {})}
        elif "usage_checks" in props:
            data = {"input_quotes":[quote], "decomposition":"테스트용 구성 분해", "meaning":"테스트용 용례 가설",
                    "usage_checks":checks, "assumptions":[], "uncertainty":"검수 필요"}
        elif "peer_usage_checks" in props:
            data = {"objections":["테스트용 반증 없음"], "peer_usage_checks":checks, "revised_meaning":"수정된 테스트 가설",
                    "input_quotes":[quote], "uncertainty":"검수 필요"}
        elif payload["stage"] == "final":
            data = {"status":"proposed", "expressions":[quote], "interpretation":"테스트용 의미 설명입니다.",
                    "replacements":[{"expression":quote, "easy":"테스트용 쉬운 말"}],
                    "nuance":"테스트용 뉘앙스입니다.",
                    "input_quotes":[quote], "alternatives":[], "uncertainty":"의미 정확성을 검증한 응답이 아닙니다."}
            if "supporting_usages" in props:
                data["supporting_usages"] = given[:2]
        elif payload["stage"] == "review":
            data = {"objections":["원문 밖의 사정을 가정합니다."], "unsupported_assumptions":["인물 관계"],
                    "revised_meaning":"수정된 테스트 가설", "input_quotes":[quote], "uncertainty":"검수 필요"}
        else:
            dialogue = ["A: 이것은 가상 상황입니다.", "B: 실제 용례가 아닙니다."] if schema["properties"]["synthetic_dialogue"]["maxItems"] else []
            data = {"input_quotes":[quote], "decomposition":"테스트용 구성 분해", "meaning":"테스트용 가설",
                    "assumptions":["가정된 상황"], "synthetic_dialogue":dialogue,
                    "contrast":{"text":"가상으로 바꾼 댓글", "expected_change":"해석 변화 예상"}, "uncertainty":"검수 필요"}
        if self.hook:
            self.hook(payload, data)
        return {"raw":json.dumps(data,ensure_ascii=False), "prompt_tokens":30, "completion_tokens":20,
                "finish_reason":"stop", "seconds":0.001}

    def choose(self, messages, labels, seed):
        payload = json.loads(messages[-1]["content"])
        self.requests.append(copy.deepcopy(payload))
        probs = self.pick(payload, labels)
        return {"probs": probs, "token": max(probs, key=probs.get) if probs else "", "top_logprobs": [],
                "prompt_tokens": 12, "completion_tokens": 1, "seconds": 0.001}

    def yes_no(self, messages, seed):
        payload = json.loads(messages[-1]["content"])
        self.requests.append(copy.deepcopy(payload))
        p = self.probe(payload)
        return {"p_yes": p, "token": "yes" if p is not None and p >= .5 else "no",
                "top_logprobs": [], "prompt_tokens": 12, "completion_tokens": 1, "seconds": 0.001}
