import { useState, useEffect, useCallback } from 'react';
import { useMqtt } from '../contexts/MqttContext';
import type { VlmResult, VlmAlert } from '../types/vlm';

const VLM_TOPIC = 'camera/vlm';
const MAX_HISTORY = 20;

export function useVlmResults() {
  const { state } = useMqtt();
  const [latestResult, setLatestResult] = useState<VlmResult | null>(null);
  const [history, setHistory] = useState<VlmResult[]>([]);

  useEffect(() => {
    if (!state.lastMessage) return;
    if (state.lastMessage.topic !== VLM_TOPIC) return;

    try {
      const parsed: VlmResult = JSON.parse(state.lastMessage.payload);
      if (parsed.timestamp && (parsed.response || parsed.raw_output)) {
        setLatestResult(parsed);
        setHistory((prev) => [parsed, ...prev].slice(0, MAX_HISTORY));
      }
    } catch {
      // Not a valid VLM message
    }
  }, [state.lastMessage]);

  const clearHistory = useCallback(() => {
    setHistory([]);
    setLatestResult(null);
  }, []);

  const latestAlerts: VlmAlert[] = latestResult?.response?.alerts ?? [];
  const latestTimestamp: number | null = latestResult?.timestamp ?? null;

  return { latestResult, history, clearHistory, latestAlerts, latestTimestamp };
}
