import { useCallback, useEffect, useRef, useState } from "react";
import { fetchChatHistory, type ChatHistory } from "./chat";

type HistoryState = {
  scope: string;
  history: ChatHistory | null;
  reading: boolean;
  failed: boolean;
};

export type ConversationHistoryStatus = Pick<ReturnType<typeof useConversationHistory>, "phase" | "reading" | "sendBlocked" | "retry">;

/** Read recovery shared by steward and Goal conversations; never executes a Turn. */
export function useConversationHistory({ agentId, currentAgentId, channelId, goalId, enabled }: {
  agentId?: string;
  currentAgentId: string;
  channelId: string;
  goalId?: string;
  enabled: boolean;
}) {
  const scope = JSON.stringify([agentId ?? null, currentAgentId, channelId, goalId ?? null]);
  const [state, setState] = useState<HistoryState | null>(null);
  const retryRead = useRef<(() => void) | null>(null);
  const retry = useCallback(() => retryRead.current?.(), []);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let reading = false;
    let history: ChatHistory | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    async function read() {
      if (cancelled || reading) return;
      clearTimeout(retryTimer);
      reading = true;
      setState({ scope, history, reading: true, failed: false });
      try {
        const loaded = await fetchChatHistory({ agentId, channelId, goalId }, history ?? undefined);
        if (cancelled) return;
        history = loaded;
        setState({ scope, history, reading: false, failed: false });
      } catch {
        if (cancelled) return;
        setState({ scope, history, reading: false, failed: true });
      } finally {
        reading = false;
        if (!cancelled && (!history || history.unavailableSessionIds.length > 0)) {
          // Back off sustained transport failures; a user can retry immediately.
          retryTimer = setTimeout(() => void read(), Math.min(3000 * 2 ** attempts++, 30_000));
        }
      }
    }
    retryRead.current = () => void read();
    void read();
    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      retryRead.current = null;
    };
  }, [agentId, channelId, goalId, enabled, scope]);
  const current = enabled && state?.scope === scope ? state : null;
  const history = current?.history ?? null;
  // A channel transcript spans executors; readability of another executor's
  // latest session cannot authorize sending into the selected one.
  const latest = history?.sessions.find((session) => session.agent_id === currentAgentId);
  const currentSessionReadable = history !== null && (!latest || history.snapshots.some((snapshot) => snapshot.session.session_id === latest.session_id));
  return {
    history,
    currentSession: latest,
    phase: !enabled ? "ready" as const : !current ? "loading" as const
      : current.failed ? "unavailable" as const
      : history?.unavailableSessionIds.length ? (history.snapshots.length ? "partial" as const : "unavailable" as const)
      : current.reading ? "loading" as const : "ready" as const,
    reading: current?.reading ?? enabled,
    sendBlocked: enabled && !currentSessionReadable,
    // Missing older history must not restart a recovered current stream.
    connectionKey: currentSessionReadable ? `${scope}:${latest?.session_id ?? "empty"}` : null,
    retry,
  };
}
