import React, { useState } from 'react';
import type { VlmResult, RiskLevel } from '../../types/vlm';
import './VlmPanel.css';

interface VlmPanelProps {
  latestResult: VlmResult | null;
}

const RISK_COLORS: Record<RiskLevel, string> = {
  HIGH: '#ef4444',
  MEDIUM: '#f59e0b',
  LOW: '#22c55e',
  NONE: '#6b7280',
};

function formatTimeSince(timestamp: number): string {
  const seconds = Math.floor((Date.now() / 1000) - timestamp);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

export const VlmPanel: React.FC<VlmPanelProps> = ({ latestResult }) => {
  const [risksExpanded, setRisksExpanded] = useState(true);
  const [promptExpanded, setPromptExpanded] = useState(false);

  if (!latestResult) {
    return (
      <div className="vlm-panel vlm-panel--empty">
        <div className="vlm-panel__placeholder">
          <svg className="vlm-panel__placeholder-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <p>Waiting for VLM analysis...</p>
          <p className="vlm-panel__placeholder-hint">Scene risk assessment will appear here</p>
        </div>
      </div>
    );
  }

  const { response, raw_output, inference_time_ms, model_name, timestamp, prompt } = latestResult;
  const riskLevel = response?.risk_level ?? 'NONE';
  const riskColor = RISK_COLORS[riskLevel];

  return (
    <div className="vlm-panel">
      <div className="vlm-panel__header">
        <span
          className="vlm-panel__risk-badge"
          style={{ backgroundColor: riskColor }}
        >
          {riskLevel}
        </span>
        <span className="vlm-panel__staleness">{formatTimeSince(timestamp)}</span>
      </div>

      {response ? (
        <>
          <p className="vlm-panel__summary">{response.summary}</p>

          {response.risks.length > 0 && (
            <div className="vlm-panel__risks">
              <button
                className="vlm-panel__risks-toggle"
                onClick={() => setRisksExpanded(!risksExpanded)}
              >
                Risks ({response.risks.length}) {risksExpanded ? '▾' : '▸'}
              </button>
              {risksExpanded && (
                <ul className="vlm-panel__risks-list">
                  {response.risks.map((risk, i) => (
                    <li key={i} className="vlm-panel__risk-item">
                      <div className="vlm-panel__risk-top-row">
                        <span
                          className="vlm-panel__risk-severity"
                          style={{ backgroundColor: RISK_COLORS[risk.severity] }}
                        >
                          {risk.severity}
                        </span>
                        <span className="vlm-panel__risk-category">{risk.category}</span>
                      </div>
                      <span className="vlm-panel__risk-desc">{risk.description}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      ) : (
        <div className="vlm-panel__raw">
          <p className="vlm-panel__raw-label">Raw output (JSON parse failed):</p>
          <pre className="vlm-panel__raw-output">{raw_output}</pre>
        </div>
      )}

      <div className="vlm-panel__footer">
        <span className="vlm-panel__inference-time"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{verticalAlign: 'middle', marginRight: '4px'}}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>{(inference_time_ms / 1000).toFixed(1)}s</span>
        <span className="vlm-panel__model">{model_name}</span>
      </div>

      <div className="vlm-panel__prompt-section">
        <button
          className="vlm-panel__prompt-toggle"
          onClick={() => setPromptExpanded(!promptExpanded)}
        >
          Prompt {promptExpanded ? '▾' : '▸'}
        </button>
        {promptExpanded && (
          <div className="vlm-panel__prompt-content">
            <div className="vlm-panel__prompt-field">
              <label>System:</label>
              <p>{prompt.system}</p>
            </div>
            <div className="vlm-panel__prompt-field">
              <label>User:</label>
              <p>{prompt.user}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
