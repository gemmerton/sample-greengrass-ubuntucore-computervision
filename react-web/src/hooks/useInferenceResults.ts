import { useState, useEffect, useCallback } from 'react';
import { useMqtt } from '../contexts/MqttContext';
import type { InferenceResult } from '../types/inference';

const INFERENCE_TOPIC = 'camera/inference';
const MAX_HISTORY = 20;

export function useInferenceResults() {
  const { state } = useMqtt();
  const [latestResult, setLatestResult] = useState<InferenceResult | null>(null);
  const [history, setHistory] = useState<InferenceResult[]>([]);

  useEffect(() => {
    if (!state.lastMessage) return;
    if (state.lastMessage.topic !== INFERENCE_TOPIC) return;

    try {
      const parsed: InferenceResult = JSON.parse(state.lastMessage.payload);
      if (parsed.result_type && parsed.results) {
        setLatestResult(parsed);
        setHistory((prev) => [parsed, ...prev].slice(0, MAX_HISTORY));
      }
    } catch {
      // Not a valid inference message
    }
  }, [state.lastMessage]);

  const clearHistory = useCallback(() => {
    setHistory([]);
    setLatestResult(null);
  }, []);

  return { latestResult, history, clearHistory };
}
