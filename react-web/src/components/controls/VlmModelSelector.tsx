/**
 * VlmModelSelector - Displays VLM model inventory and allows switching the active VLM model
 * independently from the CV model, via the vlm-config IoT Device Shadow.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { iotShadowService, VlmConfigShadowState } from '../../services/iotShadowService';
import { useAuthenticatedAWS } from '../../hooks/useAuthenticatedAWS';
import { ModelSwitchState } from '../../types/modelConfig';
import './ModelSelector.css';

export interface VlmModelSelectorProps {
  thingName: string;
  className?: string;
}

type LoadState = 'loading' | 'loaded' | 'error';

export const VlmModelSelector: React.FC<VlmModelSelectorProps> = ({
  thingName,
  className = '',
}) => {
  const { credentials, region } = useAuthenticatedAWS();

  const [vlmModels, setVlmModels] = useState<Record<string, { status: string; channel?: string; reason?: string }>>({});
  const [activeVlmModelId, setActiveVlmModelId] = useState<string | null>(null);
  const [selectedVlmModelId, setSelectedVlmModelId] = useState<string | null>(null);
  const [switchState, setSwitchState] = useState<ModelSwitchState>('idle');
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [shadowExists, setShadowExists] = useState<boolean>(true);
  const [errorMessage, setErrorMessage] = useState<string>('');

  const applyVlmState = (state: VlmConfigShadowState | null) => {
    if (state) {
      setVlmModels(state.reported_models);
      setActiveVlmModelId(state.reported_active_model);
      setSelectedVlmModelId(state.reported_active_model);
      setShadowExists(true);
    } else {
      setShadowExists(false);
    }
  };

  useEffect(() => {
    if (!thingName || !credentials) return;
    let cancelled = false;

    const loadShadow = async (attempt: number): Promise<void> => {
      try {
        const state = await iotShadowService.getVlmConfigShadow(thingName, credentials, region);
        if (cancelled) return;
        applyVlmState(state);
        setLoadState('loaded');
      } catch (err: any) {
        if (cancelled) return;
        if (attempt === 1) {
          await new Promise((r) => setTimeout(r, 1000));
          if (!cancelled) return loadShadow(2);
        } else {
          setErrorMessage('Failed to read VLM model configuration.');
          setLoadState('error');
        }
      }
    };

    setLoadState('loading');
    loadShadow(1);
    return () => { cancelled = true; };
  }, [thingName, credentials, region]);

  const handleRetry = useCallback(async () => {
    if (!thingName || !credentials) return;
    setErrorMessage('');
    setLoadState('loading');

    try {
      const state = await iotShadowService.getVlmConfigShadow(thingName, credentials, region);
      applyVlmState(state);
      setLoadState('loaded');
    } catch (err: any) {
      setErrorMessage('Failed to read VLM model configuration.');
      setLoadState('error');
    }
  }, [thingName, credentials, region]);

  const handleApply = useCallback(async () => {
    if (!selectedVlmModelId || !credentials || selectedVlmModelId === activeVlmModelId) return;
    if (switchState !== 'idle') return;

    setSwitchState('updating');
    setErrorMessage('');

    try {
      await iotShadowService.setActiveVlmModel(thingName, credentials, region, selectedVlmModelId);
      setActiveVlmModelId(selectedVlmModelId);
      setSwitchState('success');
      setTimeout(() => setSwitchState('idle'), 3000);
    } catch (err: any) {
      setErrorMessage(err?.message || 'Failed to switch VLM model.');
      setSwitchState('error');
      setSelectedVlmModelId(activeVlmModelId);
      setTimeout(() => setSwitchState('idle'), 3000);
    }
  }, [selectedVlmModelId, activeVlmModelId, credentials, thingName, region, switchState]);

  const handleModelClick = (modelId: string, status: string) => {
    if (status !== 'ready') return;
    if (switchState !== 'idle') return;
    setSelectedVlmModelId(modelId);
    setErrorMessage('');
  };

  if (!thingName) {
    return (
      <div className={`model-selector ${className}`} role="group" aria-labelledby="vlm-model-selector-label">
        <label id="vlm-model-selector-label" className="model-selector__label">
          VLM Model
        </label>
      </div>
    );
  }

  const isApplyEnabled =
    switchState === 'idle' &&
    selectedVlmModelId !== null &&
    selectedVlmModelId !== activeVlmModelId;

  const renderStatusBadge = (status: string): React.ReactNode => {
    const label = status === 'ready' ? 'Ready' : status === 'installing' ? 'Installing' : 'Failed';
    const cssStatus = ['ready', 'installing', 'failed'].includes(status) ? status : 'failed';
    return (
      <span className={`model-selector__status-badge model-selector__status-badge--${cssStatus}`}>
        {label}
      </span>
    );
  };

  return (
    <div className={`model-selector ${className}`} role="group" aria-labelledby="vlm-model-selector-label">
      <label id="vlm-model-selector-label" className="model-selector__label">
        VLM Model
      </label>

      <div className="model-selector__body">
        {loadState === 'loading' && (
          <div className="model-selector__overlay">
            <div className="model-selector__overlay-spinner" />
            <span className="model-selector__overlay-text">Loading VLM models...</span>
          </div>
        )}
        {loadState === 'loaded' && !shadowExists && (
          <p className="model-selector__hint">No model configuration available</p>
        )}
        {loadState === 'loaded' && shadowExists && Object.keys(vlmModels).length === 0 && (
          <p className="model-selector__hint">No VLM models installed on device</p>
        )}

        {loadState === 'loaded' && Object.keys(vlmModels).length > 0 && (
          <>
            <div className="model-selector__list" role="listbox" aria-label="VLM models">
              {Object.entries(vlmModels).map(([modelId, entry]) => {
                const isActive = modelId === activeVlmModelId;
                const isSelectable = entry.status === 'ready' && switchState === 'idle';
                const classes = ['model-selector__item'];
                if (isActive) classes.push('model-selector__item--active');
                if (modelId === selectedVlmModelId && !isActive) classes.push('model-selector__item--selected');
                if (entry.status === 'ready') classes.push('model-selector__item--ready');
                if (entry.status === 'installing') { classes.push('model-selector__item--installing'); classes.push('model-selector__item--disabled'); }
                if (entry.status === 'failed') { classes.push('model-selector__item--failed'); classes.push('model-selector__item--disabled'); }
                return (
                  <div
                    key={modelId}
                    className={classes.join(' ')}
                    role="option"
                    aria-selected={modelId === selectedVlmModelId}
                    aria-disabled={!isSelectable}
                    onClick={() => handleModelClick(modelId, entry.status)}
                    tabIndex={isSelectable ? 0 : -1}
                    onKeyDown={(e) => {
                      if ((e.key === 'Enter' || e.key === ' ') && isSelectable) {
                        e.preventDefault();
                        handleModelClick(modelId, entry.status);
                      }
                    }}
                  >
                    <div className="model-selector__item-content">
                      <span className="model-selector__item-name">{modelId}</span>
                      <span className="model-selector__item-meta">{entry.channel ?? 'stable'} channel</span>
                      {entry.status === 'failed' && (
                        <span className="model-selector__item-failure">{entry.reason || 'Failed'}</span>
                      )}
                    </div>
                    {renderStatusBadge(entry.status)}
                    {isActive && <span className="model-selector__active-badge">Active</span>}
                  </div>
                );
              })}
            </div>

            <button
              className={`model-selector__apply-btn ${isApplyEnabled ? 'model-selector__apply-btn--enabled' : ''}`}
              onClick={isApplyEnabled ? handleApply : undefined}
              disabled={!isApplyEnabled}
              aria-label="Apply VLM model selection"
            >
              {switchState === 'updating' ? 'Applying...' : switchState === 'success' ? 'Applied ✓' : 'Apply'}
            </button>

            {switchState === 'updating' && (
              <div className="model-selector__overlay" role="status" aria-live="polite">
                <div className="model-selector__overlay-spinner" />
                <span className="model-selector__overlay-text">Updating shadow...</span>
              </div>
            )}
          </>
        )}
      </div>

      {errorMessage && (
        <div className="model-selector__error" role="alert">
          <span className="model-selector__error-text">{errorMessage}</span>
          <div className="model-selector__error-actions">
            {loadState === 'error' && (
              <button className="model-selector__retry-btn" onClick={handleRetry} aria-label="Retry">
                Retry
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
