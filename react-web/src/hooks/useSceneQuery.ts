import { useState, useEffect, useCallback } from 'react';
import { useMqtt } from '../contexts/MqttContext';
import { mqttService } from '../services/mqttService';
import type { VlmQueryResponse } from '../types/vlm';

const QUERY_TOPIC = 'camera/vlm-query';
const RESPONSE_TOPIC = 'camera/vlm-response';
const MAX_HISTORY = 20;

export interface QueryHistoryEntry {
  query_id: string;
  question: string;
  answer: string | null;
  timestamp: number;
  inference_time_ms: number | null;
  pending: boolean;
}

export function useSceneQuery() {
  const { state } = useMqtt();
  const [history, setHistory] = useState<QueryHistoryEntry[]>([]);
  const [pendingQueryId, setPendingQueryId] = useState<string | null>(null);

  useEffect(() => {
    if (!state.lastMessage) return;
    if (state.lastMessage.topic !== RESPONSE_TOPIC) return;

    try {
      const parsed: VlmQueryResponse = JSON.parse(state.lastMessage.payload);
      if (parsed.query_id && parsed.answer) {
        setHistory((prev) =>
          prev.map((entry) =>
            entry.query_id === parsed.query_id
              ? { ...entry, answer: parsed.answer, inference_time_ms: parsed.inference_time_ms, pending: false }
              : entry
          )
        );
        setPendingQueryId(null);
      }
    } catch {
      // Not a valid response
    }
  }, [state.lastMessage]);

  const submitQuery = useCallback(async (question: string) => {
    if (!question.trim()) return;

    const query_id = crypto.randomUUID();
    const timestamp = Date.now() / 1000;

    const entry: QueryHistoryEntry = {
      query_id,
      question,
      answer: null,
      timestamp,
      inference_time_ms: null,
      pending: true,
    };

    setHistory((prev) => [entry, ...prev].slice(0, MAX_HISTORY));
    setPendingQueryId(query_id);

    const payload = JSON.stringify({ query_id, question, timestamp });
    await mqttService.publishMessage(QUERY_TOPIC, payload);
  }, []);

  const clearHistory = useCallback(() => {
    setHistory([]);
    setPendingQueryId(null);
  }, []);

  return { history, pendingQueryId, submitQuery, clearHistory };
}
