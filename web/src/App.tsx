import { useState, useCallback, useRef, useEffect } from "react";
import type { GameState, SetupConfig, SessionReview } from "./types";
import { api } from "./api";
import { useEventQueue } from "./hooks/useEventQueue";
import { panelState, shownState } from "./hooks/eventQueueLogic";
import SetupForm from "./components/SetupForm";
import PokerTable from "./components/PokerTable";
import ActionBar from "./components/ActionBar";
import ActionLog from "./components/ActionLog";
import { logLines } from "./components/actionLogLogic";
import HandResult from "./components/HandResult";
import HintPanel from "./components/HintPanel";
import { gtoFetchState, type GtoFetchResult } from "./components/gtoPanelLogic";
import { sessionSummaryText, shouldFetchReview } from "./reviewLogic";
import { readSkipMode, storeSkipMode, shouldAutoSkip, autoNextActive } from "./autoAdvance";
import {
  readStoredSessionId, storeSessionId, clearStoredSessionId, isSessionGone,
  SESSION_EXPIRED_MESSAGE,
} from "./sessionStore";

const HINT_STORAGE_KEY = "ev_plus_hint_enabled";

// 힌트 켜짐 여부는 localStorage — 브라우저 설정(사이트 데이터 차단 등)에 따라 접근이 예외를 던질 수 있다
function readHintEnabled(): boolean {
  try {
    return localStorage.getItem(HINT_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function storeHintEnabled(v: boolean): void {
  try {
    localStorage.setItem(HINT_STORAGE_KEY, String(v));
  } catch {
    // 저장 실패는 무시(다음 방문에 기본값)
  }
}

export default function App() {
  const [state, setState] = useState<GameState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 서버가 세션을 모름(404: 서버 재시작·오래돼 정리됨) — 액션 잠금 + "세션 만료 — 새 게임" 안내
  const [sessionExpired, setSessionExpired] = useState(false);
  // 설정 화면 안내(새로고침했는데 이전 세션이 사라진 경우)
  const [setupNotice, setSetupNotice] = useState<string | null>(null);
  // 새로고침 후 이어하기(ADR 0043): 보관된 세션이 있으면 첫 화면에서 서버에 확인하는 중
  const [restoring, setRestoring] = useState<boolean>(() => readStoredSessionId() !== null);
  const restoreTried = useRef(false);
  const [myCardsRevealed, setMyCardsRevealed] = useState(false);
  const [rightTab, setRightTab] = useState<"log" | "hint">("log");
  const [gtoResult, setGtoResult] = useState<GtoFetchResult | null>(null);
  const [hintEnabled, setHintEnabled] = useState<boolean>(readHintEnabled);
  // 스킵 모드(⏭): 폴드한 핸드는 재생 없이 바로 결과, 결과 창은 5초 뒤 자동 다음 핸드
  const [skipMode, setSkipMode] = useState<boolean>(readSkipMode);
  const [sessionReview, setSessionReview] = useState<SessionReview | null>(null);

  const prevHandNumber = useRef<number>(0);

  const {
    isReplaying,
    display,
    activePlayer,
    isThinking,
    badge,
    bettingPlayer,
    enqueue,
    skip,
    reset: resetReplay,
  } = useEventQueue();

  // 재생 직전의 상태 — 재생 중 힌트 패널(에퀴티·GTO)·액션 바·헤더 핸드 번호는 이 값을 유지한다.
  // 새 값(아직 안 깔린 카드가 반영된 에퀴티 등)은 재생이 끝난 뒤에만 보인다.
  const [replayBase, setReplayBase] = useState<GameState | null>(null);

  // 서버 응답을 받아 이벤트 큐를 세팅하는 공통 처리
  const applyNewState = useCallback(
    (next: GameState) => {
      const isNewHand = next.hand_number !== prevHandNumber.current;
      prevHandNumber.current = next.hand_number;
      if (isNewHand) setMyCardsRevealed(false); // 새 핸드: 카드 숨김 초기화

      setReplayBase(state);
      setState(next);
      storeSessionId(next.session_id);
      // 재생 시작점 = 요청 직전 상태(state). 새 핸드면 블라인드 전부터.
      // 스킵 모드에서 사람이 폴드한 핸드는 남은 이벤트를 즉시 소비해 결과 창을 바로 띄운다.
      enqueue(next.events, state, next, isNewHand, shouldAutoSkip(skipMode, next));
    },
    [state, enqueue, skipMode]
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

  // GTO 레인지 페치 — 게임 상태의 gto.node_key(advisor 추천이 쓴 노드)가 바뀔 때마다.
  // 힌트(내 패 빈도)와 레인지가 같은 노드에서 온다. UTG RFI 노드 키는 ""이므로 null과 구분한다.
  // 재생 중엔 재생 직전 상태의 노드를 유지한다 — 새 노드 조회는 재생이 끝난 뒤.
  // 결과는 요청한 노드 키와 함께 둔다: 지금 노드의 결과가 없으면 로딩, 실패면 "조회 실패"(gtoFetchState)
  const panelSource = state ? panelState(isReplaying, replayBase, state) : null;
  const gtoNodeKey = panelSource?.gto?.found ? (panelSource.gto.node_key ?? null) : null;
  useEffect(() => {
    if (gtoNodeKey === null) return;
    let cancelled = false;
    api.getGtoRange(gtoNodeKey)
      .then(r => { if (!cancelled) setGtoResult({ key: gtoNodeKey, range: r }); })
      .catch(() => { if (!cancelled) setGtoResult({ key: gtoNodeKey, range: null }); });
    return () => { cancelled = true; };
  }, [gtoNodeKey]);
  const gtoFetch = gtoFetchState(gtoNodeKey, gtoResult);

  // 핸드가 끝나고 그 재생도 끝난 뒤 세션 평가 요약 페치 — 헤더가 결과보다 먼저 바뀌지 않게
  const fetchReview = shouldFetchReview(isReplaying, state);
  useEffect(() => {
    if (!fetchReview || !state?.session_id) return;
    let cancelled = false;
    api.getSessionReview(state.session_id)
      .then(r => { if (!cancelled) setSessionReview(r); })
      .catch(() => { if (!cancelled) setSessionReview(null); });
    return () => { cancelled = true; };
  }, [fetchReview, state?.hand_number, state?.session_id]);

  const toggleHint = () => {
    setHintEnabled((v) => {
      const next = !v;
      storeHintEnabled(next);
      return next;
    });
  };

  const toggleSkipMode = () => {
    const next = !skipMode;
    setSkipMode(next);
    storeSkipMode(next);
    // 폴드한 핸드의 재생 중에 켜면 그 자리에서 남은 재생을 건너뛴다
    if (next && isReplaying && state && shouldAutoSkip(true, state)) skip();
  };

  const handleStart    = (config: SetupConfig) => run(() => api.startGame(config));
  const handleAction   = (action: string, amount = 0) => {
    if (!state) return;
    run(() => api.submitAction(state.session_id, action, amount));
  };
  const handleNextHand = () => { if (!state) return; run(() => api.nextHand(state.session_id)); };
  const handleNewGame  = () => {
    resetReplay();
    setReplayBase(null);
    setState(null);
    setMyCardsRevealed(false);
    setError(null);
    setSessionExpired(false);
    setSetupNotice(null);
    setSessionReview(null);          // 새 게임 헤더에 이전 게임 요약이 남지 않게
    prevHandNumber.current = 0;      // 새 게임 첫 핸드도 "새 핸드"로 처리
    clearStoredSessionId();
  };

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

  // 지금 화면에 보일 상태 하나: 재생 중이면 "이전 상태 + 소비한 이벤트", 아니면 서버 최종 상태
  const shown = shownState(isReplaying, display, state);
  const panel = panelState(isReplaying, replayBase, state);
  const human = shown.players.find((p) => p.is_human);

  // 액션 버튼: 재생 중·로딩 중·세션 만료면 비활성
  const actionDisabled = isReplaying || loading || sessionExpired;

  return (
    <div className="min-h-screen lg:h-screen lg:overflow-hidden bg-gray-950 flex flex-col lg:flex-row">
      {/* 메인 게임 영역 */}
      <div className="flex-1 flex flex-col min-h-0">
        {/* 헤더 */}
        <div className="bg-gray-900 border-b border-gray-700 px-4 py-2 flex items-center justify-between shrink-0">
          <h1 className="text-white font-bold text-sm">♠ Texas Hold'em</h1>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-gray-400">핸드 #{panel.hand_number}</span>
            <span className="text-yellow-400 font-bold">
              {human?.name}: {(human?.chips ?? 0).toLocaleString()} 칩
            </span>
            {sessionReview && (
              <span className="text-gray-400 text-xs">{sessionSummaryText(sessionReview)}</span>
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
            <button
              onClick={toggleSkipMode}
              aria-pressed={skipMode}
              title={"스킵 모드: 폴드한 핸드는 바로 결과, 결과 창은 5초 뒤 자동으로 다음 핸드(마우스를 올리면 멈춤)"}
              className={`text-xs border rounded px-2 py-0.5 transition-colors ${
                skipMode
                  ? "text-sky-300 border-sky-600 bg-sky-900/30"
                  : "text-gray-500 border-gray-600"
              }`}
            >
              ⏭ 자동
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
        <div className="flex-1 min-h-0 flex justify-center p-4 relative lg:overflow-y-auto">
          <div className="w-full max-w-3xl relative my-auto">
            <PokerTable
              state={shown}
              activePlayer={activePlayer}
              isThinking={isThinking}
              badge={badge}
              bettingPlayer={bettingPlayer}
              isReplaying={isReplaying}
              cardsDealt={(name) => (isReplaying && display ? (display.seats[name]?.dealt ?? 0) : 2)}
              myCardsRevealed={myCardsRevealed}
              onRevealCards={() => setMyCardsRevealed((v) => !v)}
              showdownRevealed={!isReplaying || !!display?.showdownRevealed}
              committedAction={(name) => display?.seats[name]?.committed ?? undefined}
            />
            {state.hand_over && !isReplaying && (
              <HandResult
                state={state}
                onNextHand={handleNextHand}
                onNewGame={handleNewGame}
                loading={loading || sessionExpired}
                autoNext={autoNextActive({
                  skipMode, gameOver: state.game_over, loading, sessionExpired, hasError: !!error,
                })}
              />
            )}
          </div>
        </div>

        {/* 액션 바 — 항상 표시, 내 차례 아닐 때 disabled */}
        {!state.game_over && (
          <div className="shrink-0">
            <ActionBar
              state={panel}
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
      <div className="lg:w-72 shrink-0 min-h-0 flex flex-col border-t lg:border-t-0 lg:border-l border-gray-800">
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
              {t === "hint" && hintEnabled && panel.gto && (
                <span className="ml-1 text-[10px]">
                  {panel.gto.found && gtoFetch.status === "ok" && gtoFetch.range.found ? "🟢" : "🔴"}
                </span>
              )}
            </button>
          ))}
        </div>
        {/* 탭 컨텐츠 */}
        <div className="flex-1 min-h-0 overflow-hidden">
          {rightTab === "log" ? (
            <div className="p-3 h-full flex flex-col">
              <ActionLog lines={logLines(shown)} />
            </div>
          ) : hintEnabled ? (
            // ① 상황 ② GTO 빈도 ③ 내 패 ④ 에퀴티 — 넘치면 패널 안에서만 스크롤
            <div className="h-full overflow-y-auto">
              <HintPanel
                gto={panel.gto}
                fetch={gtoFetch}
                equity={panel.equity}
                callAmount={panel.call_amount}
                isMyTurn={state.waiting_for_action && !isReplaying}
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
