import { useState, useCallback, useRef, useEffect } from "react";
import type { GameState, SetupConfig, GtoRange, SessionReview } from "./types";
import { api } from "./api";
import { useEventQueue } from "./hooks/useEventQueue";
import SetupForm from "./components/SetupForm";
import PokerTable from "./components/PokerTable";
import ActionBar from "./components/ActionBar";
import ActionLog from "./components/ActionLog";
import HandResult from "./components/HandResult";
import GtoPanel from "./components/GtoPanel";
import EquityPanel from "./components/EquityPanel";
import {
  readStoredSessionId, storeSessionId, clearStoredSessionId, isSessionGone,
  SESSION_EXPIRED_MESSAGE,
} from "./sessionStore";

const HINT_STORAGE_KEY = "ev_plus_hint_enabled";

export default function App() {
  const [state, setState] = useState<GameState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 서버가 세션을 모름(404: 서버 재시작·오래돼 정리됨) — 액션 잠금 + "세션 만료 — 새 게임" 안내 (T-028)
  const [sessionExpired, setSessionExpired] = useState(false);
  // 설정 화면 안내(새로고침했는데 이전 세션이 사라진 경우)
  const [setupNotice, setSetupNotice] = useState<string | null>(null);
  // 새로고침 후 이어하기(ADR 0043): 보관된 세션이 있으면 첫 화면에서 서버에 확인하는 중
  const [restoring, setRestoring] = useState<boolean>(() => readStoredSessionId() !== null);
  const restoreTried = useRef(false);
  const [myCardsRevealed, setMyCardsRevealed] = useState(false);
  const [rightTab, setRightTab] = useState<"log" | "hint">("log");
  const [gtoRange, setGtoRange] = useState<GtoRange | null>(null);
  const [gtoLoading, setGtoLoading] = useState(false);
  const [hintEnabled, setHintEnabled] = useState<boolean>(
    () => localStorage.getItem(HINT_STORAGE_KEY) === "true"
  );
  const [sessionReview, setSessionReview] = useState<SessionReview | null>(null);

  const prevHandNumber = useRef<number>(0);

  const {
    isReplaying,
    activePlayer,
    isThinking,
    badge,
    visibleCardCount,
    visibleLogCount,
    foldedDuringReplay,
    bettingPlayer,
    dealtCards,
    showdownRevealed,
    displayedChips,
    committedActions,
    enqueue,
    skip,
    setVisibleCardCount,
  } = useEventQueue();

  // 서버 응답을 받아 이벤트 큐를 세팅하는 공통 처리
  const applyNewState = useCallback(
    (next: GameState) => {
      const isNewHand = next.hand_number !== prevHandNumber.current;
      prevHandNumber.current = next.hand_number;
      if (isNewHand) setMyCardsRevealed(false); // 새 핸드: 카드 숨김 초기화

      // 새 핸드: 커뮤니티 카드 0부터 시작
      // 이어지는 액션: 이전 표시 카드 수부터 시작
      const initialCardCount = isNewHand ? 0 : (state?.community_cards.length ?? 0);
      const initialFolded    = isNewHand ? [] : (state?.players.filter((p) => p.is_folded).map((p) => p.name) ?? []);
      const initialLogCount  = isNewHand ? 0 : (state?.action_log.length ?? 0);
      // 새 핸드: 블라인드가 이미 반영된 next.players 에서 chips+current_bet 으로 역산
      // → SB: 990+10=1000, BB: 980+20=1000 (블라인드 포스팅 전 값)
      // 기존 핸드: 직전 상태의 chips (이번 액션 전 값)
      const initialChips = isNewHand
        ? Object.fromEntries(next.players.map((p) => [p.name, p.chips + p.current_bet]))
        : Object.fromEntries((state?.players ?? next.players).map((p) => [p.name, p.chips]));

      setState(next);
      storeSessionId(next.session_id);

      if (next.events.length > 0) {
        enqueue(next.events, initialCardCount, initialFolded, initialLogCount, isNewHand, initialChips);
      } else {
        setVisibleCardCount(next.community_cards.length);
      }
    },
    [state, enqueue, setVisibleCardCount]
  );

  const run = useCallback(
    async (fn: () => Promise<GameState>) => {
      setLoading(true);
      setError(null);
      try {
        const next = await fn();
        applyNewState(next);
      } catch (e) {
        if (isSessionGone(e)) {
          setSessionExpired(true);
          clearStoredSessionId();
        } else {
          setError(e instanceof Error ? e.message : "오류가 발생했습니다.");
        }
      } finally {
        setLoading(false);
      }
    },
    [applyNewState]
  );

  // 새로고침·탭 다시 열기: 보관된 세션이 서버에 살아 있으면 이어간다(ADR 0043).
  // 없으면(404) 설정 화면에 "세션 만료 — 새 게임" 안내. 마운트 시 1회만.
  useEffect(() => {
    if (restoreTried.current) return;
    restoreTried.current = true;
    const id = readStoredSessionId();
    if (!id) return;
    api.getState(id)
      .then((next) => applyNewState(next))
      .catch((e) => {
        clearStoredSessionId();
        if (isSessionGone(e)) setSetupNotice(`${SESSION_EXPIRED_MESSAGE} — 이전 게임을 이어갈 수 없습니다.`);
        else setError(e instanceof Error ? e.message : "오류가 발생했습니다.");
      })
      .finally(() => setRestoring(false));
    // 첫 렌더(state=null)의 applyNewState로 충분하다 — 의도적으로 마운트 1회만 실행
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // GTO 레인지 페치 — 게임 상태의 gto.node_key(advisor 추천이 쓴 노드)가 바뀔 때마다(T-013).
  // 힌트(내 패 빈도)와 레인지가 같은 노드에서 온다. UTG RFI 노드 키는 ""이므로 null과 구분한다.
  const gtoNodeKey = state?.gto?.found ? (state.gto.node_key ?? null) : null;
  useEffect(() => {
    if (gtoNodeKey === null) return;

    let cancelled = false;
    // 요청 시작을 알리는 로딩 플래그 — 표준 데이터 페칭 idiom(react.dev 공식 예제와 동일
    // 형태)이라 여기서는 억제한다. .then/.catch/.finally 안의 setState는 이 규칙 대상이 아니다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setGtoLoading(true);
    api.getGtoRange(gtoNodeKey)
      .then(r => { if (!cancelled) setGtoRange(r); })
      .catch(() => { if (!cancelled) setGtoRange(null); })
      .finally(() => { if (!cancelled) setGtoLoading(false); });

    return () => { cancelled = true; };
  }, [gtoNodeKey]);

  // 지금 노드의 레인지만 쓴다 — 노드가 없거나(포스트플랍·데이터 없음) 아직 이전 노드의 응답이면 무시
  const effectiveGtoRange =
    gtoNodeKey !== null && gtoRange?.action_seq === gtoNodeKey ? gtoRange : null;

  // 핸드 종료 시마다 세션 평가 요약 페치
  useEffect(() => {
    if (!state?.hand_over || !state.session_id) return;
    let cancelled = false;
    api.getSessionReview(state.session_id)
      .then(r => { if (!cancelled) setSessionReview(r); })
      .catch(() => { if (!cancelled) setSessionReview(null); });
    return () => { cancelled = true; };
  }, [state?.hand_over, state?.hand_number, state?.session_id]);

  const toggleHint = () => {
    setHintEnabled((v) => {
      const next = !v;
      localStorage.setItem(HINT_STORAGE_KEY, String(next));
      return next;
    });
  };

  const handleStart    = (config: SetupConfig) => run(() => api.startGame(config));
  const handleAction   = (action: string, amount = 0) => {
    if (!state) return;
    run(() => api.submitAction(state.session_id, action, amount));
  };
  const handleNextHand = () => { if (!state) return; run(() => api.nextHand(state.session_id)); };
  const handleNewGame  = () => {
    skip();
    setState(null);
    setMyCardsRevealed(false);
    setError(null);
    setSessionExpired(false);
    setSetupNotice(null);
    setSessionReview(null);          // 새 게임 헤더에 이전 게임 요약이 남지 않게 (T-028)
    prevHandNumber.current = 0;      // 새 게임 첫 핸드도 "새 핸드"로 처리
    clearStoredSessionId();
  };

  // 홀카드 → GTO 핸드 표기 변환
  function toGtoHand(cards: string[] | null): string | null {
    if (!cards || cards.length < 2) return null;
    const RANK_VAL: Record<string, number> = {
      A:14,K:13,Q:12,J:11,"10":10,T:10,"9":9,"8":8,"7":7,"6":6,"5":5,"4":4,"3":3,"2":2
    };
    const GTO_RANK: Record<string, string> = {
      A:"A",K:"K",Q:"Q",J:"J","10":"T","9":"9","8":"8","7":"7","6":"6","5":"5","4":"4","3":"3","2":"2"
    };
    const SUITS = ["♠","♥","♦","♣"];
    const parse = (c: string) => {
      const suit = SUITS.find(s => c.endsWith(s)) ?? "";
      const rank = c.slice(0, -1);
      return { rank, suit, val: RANK_VAL[rank] ?? 0, gto: GTO_RANK[rank] ?? rank };
    };
    const [c1, c2] = [parse(cards[0]), parse(cards[1])];
    const [hi, lo] = c1.val >= c2.val ? [c1, c2] : [c2, c1];
    if (hi.rank === lo.rank) return hi.gto + lo.gto;
    return hi.gto + lo.gto + (hi.suit === lo.suit ? "s" : "o");
  }

  if (!state) {
    if (restoring) {
      return (
        <div className="min-h-screen bg-gray-900 flex items-center justify-center text-gray-400 text-sm">
          진행 중인 게임을 불러오는 중…
        </div>
      );
    }
    return (
      <SetupForm onStart={handleStart} error={error} loading={loading} notice={setupNotice} />
    );
  }

  const human = state.players.find((p) => p.is_human);

  // 액션 버튼: 재생 중·로딩 중·세션 만료면 비활성
  const actionDisabled = isReplaying || loading || sessionExpired;

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col lg:flex-row">
      {/* 메인 게임 영역 */}
      <div className="flex-1 flex flex-col min-h-0">
        {/* 헤더 */}
        <div className="bg-gray-900 border-b border-gray-700 px-4 py-2 flex items-center justify-between shrink-0">
          <h1 className="text-white font-bold text-sm">♠ Texas Hold'em</h1>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-gray-400">핸드 #{state.hand_number}</span>
            <span className="text-yellow-400 font-bold">
              {human?.name}: {(isReplaying && human ? (displayedChips.get(human.name) ?? human.chips) : human?.chips ?? 0).toLocaleString()} 칩
            </span>
            {sessionReview && (
              <span className="text-gray-400 text-xs">
                GTO {sessionReview.gto_match_rate != null ? `${(sessionReview.gto_match_rate * 100).toFixed(0)}%` : "—"}
                {" · "}
                EV {sessionReview.total_ev_loss_bb >= 0 ? "+" : ""}
                {sessionReview.total_ev_loss_bb.toFixed(1)}bb
              </span>
            )}
            <button
              onClick={toggleHint}
              className={`text-xs border rounded px-2 py-0.5 transition-colors ${
                hintEnabled
                  ? "text-green-400 border-green-600 bg-green-900/30"
                  : "text-gray-500 border-gray-600"
              }`}
            >
              힌트 👁
            </button>
            {isReplaying && (
              <button
                onClick={skip}
                className="text-xs text-gray-400 hover:text-white border border-gray-600 rounded px-2 py-0.5"
              >
                스킵 ⏩
              </button>
            )}
            <button
              onClick={handleNewGame}
              className="text-xs text-gray-500 hover:text-gray-300"
            >
              새 게임
            </button>
          </div>
        </div>

        {/* 테이블 */}
        <div className="flex-1 flex items-center justify-center p-4 relative">
          <div className="w-full max-w-3xl relative">
            <PokerTable
              state={state}
              activePlayer={activePlayer}
              isThinking={isThinking}
              badge={badge}
              visibleCardCount={visibleCardCount}
              foldedDuringReplay={foldedDuringReplay}
              bettingPlayer={bettingPlayer}
              isReplaying={isReplaying}
              dealtCards={dealtCards}
              myCardsRevealed={myCardsRevealed}
              onRevealCards={() => setMyCardsRevealed((v) => !v)}
              showdownRevealed={showdownRevealed}
              displayedChips={displayedChips}
              committedActions={committedActions}
            />
            {state.hand_over && !isReplaying && (
              <HandResult
                state={state}
                onNextHand={handleNextHand}
                onNewGame={handleNewGame}
                loading={loading || sessionExpired}
              />
            )}
          </div>
        </div>

        {/* 액션 바 — 항상 표시, 내 차례 아닐 때 disabled */}
        {!state.game_over && (
          <div className="shrink-0">
            <ActionBar
              state={state}
              onAction={handleAction}
              loading={loading}
              disabled={actionDisabled || !state.waiting_for_action || state.hand_over}
            />
          </div>
        )}

        {/* 세션 만료 — 서버가 세션을 모름(재시작·정리). 액션은 잠기고 새 게임만 가능 */}
        {sessionExpired && (
          <div
            role="alert"
            className="shrink-0 bg-amber-900/80 text-amber-200 text-sm flex items-center justify-center gap-3 py-2 px-4"
          >
            <span>{SESSION_EXPIRED_MESSAGE}: 서버에서 이 게임을 찾을 수 없습니다.</span>
            <button
              onClick={handleNewGame}
              className="rounded border border-amber-500 px-2 py-0.5 text-xs font-medium hover:bg-amber-800"
            >
              새 게임
            </button>
          </div>
        )}

        {/* 에러 */}
        {error && (
          <div className="shrink-0 bg-red-900/80 text-red-300 text-sm text-center py-2 px-4">
            {error}
          </div>
        )}
      </div>

      {/* 사이드패널 — 로그 / 힌트 탭 */}
      <div className="lg:w-72 shrink-0 flex flex-col border-t lg:border-t-0 lg:border-l border-gray-800">
        {/* 탭 헤더 */}
        <div className="flex border-b border-gray-700 shrink-0">
          {(["log", "hint"] as const).map(t => (
            <button
              key={t}
              onClick={() => setRightTab(t)}
              className={`flex-1 py-2 text-xs font-medium transition-colors ${
                rightTab === t
                  ? "text-white border-b-2 border-green-500 bg-gray-900"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {t === "log" ? "📋 로그" : "💡 힌트"}
              {t === "hint" && hintEnabled && state.gto && (
                <span className="ml-1 text-[10px]">
                  {state.gto.found && effectiveGtoRange?.found ? "🟢" : "🔴"}
                </span>
              )}
            </button>
          ))}
        </div>
        {/* 탭 컨텐츠 */}
        <div className="flex-1 overflow-hidden">
          {rightTab === "log" ? (
            <div className="p-3 h-full">
              <ActionLog
                log={isReplaying
                  ? state.action_log.slice(0, visibleLogCount)
                  : state.action_log}
              />
            </div>
          ) : hintEnabled ? (
            <div className="h-full overflow-y-auto">
              {/* 에퀴티 */}
              <div className="border-b border-gray-800">
                <div className="px-3 pt-2 text-xs font-medium text-gray-400">📈 에퀴티</div>
                <EquityPanel
                  equity={state.equity}
                  callAmount={state.call_amount}
                  isMyTurn={state.waiting_for_action && !isReplaying}
                />
              </div>
              {/* GTO */}
              <GtoPanel
                gto={state.gto}
                gtoRange={effectiveGtoRange}
                myHand={toGtoHand(
                  state.players.find(p => p.is_human)?.hole_cards ?? null
                )}
                isLoading={gtoLoading}
              />
            </div>
          ) : (
            <div className="flex items-center justify-center h-32 text-gray-600 text-sm text-center px-4">
              힌트가 꺼져 있습니다 — 헤더의 👁 버튼으로 켜세요
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
