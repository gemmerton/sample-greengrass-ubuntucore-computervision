/**
 * ModelSelector - Displays model inventory and allows switching the active inference model
 * via the model-config IoT Device Shadow.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { iotShadowService } from '../../services/iotShadowService';
import { useAuthenticatedAWS } from '../../hooks/useAuthenticatedAWS';
import { ModelEntry, ModelInventory, ModelSwitchState } from '../../types/modelConfig';
import './ModelSelector.css';

const UPDATE_TIMEOUT_MS = 30000;
const POLL_INTERVAL_MS = 5000;
const SWITCH_TIMEOUT_MS = 90000;
const SUCCESS_DISPLAY_MS = 5000;
const MAX_POLL_FAILURES = 3;

export interface ModelSelectorProps {
  thingName: string;
  className?: string;
}

type LoadState = 'loading' | 'loaded' | 'error';

export const ModelSelector: React.FC<ModelSelectorProps> = ({
  thingName,
  className = '',
}) => {
  const { credentials, region } = useAuthenticatedAWS();

  const [models, setModels] = useState<ModelInventory>({});
  const [activeModelId, setActiveModelId] = useState<string | null>(null);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [switchState, setSwitchState] = useState<ModelSwitchState>('idle');
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [pollFailCount, setPollFailCount] = useState<number>(0);
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [shadowExists, setShadowExists] = useState<boolean>(true);
  const [successMessage, setSuccessMessage] = useState<string>('');

  // Ref to track the target model ID during switching (the model we're switching to)
  const targetModelRef = useRef<string | null>(null);

  // Load model config shadow when thingName and credentials are available.
  // Includes a short delay to allow the credential provider to resolve on first use,
  // and retries once on failure to handle transient credential resolution errors.
  useEffect(() => {
    if (!thingName || !credentials) return;

    let cancelled = false;

    const loadShadow = async (attempt: number): Promise<void> => {
      try {
        const state = await iotShadowService.getModelConfigShadow(thingName, credentials, region);
        if (cancelled) return;
        if (state) {
          setModels(state.reported_models);
          setActiveModelId(state.reported_active_model);
          setSelectedModelId(state.reported_active_model);
          setShadowExists(true);
        } else {
          setShadowExists(false);
        }
        setLoadState('loaded');
      } catch (err: any) {
        if (cancelled) return;
        // Retry once after a short delay — handles credential provider not yet resolved
        if (attempt === 1) {
          console.warn('Model config shadow load failed, retrying in 1s...', err?.message);
          await new Promise((r) => setTimeout(r, 1000));
          if (!cancelled) {
            return loadShadow(2);
          }
        } else {
          console.error('Failed to read model config shadow:', err);
          setErrorMessage('Failed to read model configuration from device shadow.');
          setLoadState('error');
        }
      }
    };

    setLoadState('loading');
    loadShadow();

    return () => { cancelled = true; };
  }, [thingName, credentials, region]);

  // Polling effect: poll getModelConfigShadow every 5s while in 'switching' state
  useEffect(() => {
    if (switchState !== 'switching') return;
    if (!thingName || !credentials) return;

    const targetModelId = targetModelRef.current;
    if (!targetModelId) return;

    const startTime = Date.now();
    let failCount = 0;

    const intervalId = setInterval(async () => {
      // Check timeout first
      if (Date.now() - startTime >= SWITCH_TIMEOUT_MS) {
        clearInterval(intervalId);
        setSwitchState('timeout');
        setErrorMessage('Model switch timed out after 90 seconds. The device may still be processing the request.');
        setPollFailCount(0);
        return;
      }

      try {
        const state = await iotShadowService.getModelConfigShadow(thingName, credentials, region);

        // Reset poll failure count on successful poll
        failCount = 0;
        setPollFailCount(0);

        if (!state) return;

        // Check if reported.active_model matches the target
        if (state.reported_active_model === targetModelId) {
          clearInterval(intervalId);
          setActiveModelId(targetModelId);
          setSelectedModelId(targetModelId);
          setModels(state.reported_models);
          setSuccessMessage(`Model switched to "${targetModelId}" successfully.`);
          setSwitchState('success');
          setPollFailCount(0);

          // Auto-dismiss success after 5 seconds, transition back to idle
          setTimeout(() => {
            setSuccessMessage('');
            setSwitchState('idle');
          }, SUCCESS_DISPLAY_MS);
          return;
        }

        // Check if target model status became 'failed'
        const targetEntry = state.reported_models[targetModelId];
        if (targetEntry && targetEntry.status === 'failed') {
          clearInterval(intervalId);
          const reason = targetEntry.failure_reason || 'Model switch failed on the device.';
          setErrorMessage(`Device failed to switch model: ${reason}`);
          setSwitchState('error');
          setSelectedModelId(state.reported_active_model);
          setModels(state.reported_models);
          setPollFailCount(0);
          return;
        }

        // Update models with latest state from poll
        setModels(state.reported_models);
      } catch (err) {
        // Poll failed - increment consecutive failure count
        failCount += 1;
        setPollFailCount(failCount);

        if (failCount >= MAX_POLL_FAILURES) {
          // Display connectivity warning but continue polling
          console.warn(`ModelSelector: ${failCount} consecutive poll failures during model switch.`);
        }
      }
    }, POLL_INTERVAL_MS);

    // Cleanup: clear interval on unmount or when switchState changes away from 'switching'
    return () => {
      clearInterval(intervalId);
    };
  }, [switchState, thingName, credentials, region]);

  /**
   * Handle retry on load failure.
   * Preserves previously loaded state (models/activeModelId) if retry also fails.
   */
  const handleRetry = useCallback(async () => {
    if (!thingName || !credentials) return;

    setErrorMessage('');
    setLoadState('loading');

    try {
      const state = await iotShadowService.getModelConfigShadow(thingName, credentials, region);
      if (state) {
        setModels(state.reported_models);
        setActiveModelId(state.reported_active_model);
        setSelectedModelId(state.reported_active_model);
        setShadowExists(true);
      } else {
        setShadowExists(false);
      }
      setLoadState('loaded');
    } catch (err: any) {
      console.error('Retry failed to read model config shadow:', err);
      setErrorMessage('Failed to read model configuration from device shadow.');
      if (Object.keys(models).length > 0 || activeModelId !== null) {
        setLoadState('loaded');
      } else {
        setLoadState('error');
      }
    }
  }, [thingName, credentials, region, models, activeModelId]);

  /**
   * Dismiss switch/timeout error - transitions switchState back to idle and clears error.
   */
  const handleDismissError = useCallback(() => {
    setSwitchState('idle');
    setErrorMessage('');
  }, []);

  /**
   * Handle Apply action - transitions through updating -> switching states.
   */
  const handleApply = useCallback(async () => {
    if (!selectedModelId || !credentials || selectedModelId === activeModelId) return;
    if (switchState !== 'idle') return;

    setSwitchState('updating');
    setErrorMessage('');

    const timeoutPromise = new Promise<never>((_, reject) => {
      setTimeout(() => reject(new Error('TIMEOUT')), UPDATE_TIMEOUT_MS);
    });

    try {
      await Promise.race([
        iotShadowService.setActiveModel(thingName, credentials, region, selectedModelId),
        timeoutPromise,
      ]);

      targetModelRef.current = selectedModelId;
      setPollFailCount(0);
      setSwitchState('switching');
    } catch (err: any) {
      if (err?.message === 'TIMEOUT') {
        setErrorMessage('Model switch request timed out after 30 seconds. Please try again.');
      } else {
        setErrorMessage(err?.message || 'Failed to update model selection. Please try again.');
      }
      setSwitchState('error');
      setSelectedModelId(activeModelId);
    }
  }, [selectedModelId, activeModelId, credentials, thingName, region, switchState]);

  // --- All hooks are above this line. Conditional returns below. ---

  // When thingName is empty, display hint message
  if (!thingName) {
    return (
      <div className={`model-selector ${className}`} role="group" aria-labelledby="model-selector-label">
        <label id="model-selector-label" className="model-selector__label">
          Model Selection
        </label>
        <p className="model-selector__hint">
          Set an IoT Thing Name above to enable model selection.
        </p>
      </div>
    );
  }

  // Determine if the Apply button should be enabled
  const isApplyEnabled =
    switchState === 'idle' &&
    selectedModelId !== null &&
    selectedModelId !== activeModelId;

  const handleModelClick = (modelId: string, entry: ModelEntry) => {
    if (entry.status !== 'ready') return;
    if (switchState !== 'idle') return;
    setSelectedModelId(modelId);
    setErrorMessage('');
  };

  const getItemClassName = (modelId: string, entry: ModelEntry): string => {
    const classes = ['model-selector__item'];

    if (modelId === activeModelId) {
      classes.push('model-selector__item--active');
    }
    if (modelId === selectedModelId && modelId !== activeModelId) {
      classes.push('model-selector__item--selected');
    }

    switch (entry.status) {
      case 'ready':
        classes.push('model-selector__item--ready');
        break;
      case 'installing':
        classes.push('model-selector__item--installing');
        classes.push('model-selector__item--disabled');
        break;
      case 'failed':
        classes.push('model-selector__item--failed');
        classes.push('model-selector__item--disabled');
        break;
    }

    return classes.join(' ');
  };

  const renderStatusBadge = (status: ModelEntry['status']): React.ReactNode => {
    const label = status === 'ready' ? 'Ready' : status === 'installing' ? 'Installing' : 'Failed';
    return (
      <span className={`model-selector__status-badge model-selector__status-badge--${status}`}>
        {label}
      </span>
    );
  };

  const renderModelList = (): React.ReactNode => {
    // Still loading - show nothing in the list area
    if (loadState === 'loading') {
      return (
        <div className="model-selector__overlay">
          <div className="model-selector__overlay-spinner" />
          <span className="model-selector__overlay-text">Loading models...</span>
        </div>
      );
    }

    // Shadow does not exist (null response)
    if (loadState === 'loaded' && !shadowExists) {
      return (
        <p className="model-selector__hint">No model configuration available</p>
      );
    }

    // Shadow exists but models map is empty
    const modelIds = Object.keys(models);
    if (loadState === 'loaded' && modelIds.length === 0) {
      return (
        <p className="model-selector__hint">No models installed on device</p>
      );
    }

    // Check if active model references a model not in inventory
    const activeModelNotInInventory =
      activeModelId !== null && !models[activeModelId];

    return (
      <>
        {activeModelNotInInventory && (
          <div
            className="model-selector__item model-selector__item--active model-selector__item--disabled"
            role="option"
            aria-selected={false}
            aria-disabled={true}
          >
            <div className="model-selector__item-content">
              <span className="model-selector__item-name">{activeModelId}</span>
              <span className="model-selector__not-found">Model not found in inventory</span>
            </div>
            <span className="model-selector__active-badge">Active</span>
          </div>
        )}
        {modelIds.map((modelId) => {
          const entry = models[modelId];
          const isActive = modelId === activeModelId;
          const isSelectable = entry.status === 'ready' && switchState === 'idle';

          return (
            <div
              key={modelId}
              className={getItemClassName(modelId, entry)}
              role="option"
              aria-selected={modelId === selectedModelId}
              aria-disabled={!isSelectable}
              onClick={() => handleModelClick(modelId, entry)}
              tabIndex={isSelectable ? 0 : -1}
              onKeyDown={(e) => {
                if ((e.key === 'Enter' || e.key === ' ') && isSelectable) {
                  e.preventDefault();
                  handleModelClick(modelId, entry);
                }
              }}
            >
              <div className="model-selector__item-content">
                <span className="model-selector__item-name">
                  {entry.model_metadata.model_name}
                </span>
                <span className="model-selector__item-meta">
                  {modelId} &middot; v{entry.model_metadata.version}
                </span>
                {entry.status === 'failed' && (
                  <span className="model-selector__item-failure">
                    {entry.failure_reason || 'Failed'}
                  </span>
                )}
              </div>
              {renderStatusBadge(entry.status)}
              {isActive && (
                <span className="model-selector__active-badge">Active</span>
              )}
            </div>
          );
        })}
      </>
    );
  };

  return (
    <div className={`model-selector ${className}`} role="group" aria-labelledby="model-selector-label">
      <label id="model-selector-label" className="model-selector__label">
        Model Selection
      </label>

      <div className="model-selector__body">
        <div className="model-selector__list" role="listbox" aria-label="Available models">
          {renderModelList()}
        </div>

        {/* Apply button - enabled only when selection differs from active and state is idle */}
        <button
          className={`model-selector__apply-btn ${isApplyEnabled ? 'model-selector__apply-btn--enabled' : ''}`}
          onClick={isApplyEnabled ? handleApply : undefined}
          disabled={!isApplyEnabled}
          aria-label="Apply model selection"
        >
          {switchState === 'updating' ? 'Applying...' : 'Apply'}
        </button>

        {/* Switching overlay shown during updating/switching states */}
        {(switchState === 'updating' || switchState === 'switching') && (
          <div className="model-selector__overlay" role="status" aria-live="polite">
            <div className="model-selector__overlay-spinner" />
            <span className="model-selector__overlay-text">
              {switchState === 'updating' ? 'Updating shadow...' : 'Waiting for device to switch model...'}
            </span>
          </div>
        )}
      </div>

      {/* Connectivity warning - inline, non-blocking, shown during poll failures while switching */}
      {pollFailCount >= MAX_POLL_FAILURES && switchState === 'switching' && (
        <div className="model-selector__connectivity-warning" role="status" aria-live="polite">
          Connectivity issues detected. Retrying...
        </div>
      )}

      {/* Error display with contextual actions */}
      {errorMessage && (
        <div className="model-selector__error" role="alert">
          <span className="model-selector__error-text">{errorMessage}</span>
          <div className="model-selector__error-actions">
            {loadState === 'error' && (
              <button
                className="model-selector__retry-btn"
                onClick={handleRetry}
                aria-label="Retry loading model configuration"
              >
                Retry
              </button>
            )}
            {(switchState === 'error' || switchState === 'timeout') && (
              <button
                className="model-selector__dismiss-btn"
                onClick={handleDismissError}
                aria-label="Dismiss error"
              >
                Dismiss
              </button>
            )}
          </div>
        </div>
      )}

      {/* Success message */}
      {successMessage && (
        <div className="model-selector__success" role="status" aria-live="polite">
          {successMessage}
        </div>
      )}
    </div>
  );
};
