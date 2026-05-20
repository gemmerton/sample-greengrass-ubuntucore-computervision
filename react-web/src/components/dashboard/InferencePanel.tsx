import React from 'react';
import type { InferenceResult, Detection, Classification } from '../../types/inference';

interface InferencePanelProps {
  latestResult: InferenceResult | null;
  history: InferenceResult[];
  className?: string;
}

export const InferencePanel: React.FC<InferencePanelProps> = ({
  latestResult,
  history,
  className = '',
}) => {
  if (!latestResult) {
    return (
      <div className={`inference-panel ${className}`}>
        <div className="inference-panel__empty">
          Waiting for inference results...
        </div>
      </div>
    );
  }

  return (
    <div className={`inference-panel ${className}`}>
      <div className="inference-panel__header">
        <span className="inference-panel__model">{latestResult.model_name}</span>
        <span className="inference-panel__timing">{latestResult.inference_time_ms}ms</span>
        <span className="inference-panel__type">{latestResult.result_type}</span>
      </div>

      <div className="inference-panel__results">
        {latestResult.result_type === 'detection' ? (
          <DetectionTable
            detections={(latestResult.results as { detections: Detection[] }).detections}
          />
        ) : (
          <ClassificationList
            classifications={(latestResult.results as { classifications: Classification[] }).classifications}
          />
        )}
      </div>

      <div className="inference-panel__history">
        <span className="inference-panel__history-label">
          History ({history.length})
        </span>
        <div className="inference-panel__history-list">
          {history.slice(0, 10).map((r, i) => (
            <div key={i} className="inference-panel__history-item">
              <span>{new Date(r.timestamp * 1000).toLocaleTimeString()}</span>
              <span>{r.result_type === 'detection'
                ? `${(r.results as { count: number }).count} detections`
                : `${(r.results as { classifications: Classification[] }).classifications.length} classes`
              }</span>
              <span>{r.inference_time_ms}ms</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

const DetectionTable: React.FC<{ detections: Detection[] }> = ({ detections }) => {
  if (detections.length === 0) {
    return <div className="inference-panel__no-results">No detections</div>;
  }
  return (
    <table className="inference-panel__table">
      <thead>
        <tr><th>Label</th><th>Score</th><th>Position</th></tr>
      </thead>
      <tbody>
        {detections.map((d, i) => (
          <tr key={i}>
            <td>{d.label}</td>
            <td>{(d.score * 100).toFixed(1)}%</td>
            <td className="inference-panel__coords">
              ({d.box.xmin.toFixed(2)}, {d.box.ymin.toFixed(2)}) -
              ({d.box.xmax.toFixed(2)}, {d.box.ymax.toFixed(2)})
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

const ClassificationList: React.FC<{ classifications: Classification[] }> = ({ classifications }) => {
  if (classifications.length === 0) {
    return <div className="inference-panel__no-results">No classifications</div>;
  }
  return (
    <div className="inference-panel__class-list">
      {classifications.map((c, i) => (
        <div key={i} className="inference-panel__class-item">
          <span className="inference-panel__class-label">{c.label}</span>
          <div className="inference-panel__class-bar">
            <div
              className="inference-panel__class-bar-fill"
              style={{ width: `${c.confidence * 100}%` }}
            />
          </div>
          <span className="inference-panel__class-score">
            {(c.confidence * 100).toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  );
};
