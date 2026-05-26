import React, { useState, useEffect, useCallback } from 'react';
import { iotShadowService } from '../../services/iotShadowService';
import { useAuthenticatedAWS } from '../../hooks/useAuthenticatedAWS';
import './InferenceIntervalControl.css';

export interface InferenceIntervalControlProps {
  className?: string;
  thingName: string;
}

const MIN_INTERVAL = 1;
const MAX_INTERVAL = 30;
const DEFAULT_INTERVAL = 1;

export const InferenceIntervalControl: React.FC<InferenceIntervalControlProps> = ({
  className = '',
  thingName,
}) => {
  const { credentials, region } = useAuthenticatedAWS();
  const [sliderValue, setSliderValue] = useState<number>(DEFAULT_INTERVAL);
  const [appliedValue, setAppliedValue] = useState<number | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'saving' | 'saved' | 'error'>('idle');
  const [errorMessage, setErrorMessage] = useState<string>('');

  useEffect(() => {
    if (!thingName || !credentials) return;

    setStatus('loading');
    iotShadowService.getInferenceInterval(thingName, credentials, region)
      .then((value) => {
        if (value !== null) {
          setSliderValue(value);
          setAppliedValue(value);
        }
        setStatus('idle');
      })
      .catch((err) => {
        console.error('Failed to read inference interval from shadow:', err);
        setStatus('error');
        setErrorMessage('Failed to read current interval from device shadow.');
      });
  }, [thingName, credentials, region]);

  const handleApply = useCallback(async () => {
    if (!thingName || !credentials) return;
    setStatus('saving');
    setErrorMessage('');
    try {
      await iotShadowService.setInferenceInterval(thingName, credentials, region, sliderValue);
      setAppliedValue(sliderValue);
      setStatus('saved');
      setTimeout(() => setStatus('idle'), 2000);
    } catch (err: any) {
      console.error('Failed to update inference interval:', err);
      setStatus('error');
      setErrorMessage(err?.message || 'Failed to update device shadow.');
    }
  }, [thingName, credentials, region, sliderValue]);

  const isDisabled = !thingName || !credentials || status === 'loading' || status === 'saving';
  const hasChanged = appliedValue === null || sliderValue !== appliedValue;

  return (
    <div className={`inference-interval ${className}`} role="group" aria-labelledby="inference-interval-label">
      <label id="inference-interval-label" className="inference-interval__label">
        Inference Interval
      </label>

      <div className="inference-interval__body">
        <div className="inference-interval__slider-row">
          <span className="inference-interval__bound">{MIN_INTERVAL}s</span>
          <input
            type="range"
            className="inference-interval__slider"
            min={MIN_INTERVAL}
            max={MAX_INTERVAL}
            step={1}
            value={sliderValue}
            onChange={(e) => setSliderValue(parseInt(e.target.value, 10))}
            disabled={isDisabled}
            aria-label="Inference interval slider"
            aria-valuemin={MIN_INTERVAL}
            aria-valuemax={MAX_INTERVAL}
            aria-valuenow={sliderValue}
          />
          <span className="inference-interval__bound">{MAX_INTERVAL}s</span>
          <span className="inference-interval__value">{sliderValue}s</span>
        </div>

        <button
          type="button"
          className={`inference-interval__apply${hasChanged ? ' inference-interval__apply--changed' : ''}`}
          onClick={handleApply}
          disabled={isDisabled || !hasChanged}
          aria-label="Apply inference interval"
        >
          {status === 'saving' ? 'Applying...' : status === 'saved' ? 'Applied' : 'Apply'}
        </button>
      </div>

      {status === 'error' && (
        <div className="inference-interval__error" role="alert">
          {errorMessage}
        </div>
      )}

      {appliedValue !== null && status !== 'error' && (
        <p className="inference-interval__applied">
          Device interval: <strong>{appliedValue}s</strong>
        </p>
      )}
    </div>
  );
};
