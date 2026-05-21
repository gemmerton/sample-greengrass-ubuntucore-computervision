import React, { useState } from 'react';
import type { VlmResult, RiskLevel } from '../../types/vlm';
import './VlmTimeline.css';

interface VlmTimelineProps {
  history: VlmResult[];
}

const RISK_COLORS: Record<RiskLevel, string> = {
  HIGH: '#ef4444',
  MEDIUM: '#f59e0b',
  LOW: '#22c55e',
  NONE: '#6b7280',
};

function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export const VlmTimeline: React.FC<VlmTimelineProps> = ({ history }) => {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  if (history.length === 0) {
    return (
      <div className="vlm-timeline vlm-timeline--empty">
        <p>Analysis timeline will appear here as VLM results arrive</p>
      </div>
    );
  }

  return (
    <div className="vlm-timeline">
      <div className="vlm-timeline__scroll">
        {history.map((result, index) => {
          const riskLevel = result.response?.risk_level ?? 'NONE';
          const isExpanded = expandedIndex === index;

          return (
            <button
              key={result.timestamp}
              className={`vlm-timeline__card ${isExpanded ? 'vlm-timeline__card--expanded' : ''}`}
              style={{ borderLeftColor: RISK_COLORS[riskLevel] }}
              onClick={() => setExpandedIndex(isExpanded ? null : index)}
            >
              <span className="vlm-timeline__time">{formatTime(result.timestamp)}</span>
              <span
                className="vlm-timeline__badge"
                style={{ backgroundColor: RISK_COLORS[riskLevel] }}
              >
                {riskLevel}
              </span>
              <span className="vlm-timeline__summary">
                {result.response?.summary ?? 'Parse failed'}
              </span>
              {isExpanded && result.response?.risks && (
                <ul className="vlm-timeline__detail">
                  {result.response.risks.map((risk, i) => (
                    <li key={i}>
                      <span style={{ color: RISK_COLORS[risk.severity] }}>{risk.severity}</span>
                      {' '}{risk.description}
                    </li>
                  ))}
                </ul>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};
