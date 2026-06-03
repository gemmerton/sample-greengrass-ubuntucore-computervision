import React, { useState, useEffect } from 'react';
import { iotShadowService } from '../../services/iotShadowService';
import { useAuthenticatedAWS } from '../../hooks/useAuthenticatedAWS';
import type { VlmConfig } from '../../types/vlm';
import './VlmPromptEditor.css';

const PRESETS: Record<string, { system: string; user: string }> = {
  'Workplace Safety': {
    system: 'You are a workplace safety analyst. Analyse the image and return a JSON object with: risk_level (HIGH/MEDIUM/LOW/NONE), summary (one sentence), and risks (array of {description, severity, category}).',
    user: 'Assess workplace safety risks visible in this scene.',
  },
  'Construction Site Safety': {
    system: 'You are a construction site safety analyst. Analyse ONLY what is clearly visible in the image. Do NOT assume or infer the presence of objects, equipment, or conditions that are not visible. If something is not in the image, do not mention it. Return a JSON object with: risk_level (HIGH/MEDIUM/LOW/NONE), summary (one sentence describing only what you observe), and risks (array of {description, severity, category}). Only include risks for hazards you can actually see. If the scene appears safe, return risk_level NONE with an empty risks array.',
    user: 'Describe only the safety risks you can clearly see in this image. Do not speculate about things not visible.',
  },
  'Retail Security': {
    system: 'You are a retail security analyst. Analyse the image and return a JSON object with: risk_level (HIGH/MEDIUM/LOW/NONE), summary (one sentence), and risks (array of {description, severity, category}).',
    user: 'Identify potential security concerns or suspicious activity in this retail environment.',
  },
};

interface VlmPromptEditorProps {
  thingName: string;
}

export const VlmPromptEditor: React.FC<VlmPromptEditorProps> = ({ thingName }) => {
  const { credentials, region } = useAuthenticatedAWS();
  const [systemPrompt, setSystemPrompt] = useState('');
  const [userPrompt, setUserPrompt] = useState('');
  const [inferenceInterval, setInferenceInterval] = useState(15);
  const [maxTokens, setMaxTokens] = useState(512);
  const [mode, setMode] = useState<'continuous' | 'triggered'>('continuous');
  const [triggerClasses, setTriggerClasses] = useState<string[]>(['person']);
  const [triggerCooldown, setTriggerCooldown] = useState(10);
  const [alertRules, setAlertRules] = useState<string[]>([]);
  const [smsEnabled, setSmsEnabled] = useState(false);
  const [smsCooldownSeconds, setSmsCooldownSeconds] = useState(300);
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!thingName || !credentials) return;
    let cancelled = false;

    const load = async () => {
      const config = await iotShadowService.getVlmConfig(thingName, credentials, region);
      if (cancelled) return;
      if (config) {
        setSystemPrompt(config.system_prompt);
        setUserPrompt(config.user_prompt);
        setInferenceInterval(config.inference_interval);
        setMaxTokens(config.max_tokens);
        setMode(config.mode);
        setTriggerClasses(config.trigger_classes);
        setTriggerCooldown(config.trigger_cooldown);
        setAlertRules(config.alert_rules);
        setSmsEnabled(config.sms_enabled ?? false);
        setSmsCooldownSeconds(config.sms_cooldown_seconds ?? 300);
      }
      setLoaded(true);
    };

    load();
    return () => { cancelled = true; };
  }, [thingName, credentials, region]);

  const handleApply = async () => {
    if (!thingName || !credentials) return;
    setSaveState('saving');
    try {
      const config: VlmConfig = {
        system_prompt: systemPrompt,
        user_prompt: userPrompt,
        inference_interval: inferenceInterval,
        max_tokens: maxTokens,
        mode,
        trigger_classes: triggerClasses,
        trigger_cooldown: triggerCooldown,
        alert_rules: alertRules,
        sms_enabled: smsEnabled,
        sms_cooldown_seconds: smsCooldownSeconds,
      };
      await iotShadowService.setVlmConfig(thingName, credentials, region, config);
      setSaveState('saved');
      setTimeout(() => setSaveState('idle'), 2000);
    } catch {
      setSaveState('error');
      setTimeout(() => setSaveState('idle'), 3000);
    }
  };

  const handlePreset = (name: string) => {
    const preset = PRESETS[name];
    if (preset) {
      setSystemPrompt(preset.system);
      setUserPrompt(preset.user);
    }
  };

  if (!loaded) {
    return <div className="vlm-prompt-editor vlm-prompt-editor--loading">Loading VLM config...</div>;
  }

  return (
    <div className="vlm-prompt-editor">
      <section className="vlm-prompt-editor__section">
        <h4 className="vlm-prompt-editor__section-title">Scenario</h4>
        <div className="vlm-prompt-editor__presets">
          <label className="vlm-prompt-editor__label">Preset</label>
          <select
            className="vlm-prompt-editor__select"
            onChange={(e) => handlePreset(e.target.value)}
            defaultValue=""
          >
            <option value="" disabled>Select a preset...</option>
            {Object.keys(PRESETS).map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
        <div className="vlm-prompt-editor__field">
          <label className="vlm-prompt-editor__label">System Prompt</label>
          <textarea
            className="vlm-prompt-editor__textarea"
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            rows={4}
          />
        </div>
        <div className="vlm-prompt-editor__field">
          <label className="vlm-prompt-editor__label">User Prompt</label>
          <textarea
            className="vlm-prompt-editor__textarea"
            value={userPrompt}
            onChange={(e) => setUserPrompt(e.target.value)}
            rows={3}
          />
        </div>
      </section>

      <section className="vlm-prompt-editor__section">
        <h4 className="vlm-prompt-editor__section-title">Assessment Mode</h4>
        <div className="vlm-prompt-editor__mode-toggle">
          <button
            className={`vlm-prompt-editor__mode-btn ${mode === 'continuous' ? 'vlm-prompt-editor__mode-btn--active' : ''}`}
            onClick={() => setMode('continuous')}
            type="button"
          >
            Continuous
          </button>
          <button
            className={`vlm-prompt-editor__mode-btn ${mode === 'triggered' ? 'vlm-prompt-editor__mode-btn--active' : ''}`}
            onClick={() => setMode('triggered')}
            type="button"
          >
            CV-Triggered
          </button>
        </div>
        {mode === 'triggered' && (
          <div className="vlm-prompt-editor__trigger-config">
            <div className="vlm-prompt-editor__field">
              <label className="vlm-prompt-editor__label">Trigger Classes</label>
              <input
                type="text"
                className="vlm-prompt-editor__input"
                value={triggerClasses.join(', ')}
                onChange={(e) => setTriggerClasses(e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                placeholder="person, truck, excavator"
              />
              <span className="vlm-prompt-editor__hint">Comma-separated CV detection labels</span>
            </div>
            <div className="vlm-prompt-editor__field">
              <label className="vlm-prompt-editor__label">Cooldown (s)</label>
              <input
                type="number"
                className="vlm-prompt-editor__input"
                value={triggerCooldown}
                onChange={(e) => setTriggerCooldown(Math.max(5, parseInt(e.target.value) || 10))}
                min={5}
                max={120}
              />
            </div>
          </div>
        )}
      </section>

      <section className="vlm-prompt-editor__section">
        <h4 className="vlm-prompt-editor__section-title">Parameters</h4>
        <div className="vlm-prompt-editor__row">
          <div className="vlm-prompt-editor__field vlm-prompt-editor__field--inline">
            <label className="vlm-prompt-editor__label">Interval (s)</label>
            <input
              type="number"
              className="vlm-prompt-editor__input"
              value={inferenceInterval}
              onChange={(e) => setInferenceInterval(Math.max(5, parseInt(e.target.value) || 15))}
              min={5}
              max={120}
            />
          </div>
          <div className="vlm-prompt-editor__field vlm-prompt-editor__field--inline">
            <label className="vlm-prompt-editor__label">Max Tokens</label>
            <input
              type="number"
              className="vlm-prompt-editor__input"
              value={maxTokens}
              onChange={(e) => setMaxTokens(Math.max(64, parseInt(e.target.value) || 256))}
              min={64}
              max={1024}
            />
          </div>
        </div>
      </section>

      <section className="vlm-prompt-editor__section">
        <h4 className="vlm-prompt-editor__section-title">Alert Rules</h4>
        <div className="vlm-prompt-editor__alert-rules">
          {alertRules.map((rule, i) => (
            <div key={i} className="vlm-prompt-editor__alert-rule-row">
              <input
                type="text"
                className="vlm-prompt-editor__input"
                value={rule}
                onChange={(e) => {
                  const updated = [...alertRules];
                  updated[i] = e.target.value;
                  setAlertRules(updated);
                }}
                placeholder="e.g. Alert if anyone is in the trench without a hard hat"
              />
              <button
                className="vlm-prompt-editor__rule-remove"
                onClick={() => setAlertRules(alertRules.filter((_, idx) => idx !== i))}
                type="button"
                aria-label="Remove rule"
              >
                &times;
              </button>
            </div>
          ))}
          {alertRules.length < 3 && (
            <button
              className="vlm-prompt-editor__rule-add"
              onClick={() => setAlertRules([...alertRules, ''])}
              type="button"
            >
              + Add Rule
            </button>
          )}
        </div>
        <div className="vlm-prompt-editor__sms-config">
          <div className="vlm-prompt-editor__field">
            <label className="vlm-prompt-editor__label">SMS Notifications</label>
            <div className="vlm-prompt-editor__mode-toggle">
              <button
                className={`vlm-prompt-editor__mode-btn ${!smsEnabled ? 'vlm-prompt-editor__mode-btn--active' : ''}`}
                onClick={() => setSmsEnabled(false)}
                type="button"
              >
                Off
              </button>
              <button
                className={`vlm-prompt-editor__mode-btn ${smsEnabled ? 'vlm-prompt-editor__mode-btn--active' : ''}`}
                onClick={() => setSmsEnabled(true)}
                type="button"
              >
                On
              </button>
            </div>
          </div>
          {smsEnabled && (
            <div className="vlm-prompt-editor__field">
              <label className="vlm-prompt-editor__label">SMS Cooldown (seconds)</label>
              <input
                type="number"
                className="vlm-prompt-editor__input"
                value={smsCooldownSeconds}
                onChange={(e) => setSmsCooldownSeconds(Math.max(60, parseInt(e.target.value) || 300))}
                min={60}
                max={3600}
              />
              <span className="vlm-prompt-editor__hint">Minimum time between SMS for the same rule</span>
            </div>
          )}
        </div>
      </section>

      <button
        className="vlm-prompt-editor__apply"
        onClick={handleApply}
        disabled={saveState === 'saving'}
      >
        {saveState === 'saving' ? 'Applying...' : saveState === 'saved' ? 'Applied ✓' : saveState === 'error' ? 'Failed ✗' : 'Apply'}
      </button>
    </div>
  );
};
