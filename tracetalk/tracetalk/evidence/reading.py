"""v13 (docs/DESIGN.md): what the posts state, read by rule, beside the 4B's reading of them.

Asked to sum up two or three passages in one sentence, the 4B wrote what the first sentence said or what the post was about
(fresh_v4, closed as a test and now development data: 15 of 47 readings wrong; 다꾸 as decorating a baseball diary, 치올 as a team's
win, 손절 read from a post about 손절미). The posts often state the meaning in a fixed form (치올(치고 올라간다), 손절미: ..., ...하는 걸
손민수라고 해); where they do, the rule reads it (stated) and the card keeps the 4B's reading only for the origin. Where every sentence
that names the word glosses a longer word or another term, the posts do not explain this word at all.

dev (84 words of fresh_v2-v4, blind judges): the 0.9 reading 61 right, 23 wrong; with the stated glosses and that check 65 right,
18 wrong (4 fixed, none broken). Numbering the sentences and letting the 4B pick one was worse (45 right): given one sentence the 4B
added to it (회크닉 '회와 크릭'). A post is data, never instructions.
"""
import re

from tracetalk.db.lexicon import compact

SPLIT = re.compile(r"(?<=[.!?…])\s+|(?<=[다요죠음함임네])\s+(?=[\"“‘'A-Za-z가-힣0-9])|\s*[\U0001F300-\U0001FAFF☀-➿️]+\s*|\s*\d️⃣\s*|\n+")
# What may follow a word in its own right: a particle or an ending (손절은, 손절하고), never more of a longer word (손절미).
PARTICLE = re.compile(r"^(?:[은는이가을를의에와과도만로]|으로|에서|에게|까지|부터|처럼|보다|이나|이란|란|이라|라|하|해|했|한|할|합|인|일|임|입|이에|예요|이야|야|들|적|스럽|러|요|죠|지|게|고|며|면|서|다|되|된|될|돼|됐|짤|챌|급|식|각|템)")


def sentences(text):
    return [s.strip(" -·|") for s in SPLIT.split(text) if s and len(s.strip()) >= 6]


def form_regex(form):
    """The word with any spaces, and the tildes of a sung or drawn-out line (L~을 가져가~), between its letters."""
    return "(?i:" + r"[\s~]*".join(re.escape(c) for c in compact(form)) + ")"  # compact() lowercases: L을 가져가 is still L


def names(sentence, forms):
    """The sentence names the word on its own: 치올(치고 올라간다) does, 손절미 does not name 손절."""
    for f in forms:
        for m in re.finditer(form_regex(f), sentence):
            rest = sentence[m.end():]
            if not rest or not re.match(r"[가-힣]", rest[:1]) or PARTICLE.match(rest):
                return True
    return False


def defines_longer(sentence, forms):
    """The sentence opens on a longer word that starts with this one ('손절미: ...' for 손절): it explains that word."""
    head = re.sub(r"^[\W\d_]+", "", sentence)
    for f in forms:
        m = re.match(form_regex(f) + r"([가-힣]+)", head)
        if m and not PARTICLE.match(m.group(1)):
            return True
    return False


def defines_other(sentence, forms):
    """The sentence glosses another term ('위쑤시개: 스트레스 받을 때 먹는 매운 음식들 엽떡, 마라탕 등'): this word is only an example there."""
    head = re.sub(r"^[\W\d_]+", "", sentence)
    m = re.match(r"([가-힣A-Za-z][가-힣A-Za-z ]{0,20}?)\s*[:：]", head)
    return bool(m) and not any(re.search(form_regex(f), m.group(1)) for f in forms)


def explains_other(forms, passages):
    """Every sentence that names the word glosses a longer word or another term (손절 in posts about 손절미)."""
    naming = [s for p in passages for s in sentences(p["text"]) if names(s, forms)]
    return bool(naming) and all(defines_longer(s, forms) or defines_other(s, forms) for s in naming)


def _abbreviates(key, inner):
    """치올 in '치고 올라간다': the word's letters, in order, in the words in brackets."""
    flat, at = compact(inner), 0
    for ch in key:
        at = flat.find(ch, at)
        if at < 0:
            return False
        at += 1
    return True


def _trim_lead(phrase):
    """'이러한 점 착안해 작년 엑스에서 엄마가 늙지 않았으면 좋겠다는 마음' -> '엄마가 늙지 않았으면 좋겠다는 마음'."""
    m = re.search(r"^.*(?:에서|착안해|보고|따라)\s+(.{8,})$", phrase)
    return m.group(1) if m else phrase


def stated(forms, passages):
    """A gloss the post writes out in a fixed form, as (meaning, sentence), or None. dev (84 words, fresh_v2-v4): 17 found, all right."""
    for p in passages:
        text = re.sub(r"\s+", " ", p["text"])
        for s in sentences(text) + [text]:
            for f in forms:
                F, key = form_regex(f), compact(f)
                # 치올(치고 올라간다), 다꾸(다이어리 꾸미기): a short word's expansion. v14: after a phrase of three words or more the
                # parenthesis is part of a title (내가 아이돌이었으면 이 파트는 꼭 하고 싶음 (직접 부름)), not a gloss
                m = re.search(F + r"\s*\(([^()]{2,40})\)", s) if len(f.split()) <= 2 else None
                # GMG(가면 감) spells out letters, it does not say what the word does: the 4B's reading of the post is kept for those
                if m and re.search(r"[가-힣]", m.group(1)) and compact(m.group(1)) != key and not re.search(r"[a-z]", key):
                    inner = m.group(1).strip(" .")
                    return (f"'{inner}'의 줄임말" if _abbreviates(key, inner) else inner), s
                m = re.search(r"(?:^|[^가-힣])" + F + r"\s*[:：]\s*([^.!?\n]{4,120})", s)  # 손절미: 손절하고 싶어지는 특징
                if m:
                    return re.split(r"\s*(?:ex\)|예\)|예시|\"|“)", m.group(1))[0].strip(" ,"), s
                m = re.search(r"^(.{6,110}?)\s*(?:걸|것을|을|를)\s*[‘'\"“]?" + F + r"[’'\"”]?\s*(?:이)?라고\s*(?:해|하|부르|불러|한다|합니다|부른다)", s)
                if m:  # ...따라하는 걸 손민수라고 하잖아
                    return m.group(1).strip(" ,") + " 것", s
                m = re.search(r"^(.{6,110}?)\s*(?:을|를)\s*[‘'\"“]" + F + r"[’'\"”]\s*(?:으)?로\s*(?:표현|부르|불러|일컫)", s)
                if m:  # ...마음을 '동결건조'로 표현하며
                    return _trim_lead(m.group(1).strip(" ,")) + "을 나타내는 말", s
                if re.search(F + r"\s*(?:으)?로\s*들리", s):  # a misheard line (이혼앤비혼)
                    orig = re.search(r"원래\s*(?:가사|대사|말)[은는이가]?\s*[‘'\"“]([^’'\"”]{2,40})[’'\"”]", text)
                    return ((f"원래 가사 '{orig.group(1)}'가 " if orig else "다른 말이 ") + f"'{key}'처럼 들리는 데서 나온 말"), s
                m = re.search(F + r"\s*(?:이)?란\s+([^.!?\n]{4,120})", s)
                if m:
                    return m.group(1).strip(" ,"), s
    return None
