"""TraceTalk: a Korean neologism and meme interpreter (detect, find evidence, MAD, easy wording)."""

VERSION = "0.13.0"
# v4 (10-31): the final answer names replacements (expression -> easy words in the same form) instead of a
# formal rewrite; the system rewrites the comment in place (team slide: "쟤 방금 '발끈한' 거 같은데?").
# v3 (easy_expression, kit 1031) was never run.
# v5 (10-31 night): interpretation opens with a formal one-sentence definition; replacements are standard-language
# paraphrases (no other slang), not the comment's own register. v4 (kit 1031b) was never run.
# v6 (11-01): a quote wrapped in quote marks or differing only in spaces is matched to the comment and stored as
# the comment's own text (contracts.cite). v5 baseline = runs/pilot/*_t2560.jsonl (11-01 pilot, 262 misses).
# v7 (11-01 evening): observed usages as evidence (usage_mad, usage_direct, routed dictionary -> usages -> plain -> MAD);
# the system prompt now names observed_usages as observations next to the comment. v6 was never run beyond the pilot.
# v8 (11-01 night): no usage probe (literal usage match goes straight to usage MAD when no dictionary entry passes);
# a quote with punctuation outside its quote marks is matched after stripping it. v7 = runs/pilot_v7/*_1714 (baseline).
# v9 (11-03): the team's result card (tracetalk/mad/card.py, modes card / card_single): every expression in the comment,
# candidate-comparison MAD (DB senses + literal + none; usages split between proposers), a checked plain-language
# sentence, Korean-only outputs asked again once. Methods direct..usage_mad are unchanged from v8. v8 =
# runs/r2, r4 (11-03 main run) and runs/pilot_v7/*_1101_1827.
# v9.1 (11-03, after the pilot runs/v9/pilot): a longer DB word the probes doubt is decided (dropped only when read
# literally); easy words checked (not the expression again, short, not the rest of the comment; retry keeps the
# decision and blanks them); notes are internal (stripped, not fatal); the sentence step gets explicit replacements;
# a one-letter leftover counts when nothing Korean precedes it. v9 = runs/v9/pilot (11-03 09:44).
# v9.2 (11-03, after runs/v9.1/pilot and pilot_base): internal outputs (detection, proposals, reviews) are stripped of
# Han/kana instead of failing; the retry tells the model what was wrong; easy words must not repeat the expression
# (system prompt example); copying three or more comment words into easy words is the limit (two can be fair).
# v9.3 (11-03, after the v9.2 main run runs/v9.2/main): easy words probed against the decided meaning and rewritten
# once when they do not carry it; a model-only span may be read as a standard word (dropped) and spans over four words
# are skipped; when the model keeps an expression twice the system swaps just those words (card.sentence_by);
# K2 picks no longer need easy words.
# v9.4 (11-03, after the Mac demo run): the literal option means the dictionary sense as such (a standard word used as
# a figure or meme is not L; 동결건조 was dropped); easy words may not hold a one-letter expression anywhere (각 ->
# '시각') or another expression of the same comment (마기꾼 -> '마스크빨이 큰 사람'); the has_slang probe is optional.
# v9.5 (11-04, after the v9.4 main run runs/v9.4/main and the teacher run runs/v9.4/teacher_val): DB senses may carry
# easy words a teacher drafted from the DB meaning alone (separate file, eval/draft_easy.py; marked on the card; the
# team's own easy words win); the sentence step is told to conjugate a dictionary-form easy word and the system no
# longer swaps one into an inflected slot; items say whether their meaning is an estimate (no DB sense).
# v9.6 (11-04 afternoon, after the v9.5 gate runs/v9.5/gate_reg: registered end to end 20/34, below its bar 22): a guess
# with no evidence (no DB sense, no usages) stays as written in the plain-language sentence and shows on the card only
# (card.kept_estimates; the sentence step gets it as `keep`, and replacing it is a sentence problem); the teacher's
# easy-word drafts see DB example lines and may end in '-다' only for '-다' words (eval/draft_easy.py,
# data/db/lexicon/easy_draft_v2.jsonl).
# v10 (11-05, after fresh_v1; docs/DESIGN.md): a DB sense nobody has reviewed goes to MAD even when the probe calls
# it a fit (gate), a word the DB lacks is judged by MAD (new word, standard word, not known), the judge role is
# chosen on the development picks, the debate is kept for the card, and the cards feed the collector
# (tracetalk/db/update.py queue). The 0.7 card is the same code with gate=probe, unknown=guess, judge=v9, oov off.
# v12 (11-07, after fresh_v3 and the commercial comparison; docs/DESIGN.md): a DB word is decided by one token over every
# rotation of the labels plus, between senses, a reading with the word hidden; what is not clear enough says 뜻 확인 필요; a
# word the DB lacks gets a reading, not a debate; detection names one part when the comment reads like slang; DB words keep
# their place at the cap and the card lists what it skipped. The 0.8 card is the same code with decide=roles, unknown=mad.
# v13 (11-08, after fresh_v4; docs/DESIGN.md): a gloss the post states in a fixed form is the meaning and is quoted on the card
# (tracetalk/evidence/reading.py), else the 0.9 summary of the posts (picking a sentence was tried and dropped); a post's headword in the
# comment is a candidate; the standard reading drops a word only at tau_literal 0.7, else 뜻 확인 필요; a stated gloss that another
# meaning outweighs is shown to check; a row matched by assuming a typo is not settled; a sense left to check shows its DB easy
# words and their sentence as "이 뜻이 맞다면" (easy_if, sentence_if). 0.10.0 = the code frozen for fresh_v5 (dev runs: 0.10.0-dev).
# The 0.9 card is the same code with post_read=summary, headwords off, tau_literal 0.
# v14 (11-09, after the fresh_v5 test; dev only until the next test): a word's own one-word post is read even when its body does not
# repeat the word word for word; a parenthesis after a phrase of three words or more is part of a title, not a gloss; the rule that skips
# posts naming a DB neighbour does not apply to a post's own headword; a DB word starting inside a post's headword gives way to it.
# v15 (11-10, dev only until the next test): a post's sentence presenting the word as its topic is read though another sentence says 활용
# (3일팅); a post with no date takes its heading's (Trend A Word, 위픽레터); easy words cut out of the expression are sent back (존박 맥도날드 랩
# -> '맥도날드 랩'); 반대 근거, a fourth witness: the meaning about to be shown against the words taken as they are (card.CARD "contrast").
# v16 (11-10, 0.12; docs/DESIGN.md 토론·MAD 우선): the agents answer each other (E chooses the posts' sentence backing B's reading, B
# corrects or gives way, a reading E cannot back is shown to check; D's objection is answered with a cue or given in to); B and C for
# every word; with no evidence C reads the sentence. A heading line that itself glosses the word stays in the passage (두쫀쿠).
# v17 (11-10, 0.12.1): C makes no guess when the comment holds almost nothing besides the word (card.CARD "min_context": 쮀쮀이야).
# No dev card changes (runs/tmp/v16/thin_context.py); the data folder is split into data/db and data/eval.
# v18 (11-11, 0.13.0): one word typed alone is a lookup (오디세이): a DB word read literally is shown to check instead of dropped,
# and a word nothing found is asked about instead of passed over as "no slang" (card.bare_word); dev 216 + 18: one comment
# changes (f4-r09). Automatic updating, off by default: mac/start.sh --auto-update fetches the allowed newsletters' new posts at
# the start, every N hours and soon after a word the card could not settle (data/db/live/update_wanted); the word goes nowhere.
PROTOCOL = "single-comment-20261111-v18"
