"""Small, dependency-free JSON contract and original-text citation validation."""
import json


def string(limit=500):
    return {"type": "string", "maxLength": limit}


def array(item, maximum, minimum=0):
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}


def obj(**fields):
    return {"type": "object", "properties": fields,
            "required": list(fields), "additionalProperties": False}


def proposal_schema(dialogue=True):
    return obj(
        input_quotes=array(string(120), 3, 1),
        decomposition=string(300), meaning=string(300),
        assumptions=array(string(160), 3),
        synthetic_dialogue=array(string(160), 4 if dialogue else 0, 2 if dialogue else 0),
        contrast=obj(text=string(300), expected_change=string(200)),
        uncertainty=string(200),
    )


REVIEW_SCHEMA = obj(
    objections=array(string(200), 3, 1),
    unsupported_assumptions=array(string(160), 3),
    revised_meaning=string(300),
    input_quotes=array(string(120), 3, 1), uncertainty=string(200),
)

# v4: the model names each expression and the easy words that fit in its place; the system writes the
# rewritten comment itself, so the rest of the original text can never change.
REPLACEMENT = obj(expression=string(120), easy=string(120))

FINAL_SCHEMA = obj(
    status={"type": "string", "enum": ["proposed", "uncertain"]},
    expressions=array(string(300), 3),
    interpretation=string(400), replacements=array(REPLACEMENT, 3), nuance=string(200),
    input_quotes=array(string(120), 4), alternatives=array(string(250), 2),
    uncertainty=string(250),
)


# v7 usage MAD: observed usages are cited by their number (U1, U2, ...), never quoted as free text.
FIT = {"type": "string", "enum": ["yes", "no", "unclear"]}
USAGE_CHECK = obj(id=string(8), fits=FIT, note=string(160))
USAGE_PROPOSAL_SCHEMA = obj(
    input_quotes=array(string(120), 3, 1),
    decomposition=string(300), meaning=string(300),
    usage_checks=array(USAGE_CHECK, 4, 1),
    assumptions=array(string(160), 3), uncertainty=string(200),
)
USAGE_REVIEW_SCHEMA = obj(
    objections=array(string(200), 3, 1),
    peer_usage_checks=array(USAGE_CHECK, 6, 1),
    revised_meaning=string(300),
    input_quotes=array(string(120), 3, 1), uncertainty=string(200),
)
FINAL_USAGE_SCHEMA = obj(**FINAL_SCHEMA["properties"], supporting_usages=array(string(8), 4))


def usage_ids(analysis):
    """Every usage number an output cites, so the engine can check it was actually given."""
    checks = analysis.get("usage_checks", []) + analysis.get("peer_usage_checks", [])
    return [c["id"] for c in checks] + list(analysis.get("supporting_usages", []))


def validate(value, schema, path="response"):
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict) or set(value) != set(schema["properties"]):
            raise ValueError(f"{path}: 필드가 누락되었거나 추가되었습니다.")
        for key, child in schema["properties"].items():
            validate(value[key], child, f"{path}.{key}")
    elif kind == "array":
        if not isinstance(value, list) or not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise ValueError(f"{path}: 배열 길이가 규격과 다릅니다.")
        for item in value:
            validate(item, schema["items"], path + "[]")
    elif kind == "string":
        if not isinstance(value, str) or len(value) > schema.get("maxLength", 1000):
            raise ValueError(f"{path}: 문자열 형식 또는 길이를 확인하세요.")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path}: 허용되지 않은 값입니다.")


MARKS = " \t\n'\"‘’“”「」『』"
PUNCT = MARKS + ",.!?~…;:"  # second try only; the result must still occur in the comment as written


def cite(text, quote):
    """The exact original substring a quote points at, or None.

    v6: the model often wraps a quote in quote marks ('"ㄱ-"') or adds a space the comment does not
    have ("4 번" for "4번", "도는 줄" for "도는줄"). Those are matched to the original and replaced by
    its own text. A quote that drops a space the comment has does not match ("가방" is not "가 방"),
    and any other difference (a base form, a dropped syllable, a word from synthetic dialogue or the
    dictionary candidates) still fails: the stored quote is always a real part of the comment.
    """
    if quote.strip() and quote in text:
        return quote
    bare = quote.strip(MARKS)
    if not bare:
        return None
    if bare in text:
        return bare
    if quote.strip(PUNCT) and quote.strip(PUNCT) in text:  # '"와 대박 축하드려요!", ' (11-01 v7 pilot)
        return quote.strip(PUNCT)
    for start in (i for i, ch in enumerate(text) if ch == bare[0]):
        i, j = 0, start
        while i < len(bare) and j < len(text):
            if bare[i] == text[j]:
                i, j = i + 1, j + 1
            elif bare[i].isspace():
                i += 1
            else:
                break
        if i == len(bare):
            return text[start:j]
    return None


def canonical(text, quotes):
    cited = [cite(text, quote) for quote in quotes]
    if None in cited:
        raise ValueError("인용은 원문에 실제로 존재해야 합니다. 합성 대화는 근거가 아닙니다.")
    return cited


def quote_spans(text, quotes):
    spans = []
    for quote in quotes:
        if not quote.strip() or quote not in text:
            raise ValueError("인용은 원문에 실제로 존재해야 합니다. 합성 대화는 근거가 아닙니다.")
        start = 0
        while True:
            pos = text.find(quote, start)
            if pos < 0:
                break
            spans.append({"source": "input", "quote": quote, "start": pos, "end": pos + len(quote)})
            start = pos + len(quote)
    return spans


def parse(raw, schema, text):
    if not isinstance(raw, str):
        raise ValueError("모델이 문자열 JSON을 반환하지 않았습니다.")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("JSON에 중복 키가 있습니다.")
            result[key] = value
        return result
    data = json.loads(raw, object_pairs_hook=unique)
    validate(data, schema)
    for field in ("input_quotes", "expressions"):
        if field in data:
            data[field] = canonical(text, data[field])
    # A replacement that still names no part of the comment is skipped by rewrite(), not failed here.
    for item in data.get("replacements", []):
        item["expression"] = cite(text, item["expression"]) or item["expression"]
    for field in ("meaning", "revised_meaning", "decomposition", "interpretation"):
        if field in data and not data[field].strip():
            raise ValueError(f"{field}: 내용이 비어 있습니다.")
    if "status" in data:
        if data["status"] == "uncertain" and not data["uncertainty"].strip():
            raise ValueError("유보 상태는 불확실성을 설명해야 합니다.")
        if data["status"] == "proposed" and not data["input_quotes"]:
            raise ValueError("해석 제안에는 원문 인용이 필요합니다.")
        if data["status"] == "proposed" and data.get("supporting_usages") == []:
            raise ValueError("용례 근거 해석 제안에는 근거 용례 번호가 필요합니다.")
    return data


def rewrite(text, analysis):
    """Put each replacement's easy words where its expression stands in the original comment.

    Only a proposed answer is rewritten. A replacement whose expression is not in the comment, whose
    easy words are empty, or that overlaps an earlier one is skipped and reported, not guessed.
    Positions are code-point indices: start/end in the original, new_start/new_end in the result.
    """
    if not analysis or analysis.get("status") != "proposed":
        return {"text": None, "spans": [], "skipped": []}
    taken, skipped = [], []
    for item in analysis.get("replacements", []):
        expression, easy = item["expression"], item["easy"].strip()
        if not expression.strip() or expression not in text or not easy:
            skipped.append({**item, "reason": "원문에 없는 표현" if expression not in text or not expression.strip()
                            else "쉬운 말이 비어 있음"})
            continue
        found, pos = False, text.find(expression)
        while pos >= 0:
            end = pos + len(expression)
            if all(end <= s or pos >= e for s, e, _, _ in taken):
                taken.append((pos, end, expression, easy))
                found = True
            pos = text.find(expression, end)
        if not found:
            skipped.append({**item, "reason": "앞 치환과 겹침"})
    if not taken:
        return {"text": None, "spans": [], "skipped": skipped}
    out, spans, cursor = [], [], 0
    for start, end, expression, easy in sorted(taken):
        out.append(text[cursor:start])
        new_start = sum(map(len, out))
        out.append(easy)
        spans.append({"expression": expression, "easy": easy, "start": start, "end": end,
                      "new_start": new_start, "new_end": new_start + len(easy)})
        cursor = end
    out.append(text[cursor:])
    return {"text": "".join(out), "spans": spans, "skipped": skipped}
