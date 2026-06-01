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

export const AlertBanner: React.FC<AlertBannerProps> = ({ alerts, timestamp }) => {
  const [alertHistory, setAlertHistory] = useState<AlertHistoryEntry[]>([]);
  const [historyExpanded, setHistoryExpanded] = useState(false);

  useEffect(() => {
    if (!alerts || alerts.length === 0 || !timestamp) return;

    const newEntries: AlertHistoryEntry[] = alerts
      .filter((a) => a.triggered)
      .map((alert, i) => ({
        alert,
        timestamp,
        id: `${timestamp}-${i}`,
      }));

    if (newEntries.length > 0) {
      setAlertHistory((prev) => [...newEntries, ...prev].slice(0, MAX_ALERT_HISTORY));
    }
  }, [alerts, timestamp]);

  const activeAlerts = alerts?.filter((a) => a.triggered) ?? [];
  const hasActiveAlerts = activeAlerts.length > 0;

  if (!hasActiveAlerts && alertHistory.length === 0) {
    return null;
  }

  return (
    <div className={`alert-banner ${hasActiveAlerts ? 'alert-banner--active' : 'alert-banner--inactive'}`}>
      {hasActiveAlerts && (
        <div className="alert-banner__live">
          <span className="alert-banner__icon">&#9888;</span>
          <div className="alert-banner__alerts">
            {activeAlerts.map((alert, i) => (
              <div key={i} className="alert-banner__alert-item">
                <span className="alert-banner__rule">{alert.rule}</span>
                <span className="alert-banner__detail">{alert.detail}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {alertHistory.length > 0 && (
        <div className="alert-banner__history-section">
          <button
            className="alert-banner__history-toggle"
            onClick={() => setHistoryExpanded(!historyExpanded)}
            type="button"
          >
            Alert History ({alertHistory.length}) {historyExpanded ? '▾' : '▸'}
          </button>
          {historyExpanded && (
            <ul className="alert-banner__history-list">
              {alertHistory.map((entry) => (
                <li key={entry.id} className="alert-banner__history-item">
                  <span className="alert-banner__history-time">
                    {new Date(entry.timestamp * 1000).toLocaleTimeString()}
                  </span>
                  <span className="alert-banner__history-rule">{entry.alert.rule}</span>
                  <span className="alert-banner__history-detail">{entry.alert.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
