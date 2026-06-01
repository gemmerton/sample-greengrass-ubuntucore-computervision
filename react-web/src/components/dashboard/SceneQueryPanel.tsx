import React, { useState } from 'react';
import { useSceneQuery } from '../../hooks/useSceneQuery';
import './SceneQueryPanel.css';

export const SceneQueryPanel: React.FC = () => {
  const { history, pendingQueryId, submitQuery, clearHistory } = useSceneQuery();
  const [input, setInput] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || pendingQueryId) return;
    submitQuery(input.trim());
    setInput('');
  };

  return (
    <div className="scene-query-panel">
      <div className="scene-query-panel__header">
        <h4 className="scene-query-panel__title">Scene Query</h4>
        {history.length > 0 && (
          <button className="scene-query-panel__clear" onClick={clearHistory} type="button">
            Clear
          </button>
        )}
      </div>

      <div className="scene-query-panel__history">
        {history.length === 0 && (
          <p className="scene-query-panel__placeholder">
            Ask a question about the current scene...
          </p>
        )}
        {history.map((entry) => (
          <div key={entry.query_id} className="scene-query-panel__entry">
            <div className="scene-query-panel__question">
              <span className="scene-query-panel__q-label">Q:</span>
              {entry.question}
            </div>
            <div className="scene-query-panel__answer">
              {entry.pending ? (
                <span className="scene-query-panel__pending">Thinking...</span>
              ) : (
                <>
                  <span className="scene-query-panel__a-label">A:</span>
                  {entry.answer}
                  {entry.inference_time_ms && (
                    <span className="scene-query-panel__time">
                      {(entry.inference_time_ms / 1000).toFixed(1)}s
                    </span>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      <form className="scene-query-panel__form" onSubmit={handleSubmit}>
        <input
          className="scene-query-panel__input"
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. How many workers are near the trench?"
          disabled={!!pendingQueryId}
        />
        <button
          className="scene-query-panel__submit"
          type="submit"
          disabled={!input.trim() || !!pendingQueryId}
        >
          Ask
        </button>
      </form>
    </div>
  );
};
