"""fresh_v5 (docs/DESIGN.md, written before any system saw these sentences): the newest words of the trusted newsletters.

Words by the rule: the word of the day of every Trend A Word post dated 2026-10-28..11-08 and every headword of the gogumafarm meme roundups
dated 2026-09-01..11-08 in data/db/live/corpus.jsonl (fetched 2026-11-08, _crawl/new_1108), minus anything in fresh_v1-v4
(a development script, not in this repository). Two comments each, written 2026-11-08 by Claude in the style of the posts' own examples (two are the posts'
own 용례 lines); neither defines the word. Gold meanings and origins are taken from the posts. Writes inputs.jsonl, gold.jsonl, key.jsonl,
ask_alone.txt and ask_web.txt (the commercial AI's question sheets) and SHA256SUMS.
"""
import hashlib
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
TAW, GOGUMA_SEP, GOGUMA_OCT = ("https://maily.so/trendaword/posts/", "https://gogumafarm.kr/내가-고구마팜이었으면-이-밈은-꼭-소개하고-싶음-2026/",
                               "https://gogumafarm.kr/나-왜-유행-밈-소개가-영원할-거-같지-2026년-10월-최신-밈-모/")
WORDS = [
    {"word": "조우노아시 게임즈", "date": "2026-10-29", "source": TAW + "w6ovx6mpzk5",
     "meaning": "볶음밥으로 스키 타기, 오므라이스 게임처럼 기발하고 단순한 웹 게임을 잔뜩 내놓아 화제가 된 일본 게임 사이트.",
     "origin": "일본의 웹 게임 제작 사이트 조우노아시 게임즈(Zounoashi Games)", "origin_keywords": ["일본", "Zounoashi", "ゾウノアシ"],
     "sentences": [("u", "과제 해야 하는데 조우노아시 게임즈 하다가 한 시간 날림ㅋㅋ", "조우노아시 게임즈"),
                   ("u", "동생이 조우노아시 게임즈에 빠져서 저녁도 안 먹음", "조우노아시 게임즈")]},
    {"word": "산사", "date": "2026-11-02", "source": TAW + "w6ovx279zk5",
     "meaning": "개발자 '메타몽'이 10월에 만든 온라인 사찰 웹사이트. 합장·절하기·목탁 치기를 하며 마음을 식히는 곳으로 인기를 끌었다.",
     "origin": "메타몽 개발자(metamong.dev)가 만든 온라인 사찰 사이트", "origin_keywords": ["메타몽", "metamong"],
     "sentences": [("u", "팀장님한테 산사 알려주지 마", "산사"),  # the post's own 용례
                   ("u", "시험 기간이라 폰으로 산사 들어가서 목탁 백 번 침ㅋㅋ", "산사")]},
    {"word": "존박 맥도날드 랩", "date": "2026-11-05", "source": TAW + "wjzdnp6vo3p",
     "meaning": "가수 존박이 맥도날드 매장에서 랩으로 메뉴를 주문하는 영상(과 그 랩). 숏폼과 커버 영상으로 퍼졌다.",
     "origin": "유튜브 채널 '존이냐박이냐'의 '맥도날드에서 랩으로 주문하는 존박(with 로꼬)' 영상, 신메뉴 빅아치 협업",
     "origin_keywords": ["존이냐박이냐", "로꼬", "빅아치"],
     "sentences": [("u", "존박 맥도날드 랩 무한 반복 중인데 왜 내 플레이리스트에 있냐고", "존박 맥도날드 랩"),
                   ("u", "점심 메뉴 고민할 때마다 존박 맥도날드 랩이 머리에서 재생됨", "존박 맥도날드 랩")]},
    {"word": "얼데이드립", "date": "2026-11-06", "source": TAW + "wdr98q30olx",
     "meaning": "아이돌 노래를 AI로 만든 7080 스타일 가수와 뮤직비디오로 트로트처럼 다시 불러 주는 유튜브 채널.",
     "origin": "유튜브 채널 얼데이드립(아일릿 '체포하겠어' 7080 버전 등)", "origin_keywords": ["유튜브", "채널"],
     "sentences": [("u", "나는 원곡보다 얼데이드립이 말아주는 7080이 좋더라", "얼데이드립"),  # the post's own 용례
                   ("u", "얼데이드립 버전 체포하겠어 들었는데 엄빠도 좋아하심", "얼데이드립")]},
    {"word": "STORM II 패러디", "date": "2026-09-21", "source": GOGUMA_SEP,
     "meaning": "'STORM II' 뮤직비디오에서 센터의 남자만 두고 주변 학생들이 일제히 몸을 흔드는 장면을 AI 등으로 따라 만든 패러디 밈.",
     "origin": "GENER8TION과 영 린(Yung Lean)의 'STORM II' 뮤직비디오", "origin_keywords": ["GENER8TION", "영 린", "Yung Lean", "뮤직비디오"],
     "sentences": [("u", "우리 과 MT 사진으로 STORM II 패러디 만들었는데 교수님을 센터에 세움ㅋㅋ", "STORM II 패러디"),
                   ("u", "회사 단체 사진으로 STORM II 패러디 하자는 사람 누구야ㅋㅋ", "STORM II 패러디")]},
    {"word": "내가 아이돌이었으면 이 파트는 꼭 하고 싶음", "date": "2026-09-21", "source": GOGUMA_SEP,
     "meaning": "좋아하는 아이돌(배우·캐릭터) 무대에서 하고 싶은 파트만 이어 붙여 직접 부른 영상, 또는 그렇게 최애의 매력적인 순간을 골라 자랑하는 밈.",
     "origin": "엑스(X) 유저가 올린 '내가 아이돌이었으면 이 파트는 꼭 하고 싶음 (직접 부름)' 영상", "origin_keywords": ["엑스", "X", "직접 부름"],
     "sentences": [("u", "밤새서 내가 아이돌이었으면 이 파트는 꼭 하고 싶음 영상 만들었다 (직접 부름)", "내가 아이돌이었으면 이 파트는 꼭 하고 싶음"),
                   ("u", "성우 덕질 3년 차의 내가 아이돌이었으면 이 파트는 꼭 하고 싶음 버전 올라감", "내가 아이돌이었으면 이 파트는 꼭 하고 싶음")]},
    {"word": "느리구나 쓰러지는 것조차", "date": "2026-09-21", "source": GOGUMA_SEP,
     "meaning": "반응이나 행동이 한참 뒤처졌다고 놀리는(도발하는) 말.",
     "origin": "애니메이션 「블리치」의 대사", "origin_keywords": ["블리치", "BLEACH"],
     "sentences": [("u", "알림 울리자마자 들어갔는데 벌써 품절… 느리구나 쓰러지는 것조차", "느리구나 쓰러지는 것조차"),
                   ("u", "단톡방 투표 다 끝났는데 이제 들어옴? 느리구나 쓰러지는 것조차", "느리구나 쓰러지는 것조차")]},
    {"word": "구글 이모지 뒷모습", "date": "2026-10-27", "source": GOGUMA_OCT,
     "meaning": "구글이 공개한 3D 이모지의 뒷모습(엉덩이까지 정교하게 표현된 반전 이미지)이 화제가 된 밈.",
     "origin": "구글 공식 계정의 3D 이모지(Noto 3D) 뒷모습 공개", "origin_keywords": ["Noto", "3D", "공식"],
     "sentences": [("u", "구글 이모지 뒷모습 보고 웃음 참다가 실패함", "구글 이모지 뒷모습"),
                   ("u", "구글 이모지 뒷모습 이후로 이모지를 똑바로 못 보겠음", "구글 이모지 뒷모습")]},
    {"word": "OO 정보", "date": "2026-09-21", "source": GOGUMA_SEP,
     "meaning": "좋아 보이는 대상을 보고 'OO 정보'라고 써서 부러움이나 기대감을 짧게 나타내는 말(정말 정보를 달라는 뜻이 아님).",
     "origin": "SNS 게시물의 '정보 좀요' 댓글 문화", "origin_keywords": ["정보 좀요", "댓글"],
     "sentences": [("u", "저렇게 다정한 부모님이라니… 엄마 정보 아빠 정보 좀", "엄마 정보"),
                   ("u", "이 웹툰 너무 재밌다 다음 화 정보 좀", "다음 화 정보")]},
]
RULES_ALONE = """아래는 인터넷 댓글 {n}개입니다. 각 댓글에 나오는 신조어·유행어·밈 표현을 풀이해 주세요.
규칙:
- 댓글마다 한 줄로만, 이 형식으로 답하세요: 번호 | 표현 | 이 문장에서의 뜻 | 유래(어디서 나왔는지: 노래·드라마·사람·사건 이름. 모르면 모름) | 확실/추정/모름
- 신조어·밈이 없으면: 번호 | 없음 | - | - | -
- 같은 글자가 표준어 뜻 그대로 쓰였으면 뜻 칸에 '표준어'라고 쓰세요.
- 모르는 표현은 지어내지 말고 '모름'이라고 쓰세요.
- 웹 검색은 쓰지 마세요.
"""
RULES_WEB = """아래는 인터넷 댓글 {n}개입니다. 각 댓글에 나오는 신조어·유행어·밈 표현을 풀이해 주세요.
규칙:
- 웹 검색을 꼭 써서 확인하세요. 표현마다 찾아보고 답하세요.
- 댓글마다 한 줄로만, 이 형식으로 답하세요: 번호 | 표현 | 이 문장에서의 뜻 | 유래(어디서 나왔는지: 노래·드라마·사람·사건 이름. 모르면 모름) | 확실/추정/모름 | 근거 주소(실제로 읽은 페이지 하나)
- 신조어·밈이 없으면: 번호 | 없음 | - | - | - | -
- 같은 글자가 표준어 뜻 그대로 쓰였으면 뜻 칸에 '표준어'라고 쓰세요.
- 찾아도 모르는 표현은 지어내지 말고 '모름'이라고 쓰세요.
"""


def main():
    inputs, gold = [], []
    for i, w in enumerate(WORDS, 1):
        for j, (kind, text, expression) in enumerate(w["sentences"], 1):
            case = f"f5-n{i:02d}{'ab'[j - 1]}"
            inputs.append({"id": case, "text": text, "family": f"fresh5:{w['word']}", "split": "test"})
            gold.append({"case_id": case, "type": "N", "expression": expression, "headword": w["word"], "reference_meaning": w["meaning"],
                         "sense": w["meaning"], "origin": w["origin"], "origin_keywords": w["origin_keywords"], "source": w["source"],
                         "posted": w["date"], "note": "", "recent": True})
    order = list(range(len(inputs)))
    random.Random(20261108).shuffle(order)
    key = [{"no": n, "case_id": inputs[k]["id"], "type": "N", "expression": gold[k]["expression"], "gold": gold[k]["reference_meaning"],
            "text": inputs[k]["text"]} for n, k in enumerate(order, 1)]
    lines = [f"{k['no']}. {k['text']}" for k in key]
    write = lambda name, rows: (HERE / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    write("inputs.jsonl", inputs)
    write("gold.jsonl", gold)
    write("key.jsonl", key)
    (HERE / "ask_alone.txt").write_text(RULES_ALONE.format(n=len(key)) + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    (HERE / "ask_web.txt").write_text(RULES_WEB.format(n=len(key)) + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    sums = [f"{hashlib.sha256((HERE / n).read_bytes()).hexdigest()}  {n}" for n in ("inputs.jsonl", "gold.jsonl", "key.jsonl", "ask_alone.txt", "ask_web.txt")]
    (HERE / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(f"{len(inputs)}문장, {len(WORDS)}낱말 -> {HERE}")


if __name__ == "__main__":
    main()
