"""T-029 vitest 픽스처 생성: 실제 WebGameSession 응답(이전 상태, 다음 상태+이벤트)을 JSON으로 저장.
실행: python3 tests/make_replay_fixture.py  (web/src/hooks/__tests__/fixtures/replay_session.json 갱신)
임시 DB 사용(tests/test_poker_full 임포트가 EV_PLUS_DB를 격리). 이벤트 페이로드를 바꾸면 다시 생성한다."""
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "src", "hooks", "__tests__", "fixtures", "replay_session.json")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_poker_full as T  # noqa: E402  (StubBot 패치 + 임시 DB)
from core.game import Action  # noqa: E402

random.seed(29)
# 4인: 사람=UTG(dealer_index=1 → Alpha BTN, Beta SB, Gamma BB, Human UTG)
sess, _ = T._scripted_session(3, dealer_index=1, scripts={
    "🤖 Beta": [(Action.CALL, 20), (Action.RAISE, 60)],
})
prev_fold = sess.get_state()
next_fold = sess.get_state(sess.submit_action("fold", 0))
assert next_fold["hand_over"], "폴드 후 봇들이 끝까지 진행해야 함"

prev_new = next_fold
next_new = sess.get_state(sess.next_hand())

out = {
    "fold_to_showdown": {"prev": prev_fold, "next": next_fold},
    "new_hand": {"prev": prev_new, "next": next_new},
}
with open(sys.argv[1] if len(sys.argv) > 1 else OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("ok", len(next_fold["events"]), len(next_new["events"]))
