import React, { useState, useEffect } from 'react';
import type { VlmAlert } from '../../types/vlm';
import './AlertBanner.css';

interface AlertBannerProps {
  alerts: VlmAlert[];
  timestamp: number | null;
}

interface AlertHistoryEntry {
  alert: VlmAlert;
  timestamp: number;
  id: string;
}

const MAX_ALERT_HISTORY = 20;
const TOAST_DURATION_MS = 5000;

export const AlertBanner: React.FC<AlertBannerProps> = ({ alerts, timestamp }) => {
  const [alertHistory, setAlertHistory] = useState<AlertHistoryEntry[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [toastAlerts, setToastAlerts] = useState<VlmAlert[]>([]);

  useEffect(() => {
    if (!alerts || alerts.length === 0 || !timestamp) return;

    const triggered = alerts.filter((a) => a.triggered);
    if (triggered.length === 0) return;

    const newEntries: AlertHistoryEntry[] = triggered.map((alert, i) => ({
      alert,
      timestamp,
      id: `${timestamp}-${i}`,
    }));

    setAlertHistory((prev) => [...newEntries, ...prev].slice(0, MAX_ALERT_HISTORY));
    setToastAlerts(triggered);

    const timer = setTimeout(() => setToastAlerts([]), TOAST_DURATION_MS);
    return () => clearTimeout(timer);
  }, [alerts, timestamp]);

  return (
    <>
      {toastAlerts.length > 0 && (
        <div className="alert-toast">
          <span className="alert-toast__icon">&#9888;</span>
          <div className="alert-toast__content">
            {toastAlerts.map((alert, i) => (
              <div key={i} className="alert-toast__item">
                <span className="alert-toast__rule">{alert.rule}</span>
                <span className="alert-toast__detail">{alert.detail}</span>
              </div>
            ))}
          </div>
          <button
            className="alert-toast__dismiss"
            onClick={() => setToastAlerts([])}
            type="button"
            aria-label="Dismiss"
          >
            &times;
          </button>
        </div>
      )}

      {alertHistory.length > 0 && (
        <button
          className="alert-history-fab"
          onClick={() => setHistoryOpen(!historyOpen)}
          type="button"
          aria-label="Alert history"
        >
          <span className="alert-history-fab__icon">&#9888;</span>
          <span className="alert-history-fab__count">{alertHistory.length}</span>
        </button>
      )}

      {historyOpen && (
        <div className="alert-history-panel">
          <div className="alert-history-panel__header">
            <h4 className="alert-history-panel__title">Alert History</h4>
            <button
              className="alert-history-panel__close"
              onClick={() => setHistoryOpen(false)}
              type="button"
              aria-label="Close"
            >
              &times;
            </button>
          </div>
          <ul className="alert-history-panel__list">
            {alertHistory.map((entry) => (
              <li key={entry.id} className="alert-history-panel__item">
                <span className="alert-history-panel__time">
                  {new Date(entry.timestamp * 1000).toLocaleTimeString()}
                </span>
                <span className="alert-history-panel__rule">{entry.alert.rule}</span>
                <span className="alert-history-panel__detail">{entry.alert.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
};
