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
    system: 'You are a construction site safety analyst specialising in excavation and earthworks operations. Analyse the image and return a JSON object with: risk_level (HIGH/MEDIUM/LOW/NONE), summary (one sentence), and risks (array of {description, severity, category}). Focus on: worker proximity to excavator swing radius, PPE compliance (hard hats, hi-vis vests, safety boots), trench/excavation stability, overhead hazards, exclusion zone violations, and struck-by risks.',
    user: 'Assess construction site safety risks in this scene, with particular attention to excavator operations and worker positioning.',
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
  const [maxTokens, setMaxTokens] = useState(256);
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
