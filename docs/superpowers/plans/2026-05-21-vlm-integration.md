# VLM Integration Implementation Plan

> **SUPERSEDED (2026-05-21):** Task 10 (VlmHandler component) and Task 13 (device validation) below describe the original OpenVINO GenAI direct-loading approach. The implementation was refactored to use an **inference snap HTTP API** approach instead — see commits `6755da4` and `320572b`. VlmHandler is now a lightweight HTTP client calling the snap's OpenAI-compatible API on port 9090. The inference snap uses OpenVINO internally for Intel hardware acceleration. Tasks 1-9, 11-12 (React app, shadow service, ModelManagerCore, deploy) remain accurate.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Vision Language Model component to the edge device for scene risk analysis, with prompt management via shadow and a React dashboard for displaying assessments.

**Architecture:** New `VlmHandler` Greengrass component calls a VLM inference snap's OpenAI-compatible HTTP API (`/v1/chat/completions`) with camera snapshots at a configurable interval, publishes structured risk assessments to MQTT. The inference snap runs OpenVINO internally for Intel hardware acceleration. React app subscribes and renders a risk panel, timeline, and prompt editor. Model provisioning reuses the existing shadow-driven snap component flow.

**Tech Stack:** Python (requests + HTTP API), Greengrass IPC (MQTT), boto3 (cloud shadow), React/TypeScript, AWS IoT Shadow

---

## File Structure

### New Files (Edge)

| File | Responsibility |
|------|---------------|
| `greengrass-components/artifacts/com.example.VlmHandler/1.0.0/vlm_handler.py` | Main VLM inference loop: load model, capture frame, generate, publish |
| `greengrass-components/artifacts/com.example.VlmHandler/1.0.0/cloud_shadow.py` | Copy of shared cloud shadow client |
| `greengrass-components/artifacts/com.example.VlmHandler/1.0.0/requirements.txt` | Python dependencies |
| `greengrass-components/recipes/com.example.VlmHandler-1.0.0.yaml` | Greengrass recipe |

### Modified Files (Edge)

| File | Change |
|------|--------|
| `greengrass-components/artifacts/com.example.ModelManagerCore/1.0.0/model_manager_core.py` | Type-aware OVMS config, vlm_config seeding |
| `deploy_greengrass_components.py` | Include VlmHandler in deployments |

### New Files (React)

| File | Responsibility |
|------|---------------|
| `react-web/src/types/vlm.ts` | VLM result and config TypeScript interfaces |
| `react-web/src/hooks/useVlmResults.ts` | Hook: subscribe to camera/vlm MQTT messages, maintain history |
| `react-web/src/components/dashboard/VlmPanel.tsx` | Risk assessment panel (right of video) |
| `react-web/src/components/dashboard/VlmPanel.css` | Styles for VLM panel |
| `react-web/src/components/dashboard/VlmTimeline.tsx` | Horizontal scrolling timeline of assessments |
| `react-web/src/components/dashboard/VlmTimeline.css` | Styles for timeline |
| `react-web/src/components/controls/VlmPromptEditor.tsx` | System/user prompt editor with presets |
| `react-web/src/components/controls/VlmPromptEditor.css` | Styles for prompt editor |

### Modified Files (React)

| File | Change |
|------|--------|
| `react-web/src/components/dashboard/Dashboard.tsx` | New layout: VlmPanel right of video, timeline below, remove InferencePanel |
| `react-web/src/components/dashboard/Dashboard.css` | Grid layout changes |
| `react-web/src/components/dashboard/InferenceOverlay.tsx` | Add risk level badge to overlay |
| `react-web/src/components/controls/ModelSelector.tsx` | Split into CV/VLM model groups |
| `react-web/src/services/iotShadowService.ts` | Add vlm_config read/write, active_vlm_model methods |
| `react-web/src/types/modelConfig.ts` | Add type field to ModelEntry, VlmConfig interface |

---

## Task 1: VLM TypeScript Types

**Files:**
- Create: `react-web/src/types/vlm.ts`
- Modify: `react-web/src/types/modelConfig.ts`

- [ ] **Step 1: Create VLM result types**

```typescript
// react-web/src/types/vlm.ts

export type RiskLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE';
export type RiskCategory = 'machinery' | 'ppe' | 'ergonomic' | 'environmental' | 'other';

export interface Risk {
  description: string;
  severity: RiskLevel;
  category: RiskCategory | string;
}

export interface VlmResponse {
  risk_level: RiskLevel;
  summary: string;
  risks: Risk[];
}

export interface VlmResult {
  timestamp: number;
  model_id: string;
  model_name: string;
  inference_time_ms: number;
  prompt: {
    system: string;
    user: string;
  };
  response: VlmResponse | null;
  raw_output: string;
}

export interface VlmConfig {
  system_prompt: string;
  user_prompt: string;
  inference_interval: number;
  max_tokens: number;
}
```

- [ ] **Step 2: Extend model config types**

Add `type` field to `ModelEntry` and add VLM shadow state fields in `react-web/src/types/modelConfig.ts`:

```typescript
export type ModelType = 'cv' | 'vlm';

export interface ModelEntry {
  status: ModelStatus;
  type?: ModelType;
  model_metadata: ModelMetadata;
  failure_reason?: string;
}

export interface ModelConfigShadowState {
  reported_active_model: string | null;
  reported_active_vlm_model: string | null;
  reported_models: ModelInventory;
  reported_vlm_config: VlmConfig | null;
}
```

Add the import at the top of `modelConfig.ts`:
```typescript
import type { VlmConfig } from './vlm';
```

- [ ] **Step 3: Commit**

```bash
git add react-web/src/types/vlm.ts react-web/src/types/modelConfig.ts
git commit -m "feat(types): add VLM result and config TypeScript interfaces"
```

---

## Task 2: IoT Shadow Service VLM Methods

**Files:**
- Modify: `react-web/src/services/iotShadowService.ts`

- [ ] **Step 1: Update parseModelConfigShadow to extract VLM fields**

In `iotShadowService.ts`, update the `parseModelConfigShadow` function to also extract `active_vlm_model` and `vlm_config` from the reported state:

```typescript
export function parseModelConfigShadow(payload: any): ModelConfigShadowState {
  const reported = payload?.state?.reported ?? {};
  const rawActiveModel = reported.active_model;
  const rawActiveVlmModel = reported.active_vlm_model;
  const rawModels = reported.models ?? {};
  const rawVlmConfig = reported.vlm_config;

  const reported_active_model =
    typeof rawActiveModel === 'string' && rawActiveModel.trim().length > 0
      ? rawActiveModel
      : null;

  const reported_active_vlm_model =
    typeof rawActiveVlmModel === 'string' && rawActiveVlmModel.trim().length > 0
      ? rawActiveVlmModel
      : null;

  const reported_models: Record<string, ModelEntry> = {};
  for (const [modelId, entry] of Object.entries(rawModels)) {
    if (typeof entry === 'object' && entry !== null) {
      const e = entry as any;
      reported_models[modelId] = {
        status: ['ready', 'installing', 'failed'].includes(e.status)
          ? e.status
          : 'failed',
        type: e.type === 'vlm' ? 'vlm' : 'cv',
        model_metadata: {
          model_name: e.model_metadata?.model_name ?? modelId,
          version: e.model_metadata?.version ?? 'unknown',
          input_shape: Array.isArray(e.model_metadata?.input_shape)
            ? e.model_metadata.input_shape
            : [],
          local_path: e.model_metadata?.local_path ?? '',
        },
        failure_reason: e.failure_reason,
      };
    }
  }

  const reported_vlm_config: VlmConfig | null = rawVlmConfig
    ? {
        system_prompt: rawVlmConfig.system_prompt ?? '',
        user_prompt: rawVlmConfig.user_prompt ?? '',
        inference_interval: rawVlmConfig.inference_interval ?? 15,
        max_tokens: rawVlmConfig.max_tokens ?? 256,
      }
    : null;

  return { reported_active_model, reported_active_vlm_model, reported_models, reported_vlm_config };
}
```

Add the import at the top:
```typescript
import { ModelConfigShadowState, ModelEntry } from '../types/modelConfig';
import type { VlmConfig } from '../types/vlm';
```

- [ ] **Step 2: Add setActiveVlmModel method**

```typescript
async setActiveVlmModel(
  thingName: string,
  credentials: any,
  region: string,
  modelId: string
): Promise<void> {
  const client = this.getClient(credentials, region);
  const payload = JSON.stringify({
    state: { desired: { active_vlm_model: modelId } },
  });
  const command = new UpdateThingShadowCommand({
    thingName,
    shadowName: MODEL_CONFIG_SHADOW_NAME,
    payload: new TextEncoder().encode(payload),
  });
  await client.send(command);
}
```

- [ ] **Step 3: Add getVlmConfig and setVlmConfig methods**

```typescript
async getVlmConfig(
  thingName: string,
  credentials: any,
  region: string
): Promise<VlmConfig | null> {
  const state = await this.getModelConfigShadow(thingName, credentials, region);
  return state?.reported_vlm_config ?? null;
}

async setVlmConfig(
  thingName: string,
  credentials: any,
  region: string,
  config: VlmConfig
): Promise<void> {
  const client = this.getClient(credentials, region);
  const payload = JSON.stringify({
    state: { desired: { vlm_config: config } },
  });
  const command = new UpdateThingShadowCommand({
    thingName,
    shadowName: MODEL_CONFIG_SHADOW_NAME,
    payload: new TextEncoder().encode(payload),
  });
  await client.send(command);
}
```

- [ ] **Step 4: Commit**

```bash
git add react-web/src/services/iotShadowService.ts
git commit -m "feat(shadow): add VLM config and active_vlm_model shadow methods"
```

---

## Task 3: useVlmResults Hook

**Files:**
- Create: `react-web/src/hooks/useVlmResults.ts`
- Modify: `react-web/src/components/dashboard/Dashboard.tsx` (MQTT topic change only)

- [ ] **Step 1: Create the VLM results hook**

```typescript
// react-web/src/hooks/useVlmResults.ts

import { useState, useEffect, useCallback } from 'react';
import { useMqtt } from '../contexts/MqttContext';
import type { VlmResult } from '../types/vlm';

const VLM_TOPIC = 'camera/vlm';
const MAX_HISTORY = 20;

export function useVlmResults() {
  const { state } = useMqtt();
  const [latestResult, setLatestResult] = useState<VlmResult | null>(null);
  const [history, setHistory] = useState<VlmResult[]>([]);

  useEffect(() => {
    if (!state.lastMessage) return;
    if (state.lastMessage.topic !== VLM_TOPIC) return;

    try {
      const parsed: VlmResult = JSON.parse(state.lastMessage.payload);
      if (parsed.timestamp && (parsed.response || parsed.raw_output)) {
        setLatestResult(parsed);
        setHistory((prev) => [parsed, ...prev].slice(0, MAX_HISTORY));
      }
    } catch {
      // Not a valid VLM message
    }
  }, [state.lastMessage]);

  const clearHistory = useCallback(() => {
    setHistory([]);
    setLatestResult(null);
  }, []);

  return { latestResult, history, clearHistory };
}
```

- [ ] **Step 2: Change MQTT default topic to wildcard**

In `Dashboard.tsx`, change the MqttProvider topic from `camera/inference` to `camera/#` so both hooks can receive their respective messages:

```typescript
<MqttProvider autoConnect={false} defaultTopic="camera/#">
```

- [ ] **Step 3: Commit**

```bash
git add react-web/src/hooks/useVlmResults.ts react-web/src/components/dashboard/Dashboard.tsx
git commit -m "feat(hooks): add useVlmResults hook, subscribe to camera/# wildcard"
```

---

## Task 4: VlmPanel Component

**Files:**
- Create: `react-web/src/components/dashboard/VlmPanel.tsx`
- Create: `react-web/src/components/dashboard/VlmPanel.css`

- [ ] **Step 1: Create VlmPanel component**

```typescript
// react-web/src/components/dashboard/VlmPanel.tsx

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
          <span className="vlm-panel__placeholder-icon">🔍</span>
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
                      <span
                        className="vlm-panel__risk-severity"
                        style={{ color: RISK_COLORS[risk.severity] }}
                      >
                        {risk.severity}
                      </span>
                      <span className="vlm-panel__risk-desc">{risk.description}</span>
                      <span className="vlm-panel__risk-category">{risk.category}</span>
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
        <span className="vlm-panel__inference-time">⏱ {(inference_time_ms / 1000).toFixed(1)}s</span>
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
```

- [ ] **Step 2: Create VlmPanel CSS**

```css
/* react-web/src/components/dashboard/VlmPanel.css */

.vlm-panel {
  background: var(--card-bg, #1a1a2e);
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  overflow-y: auto;
}

.vlm-panel--empty {
  justify-content: center;
  align-items: center;
}

.vlm-panel__placeholder {
  text-align: center;
  color: var(--text-muted, #888);
}

.vlm-panel__placeholder-icon {
  font-size: 2rem;
  display: block;
  margin-bottom: 8px;
}

.vlm-panel__placeholder-hint {
  font-size: 0.8rem;
  opacity: 0.7;
}

.vlm-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.vlm-panel__risk-badge {
  padding: 4px 12px;
  border-radius: 4px;
  font-weight: 700;
  font-size: 0.85rem;
  color: #fff;
  letter-spacing: 0.5px;
}

.vlm-panel__staleness {
  font-size: 0.75rem;
  color: var(--text-muted, #888);
}

.vlm-panel__summary {
  font-size: 0.95rem;
  color: var(--text-primary, #eee);
  line-height: 1.4;
  margin: 0;
}

.vlm-panel__risks-toggle {
  background: none;
  border: none;
  color: var(--text-secondary, #aaa);
  font-size: 0.8rem;
  cursor: pointer;
  padding: 0;
}

.vlm-panel__risks-list {
  list-style: none;
  padding: 0;
  margin: 8px 0 0 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.vlm-panel__risk-item {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 0.85rem;
}

.vlm-panel__risk-severity {
  font-weight: 600;
  font-size: 0.7rem;
  min-width: 48px;
}

.vlm-panel__risk-desc {
  color: var(--text-primary, #eee);
  flex: 1;
}

.vlm-panel__risk-category {
  font-size: 0.7rem;
  color: var(--text-muted, #888);
  background: var(--bg-subtle, #2a2a3e);
  padding: 2px 6px;
  border-radius: 3px;
}

.vlm-panel__raw {
  font-size: 0.8rem;
}

.vlm-panel__raw-label {
  color: var(--text-muted, #888);
  margin: 0 0 4px 0;
}

.vlm-panel__raw-output {
  background: var(--bg-subtle, #2a2a3e);
  padding: 8px;
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.75rem;
  max-height: 150px;
  overflow-y: auto;
}

.vlm-panel__footer {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: var(--text-muted, #888);
  border-top: 1px solid var(--border, #333);
  padding-top: 8px;
}

.vlm-panel__prompt-section {
  border-top: 1px solid var(--border, #333);
  padding-top: 8px;
}

.vlm-panel__prompt-toggle {
  background: none;
  border: none;
  color: var(--text-secondary, #aaa);
  font-size: 0.75rem;
  cursor: pointer;
  padding: 0;
}

.vlm-panel__prompt-content {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.vlm-panel__prompt-field label {
  font-size: 0.7rem;
  color: var(--text-muted, #888);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.vlm-panel__prompt-field p {
  margin: 2px 0 0 0;
  font-size: 0.8rem;
  color: var(--text-primary, #eee);
}
```

- [ ] **Step 3: Commit**

```bash
git add react-web/src/components/dashboard/VlmPanel.tsx react-web/src/components/dashboard/VlmPanel.css
git commit -m "feat(ui): add VlmPanel component for risk assessment display"
```

---

## Task 5: VlmTimeline Component

**Files:**
- Create: `react-web/src/components/dashboard/VlmTimeline.tsx`
- Create: `react-web/src/components/dashboard/VlmTimeline.css`

- [ ] **Step 1: Create VlmTimeline component**

```typescript
// react-web/src/components/dashboard/VlmTimeline.tsx

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
```

- [ ] **Step 2: Create VlmTimeline CSS**

```css
/* react-web/src/components/dashboard/VlmTimeline.css */

.vlm-timeline {
  background: var(--card-bg, #1a1a2e);
  border-radius: 8px;
  padding: 12px;
}

.vlm-timeline--empty {
  text-align: center;
  color: var(--text-muted, #888);
  font-size: 0.85rem;
  padding: 24px 12px;
}

.vlm-timeline__scroll {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 8px;
}

.vlm-timeline__card {
  flex: 0 0 180px;
  background: var(--bg-subtle, #2a2a3e);
  border-left: 4px solid #6b7280;
  border-radius: 4px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  cursor: pointer;
  border-top: none;
  border-right: none;
  border-bottom: none;
  text-align: left;
  color: inherit;
  font: inherit;
  transition: background 0.15s;
}

.vlm-timeline__card:hover {
  background: var(--bg-hover, #333350);
}

.vlm-timeline__card--expanded {
  flex: 0 0 280px;
}

.vlm-timeline__time {
  font-size: 0.7rem;
  color: var(--text-muted, #888);
}

.vlm-timeline__badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 0.7rem;
  font-weight: 700;
  color: #fff;
  align-self: flex-start;
}

.vlm-timeline__summary {
  font-size: 0.8rem;
  color: var(--text-primary, #eee);
  line-height: 1.3;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.vlm-timeline__detail {
  list-style: none;
  padding: 0;
  margin: 4px 0 0 0;
  font-size: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.vlm-timeline__detail li {
  color: var(--text-primary, #eee);
}
```

- [ ] **Step 3: Commit**

```bash
git add react-web/src/components/dashboard/VlmTimeline.tsx react-web/src/components/dashboard/VlmTimeline.css
git commit -m "feat(ui): add VlmTimeline horizontal scrolling component"
```

---

## Task 6: VlmPromptEditor Component

**Files:**
- Create: `react-web/src/components/controls/VlmPromptEditor.tsx`
- Create: `react-web/src/components/controls/VlmPromptEditor.css`

- [ ] **Step 1: Create VlmPromptEditor component**

```typescript
// react-web/src/components/controls/VlmPromptEditor.tsx

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
  'Traffic Monitoring': {
    system: 'You are a traffic safety analyst. Analyse the image and return a JSON object with: risk_level (HIGH/MEDIUM/LOW/NONE), summary (one sentence), and risks (array of {description, severity, category}).',
    user: 'Identify traffic hazards and unsafe driver or pedestrian behaviour in this scene.',
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
```

- [ ] **Step 2: Create VlmPromptEditor CSS**

```css
/* react-web/src/components/controls/VlmPromptEditor.css */

.vlm-prompt-editor {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.vlm-prompt-editor--loading {
  color: var(--text-muted, #888);
  font-size: 0.85rem;
}

.vlm-prompt-editor__label {
  display: block;
  font-size: 0.75rem;
  color: var(--text-muted, #888);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.vlm-prompt-editor__select,
.vlm-prompt-editor__textarea,
.vlm-prompt-editor__input {
  width: 100%;
  background: var(--bg-subtle, #2a2a3e);
  border: 1px solid var(--border, #333);
  border-radius: 4px;
  color: var(--text-primary, #eee);
  padding: 8px;
  font-size: 0.85rem;
  font-family: inherit;
}

.vlm-prompt-editor__textarea {
  resize: vertical;
  min-height: 60px;
}

.vlm-prompt-editor__row {
  display: flex;
  gap: 12px;
}

.vlm-prompt-editor__field--inline {
  flex: 1;
}

.vlm-prompt-editor__input {
  width: 100%;
}

.vlm-prompt-editor__apply {
  padding: 8px 16px;
  background: var(--accent, #3b82f6);
  color: #fff;
  border: none;
  border-radius: 4px;
  font-size: 0.85rem;
  cursor: pointer;
  transition: background 0.15s;
}

.vlm-prompt-editor__apply:hover:not(:disabled) {
  background: var(--accent-hover, #2563eb);
}

.vlm-prompt-editor__apply:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
```

- [ ] **Step 3: Commit**

```bash
git add react-web/src/components/controls/VlmPromptEditor.tsx react-web/src/components/controls/VlmPromptEditor.css
git commit -m "feat(ui): add VlmPromptEditor with presets and shadow sync"
```

---

## Task 7: Dashboard Layout Integration

**Files:**
- Modify: `react-web/src/components/dashboard/Dashboard.tsx`
- Modify: `react-web/src/components/dashboard/Dashboard.css`
- Modify: `react-web/src/components/dashboard/InferenceOverlay.tsx`

- [ ] **Step 1: Update Dashboard layout**

Replace the content section in `Dashboard.tsx`. Remove `InferencePanel` import and usage. Add VlmPanel, VlmTimeline, VlmPromptEditor, and useVlmResults:

Add imports at the top:
```typescript
import { VlmPanel } from './VlmPanel';
import { VlmTimeline } from './VlmTimeline';
import { VlmPromptEditor } from '../controls/VlmPromptEditor';
import { useVlmResults } from '../../hooks/useVlmResults';
```

Remove imports:
```typescript
// Remove: import { InferencePanel } from './InferencePanel';
```

In `DashboardContent`, add the VLM hook:
```typescript
const { latestResult: vlmLatestResult, history: vlmHistory } = useVlmResults();
```

Replace the content section (the `{credentials && (...)}` block) with:
```typescript
{credentials && (
  <>
    <section className="dashboard__content" aria-label="Live video and analysis">
      <article className="dashboard__card dashboard__card--video" style={{ position: 'relative' }}>
        <KvsPlayer
          streamName={(import.meta as any).env?.VITE_KVS_STREAM_NAME ?? ''}
          region={region ?? config.aws.region}
          credentials={credentials as unknown as AwsCredentialIdentity}
          onVideoReady={setVideoElement}
        />
        <InferenceOverlay result={latestResult} videoElement={videoElement} vlmRiskLevel={vlmLatestResult?.response?.risk_level ?? null} />
      </article>
      <aside className="dashboard__vlm-panel" aria-label="VLM Risk Assessment">
        <VlmPanel latestResult={vlmLatestResult} />
      </aside>
    </section>
    <section className="dashboard__timeline" aria-label="Analysis timeline">
      <VlmTimeline history={vlmHistory} />
    </section>
  </>
)}
```

In the settings drawer, add a VLM Prompt section after Inference Controls:
```typescript
<div className="dashboard__settings-section">
  <h3 className="dashboard__settings-heading">VLM Prompt</h3>
  <div className="dashboard__settings-stack">
    <VlmPromptEditor thingName={thingName} />
  </div>
</div>
```

- [ ] **Step 2: Update Dashboard CSS for new grid layout**

Add to `Dashboard.css`:
```css
.dashboard__content {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 16px;
  align-items: stretch;
}

.dashboard__vlm-panel {
  min-height: 300px;
}

.dashboard__timeline {
  margin-top: 16px;
}

@media (max-width: 1024px) {
  .dashboard__content {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 3: Add risk level badge to InferenceOverlay**

In `InferenceOverlay.tsx`, add a `vlmRiskLevel` prop and draw a badge in the top-right corner:

Update the interface:
```typescript
interface InferenceOverlayProps {
  result: InferenceResult | null;
  videoElement: HTMLVideoElement | null;
  vlmRiskLevel?: 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE' | null;
}
```

At the end of the canvas drawing logic (after drawing detections/classifications), add:
```typescript
if (vlmRiskLevel) {
  const badgeColors: Record<string, string> = {
    HIGH: '#ef4444',
    MEDIUM: '#f59e0b',
    LOW: '#22c55e',
    NONE: '#6b7280',
  };
  const color = badgeColors[vlmRiskLevel] ?? '#6b7280';
  const text = `RISK: ${vlmRiskLevel}`;
  ctx.font = 'bold 14px monospace';
  const metrics = ctx.measureText(text);
  const badgeX = canvas.width - metrics.width - 20;
  const badgeY = 10;
  ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
  ctx.fillRect(badgeX - 6, badgeY, metrics.width + 12, 22);
  ctx.fillStyle = color;
  ctx.fillText(text, badgeX, badgeY + 16);
}
```

- [ ] **Step 4: Commit**

```bash
git add react-web/src/components/dashboard/Dashboard.tsx react-web/src/components/dashboard/Dashboard.css react-web/src/components/dashboard/InferenceOverlay.tsx
git commit -m "feat(ui): integrate VLM panel, timeline, and risk badge into dashboard layout"
```

---

## Task 8: Model Selector VLM Support

**Files:**
- Modify: `react-web/src/components/controls/ModelSelector.tsx`

- [ ] **Step 1: Add VLM model group to ModelSelector**

The ModelSelector needs to separate models by type and provide independent switching. Update the component to:

1. Filter `models` into `cvModels` and `vlmModels` based on the `type` field
2. Track `activeVlmModelId` and `selectedVlmModelId` state
3. Load `reported_active_vlm_model` from the shadow state
4. On VLM model change, call `iotShadowService.setActiveVlmModel()`
5. Render two groups: "CV Model" section (existing) and "VLM Model" section (new)

Key additions to the existing component logic:

```typescript
const [activeVlmModelId, setActiveVlmModelId] = useState<string | null>(null);
const [selectedVlmModelId, setSelectedVlmModelId] = useState<string | null>(null);

// In loadShadow callback, add:
setActiveVlmModelId(state.reported_active_vlm_model);
setSelectedVlmModelId(state.reported_active_vlm_model);

// Filter models:
const cvModels = Object.fromEntries(
  Object.entries(models).filter(([_, m]) => m.type !== 'vlm')
);
const vlmModels = Object.fromEntries(
  Object.entries(models).filter(([_, m]) => m.type === 'vlm')
);

// VLM switch handler:
const handleVlmSwitch = async () => {
  if (!selectedVlmModelId || selectedVlmModelId === activeVlmModelId) return;
  await iotShadowService.setActiveVlmModel(thingName, credentials, region, selectedVlmModelId);
  setActiveVlmModelId(selectedVlmModelId);
};
```

Render both groups in the JSX with appropriate labels.

- [ ] **Step 2: Commit**

```bash
git add react-web/src/components/controls/ModelSelector.tsx
git commit -m "feat(ui): extend ModelSelector with independent VLM model group"
```

---

## Task 9: ModelManagerCore Type-Aware Changes

**Files:**
- Modify: `greengrass-components/artifacts/com.example.ModelManagerCore/1.0.0/model_manager_core.py`

- [ ] **Step 1: Pass type through to reported state**

In `_handle_model_install`, after reading the manifest, include `type` from the desired model config in the reported entry. Update `_report_model_status` to accept and store a `model_type` parameter:

```python
def _report_model_status(self, model_id, status, reason=None, model_metadata=None, model_type="cv"):
    model_entry = {"status": status, "type": model_type}
    if reason:
        model_entry["reason"] = reason
    if model_metadata:
        model_entry["model_metadata"] = model_metadata

    self.reported_models[model_id] = model_entry
    self._update_shadow_reported()

    if status == "ready" and model_type != "vlm":
        self._regenerate_ovms_config()

    if status == "ready" and model_type == "vlm":
        self._seed_vlm_config_defaults(model_metadata)
```

- [ ] **Step 2: Add vlm_config seeding logic**

```python
def _seed_vlm_config_defaults(self, model_metadata):
    """Seed vlm_config in shadow from manifest defaults if not already set."""
    if not model_metadata:
        return
    shadow = self.shadow_client.get_shadow()
    reported = shadow.get("state", {}).get("reported", {})
    if reported.get("vlm_config"):
        logger.info("vlm_config already exists in shadow, not seeding defaults")
        return

    default_system = model_metadata.get("default_system_prompt", "")
    default_user = model_metadata.get("default_user_prompt", "")
    if not default_system:
        return

    vlm_config = {
        "system_prompt": default_system,
        "user_prompt": default_user,
        "inference_interval": 15,
        "max_tokens": model_metadata.get("max_tokens", 256),
    }
    self.shadow_client.update_reported({"vlm_config": vlm_config})
    logger.info("Seeded vlm_config defaults from model manifest")
```

- [ ] **Step 3: Update callers to pass model_type**

In `_handle_model_install` and `_install_snap_model` / `_install_s3_model`, extract `type` from the model_config dict and pass it through to `_report_model_status`:

```python
model_type = model_config.get("type", "cv")
# ... later when calling:
self._report_model_status(model_id, "ready", model_metadata=model_metadata, model_type=model_type)
```

Also for "installing" and "failed" status calls, pass the type:
```python
self._report_model_status(model_id, "installing", model_type=model_type)
# ... on failure:
self._report_model_status(model_id, "failed", reason=f"...", model_type=model_type)
```

- [ ] **Step 4: Update _regenerate_ovms_config to skip VLM models**

The existing `_regenerate_ovms_config` iterates `self.reported_models`. Add a filter:

```python
def _regenerate_ovms_config(self):
    ready_models = []
    for model_id, model_entry in self.reported_models.items():
        if not isinstance(model_entry, dict):
            continue
        if model_entry.get("status") != "ready":
            continue
        if model_entry.get("type") == "vlm":
            continue  # VLM models are not served by OVMS
        # ... rest unchanged
```

- [ ] **Step 5: Commit**

```bash
git add greengrass-components/artifacts/com.example.ModelManagerCore/1.0.0/model_manager_core.py
git commit -m "feat(ModelManagerCore): type-aware provisioning, skip OVMS for VLM models"
```

---

## Task 10: VlmHandler Greengrass Component

**Files:**
- Create: `greengrass-components/artifacts/com.example.VlmHandler/1.0.0/vlm_handler.py`
- Create: `greengrass-components/artifacts/com.example.VlmHandler/1.0.0/requirements.txt`
- Copy: `greengrass-components/artifacts/com.example.VlmHandler/1.0.0/cloud_shadow.py` (from shared)
- Copy: `greengrass-components/artifacts/com.example.VlmHandler/1.0.0/get-pip.py` (from another component)
- Create: `greengrass-components/recipes/com.example.VlmHandler-1.0.0.yaml`

- [ ] **Step 1: Create requirements.txt**

```
openvino>=2024.0
openvino-genai>=2024.0
Pillow>=10.0
boto3>=1.28
awsiotsdk>=1.0
```

- [ ] **Step 2: Create vlm_handler.py**

```python
"""VlmHandler - OpenVINO GenAI VLM inference for edge scene risk analysis.

Loads a VLM model via openvino_genai.VLMPipeline, captures frames from the
shared snapshot directory on a configurable interval, generates structured
risk assessments, and publishes results to camera/vlm via IoT Core MQTT.
"""

import os
import sys
import time
import json
import logging
import traceback
from pathlib import Path

from PIL import Image
import openvino_genai
import awsiot.greengrasscoreipc.clientv2 as clientv2

sys.path.insert(0, os.path.dirname(__file__))
from cloud_shadow import CloudShadowClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SHADOW_NAME = "model-config"
VLM_TOPIC = "camera/vlm"


class VlmHandler:

    def __init__(self):
        self.thing_name = os.environ.get("AWS_IOT_THING_NAME", "")
        self.snapshot_dir = os.environ.get(
            "SNAPSHOT_DIR",
            "/var/snap/aws-iot-greengrass/common/greengrass/v2/work/com.example.KvsProducer/snapshots"
        )
        self.ipc_client = clientv2.GreengrassCoreIPCClientV2()
        self.shadow_client = CloudShadowClient(self.thing_name, SHADOW_NAME)

        self.pipeline = None
        self.active_model_id = None
        self.system_prompt = ""
        self.user_prompt = ""
        self.inference_interval = 15
        self.max_tokens = 256

        logger.info("VlmHandler initialized: thing=%s snapshot_dir=%s", self.thing_name, self.snapshot_dir)

    def run(self):
        self._subscribe_to_shadow_delta()
        self._load_config_and_model()

        while True:
            if self.pipeline is None:
                logger.info("No VLM model loaded, waiting...")
                time.sleep(5)
                self._load_config_and_model()
                continue

            try:
                self._inference_cycle()
            except Exception as e:
                logger.error("VLM inference cycle failed: %s", e)
                traceback.print_exc()

            time.sleep(self.inference_interval)

    def _subscribe_to_shadow_delta(self):
        if not self.thing_name:
            return
        delta_topic = f"$aws/things/{self.thing_name}/shadow/name/{SHADOW_NAME}/update/delta"
        self.ipc_client.subscribe_to_iot_core(
            topic_name=delta_topic,
            qos="1",
            on_stream_event=self._on_shadow_delta,
            on_stream_error=lambda e: logger.error("Delta stream error: %s", e),
            on_stream_closed=lambda: logger.warning("Delta stream closed"),
        )
        logger.info("Subscribed to shadow delta: %s", delta_topic)

    def _on_shadow_delta(self, event):
        try:
            payload = json.loads(event.message.payload)
            state = payload.get("state", {})

            if "vlm_config" in state:
                vlm_config = state["vlm_config"]
                if vlm_config.get("system_prompt"):
                    self.system_prompt = vlm_config["system_prompt"]
                if vlm_config.get("user_prompt"):
                    self.user_prompt = vlm_config["user_prompt"]
                if vlm_config.get("inference_interval"):
                    self.inference_interval = int(vlm_config["inference_interval"])
                if vlm_config.get("max_tokens"):
                    self.max_tokens = int(vlm_config["max_tokens"])
                logger.info("VLM config updated: interval=%ds, max_tokens=%d", self.inference_interval, self.max_tokens)
                self._report_vlm_config()

            if "active_vlm_model" in state:
                new_model = state["active_vlm_model"]
                if new_model != self.active_model_id:
                    logger.info("VLM model switch requested: %s -> %s", self.active_model_id, new_model)
                    self._switch_model(new_model)
        except Exception as e:
            logger.error("Failed to handle shadow delta: %s", e)

    def _load_config_and_model(self):
        shadow = self.shadow_client.get_shadow()
        reported = shadow.get("state", {}).get("reported", {})
        desired = shadow.get("state", {}).get("desired", {})

        # Load vlm_config
        vlm_config = reported.get("vlm_config") or desired.get("vlm_config") or {}
        self.system_prompt = vlm_config.get("system_prompt", "")
        self.user_prompt = vlm_config.get("user_prompt", "")
        self.inference_interval = vlm_config.get("inference_interval", 15)
        self.max_tokens = vlm_config.get("max_tokens", 256)

        # Find active VLM model
        target_model_id = desired.get("active_vlm_model") or reported.get("active_vlm_model")
        if not target_model_id:
            # Pick first ready VLM model
            models = reported.get("models", {})
            target_model_id = next(
                (mid for mid, m in models.items()
                 if isinstance(m, dict) and m.get("type") == "vlm" and m.get("status") == "ready"),
                None,
            )

        if target_model_id and target_model_id != self.active_model_id:
            self._switch_model(target_model_id)

    def _switch_model(self, model_id):
        shadow = self.shadow_client.get_shadow()
        reported = shadow.get("state", {}).get("reported", {})
        models = reported.get("models", {})

        if model_id not in models:
            logger.warning("VLM model '%s' not in inventory", model_id)
            return

        entry = models[model_id]
        if entry.get("status") != "ready":
            logger.warning("VLM model '%s' not ready (status=%s)", model_id, entry.get("status"))
            return

        model_path = entry.get("model_metadata", {}).get("local_path")
        if not model_path:
            logger.error("VLM model '%s' has no local_path", model_id)
            return

        logger.info("Loading VLM model '%s' from %s", model_id, model_path)
        try:
            self.pipeline = openvino_genai.VLMPipeline(model_path, "CPU")
            self.active_model_id = model_id
            logger.info("VLM model '%s' loaded successfully", model_id)
            self._report_active_vlm_model()
        except Exception as e:
            logger.error("Failed to load VLM model '%s': %s", model_id, e)
            self.pipeline = None

    def _inference_cycle(self):
        image = self._get_latest_snapshot()
        if image is None:
            return

        prompt = self._build_prompt()
        start_time = time.time()

        try:
            generation_config = openvino_genai.GenerationConfig()
            generation_config.max_new_tokens = self.max_tokens
            raw_output = self.pipeline.generate(prompt, image=image, generation_config=generation_config)
        except Exception as e:
            logger.error("VLM generation failed: %s", e)
            return

        inference_time_ms = round((time.time() - start_time) * 1000, 1)

        response = self._parse_response(raw_output)

        payload = {
            "timestamp": time.time(),
            "model_id": self.active_model_id,
            "model_name": self.active_model_id,
            "inference_time_ms": inference_time_ms,
            "prompt": {
                "system": self.system_prompt,
                "user": self.user_prompt,
            },
            "response": response,
            "raw_output": raw_output,
        }

        self._publish(payload)

    def _build_prompt(self):
        parts = []
        if self.system_prompt:
            parts.append(self.system_prompt)
        if self.user_prompt:
            parts.append(self.user_prompt)
        return "\n\n".join(parts) if parts else "Describe what you see in this image."

    def _parse_response(self, raw_output):
        try:
            # Try to extract JSON from the output (VLM may wrap it in markdown code blocks)
            text = raw_output.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            parsed = json.loads(text)
            if "risk_level" in parsed and "summary" in parsed:
                return parsed
        except (json.JSONDecodeError, IndexError, KeyError):
            pass
        return None

    def _get_latest_snapshot(self):
        if not os.path.isdir(self.snapshot_dir):
            return None
        try:
            import glob
            snapshots = sorted(glob.glob(os.path.join(self.snapshot_dir, "snapshot_*.jpg")))
            if not snapshots:
                return None
            latest = snapshots[-1]
            if time.time() - os.path.getmtime(latest) > 30:
                return None
            return Image.open(latest)
        except Exception as e:
            logger.error("Failed to read snapshot: %s", e)
            return None

    def _publish(self, payload):
        try:
            encoded = json.dumps(payload).encode("utf-8")
            self.ipc_client.publish_to_iot_core(
                topic_name=VLM_TOPIC,
                qos="1",
                payload=encoded,
            )
            risk = payload.get("response", {})
            risk_level = risk.get("risk_level", "N/A") if risk else "PARSE_FAIL"
            logger.info("Published VLM result: risk=%s, time=%.1fs", risk_level, payload["inference_time_ms"] / 1000)
        except Exception as e:
            logger.error("Failed to publish VLM result: %s", e)

    def _report_active_vlm_model(self):
        if self.active_model_id:
            self.shadow_client.update_reported({"active_vlm_model": self.active_model_id})

    def _report_vlm_config(self):
        self.shadow_client.update_reported({
            "vlm_config": {
                "system_prompt": self.system_prompt,
                "user_prompt": self.user_prompt,
                "inference_interval": self.inference_interval,
                "max_tokens": self.max_tokens,
            }
        })


if __name__ == "__main__":
    handler = VlmHandler()
    handler.run()
```

- [ ] **Step 3: Create recipe**

```yaml
# greengrass-components/recipes/com.example.VlmHandler-1.0.0.yaml
---
RecipeFormatVersion: '2020-01-25'
ComponentName: com.example.VlmHandler
ComponentVersion: '1.0.0'
ComponentDescription: 'VLM inference handler - loads OpenVINO GenAI models for scene risk analysis'
ComponentPublisher: AWS
ComponentDependencies:
  aws.greengrass.TokenExchangeService:
    VersionRequirement: '^2.0.0'
ComponentConfiguration:
  DefaultConfiguration:
    SnapshotDir: "/var/snap/aws-iot-greengrass/common/greengrass/v2/work/com.example.KvsProducer/snapshots"
    accessControl:
      aws.greengrass.ipc.mqttproxy:
        com.example.VlmHandler:mqttproxy:1:
          policyDescription: 'Publish VLM analysis results to IoT Core'
          operations:
            - 'aws.greengrass#PublishToIoTCore'
          resources:
            - 'camera/vlm'
        com.example.VlmHandler:mqttproxy:2:
          policyDescription: 'Subscribe to model-config shadow delta for config changes'
          operations:
            - 'aws.greengrass#SubscribeToIoTCore'
          resources:
            - '$aws/things/*/shadow/name/model-config/update/delta'
Manifests:
- Platform:
    os: all
    runtime: '*'
  Lifecycle:
    Install:
      Timeout: 600
      Script: |
        /bin/bash -c 'set -e && \
        python3 -m venv --without-pip --system-site-packages venv/ && \
        source venv/bin/activate && \
        python3 {artifacts:path}/get-pip.py && \
        export TMPDIR="{work:path}" && \
        python3 -m pip install -r {artifacts:path}/requirements.txt && \
        deactivate'
    Run:
      Script: |
        /bin/bash -c 'set -e && \
        source venv/bin/activate && \
        export AWS_IOT_THING_NAME="{iot:thingName}" && \
        export SNAPSHOT_DIR="{configuration:/SnapshotDir}" && \
        export TMPDIR="{work:path}" && \
        export XDG_CACHE_HOME="{work:path}/.cache" && \
        export PYTHONUNBUFFERED=1 && \
        python3 {artifacts:path}/vlm_handler.py'
  Artifacts:
    - Uri: vlm_handler.py
      Unarchive: NONE
    - Uri: cloud_shadow.py
      Unarchive: NONE
    - Uri: get-pip.py
      Unarchive: NONE
    - Uri: requirements.txt
      Unarchive: NONE
```

- [ ] **Step 4: Copy shared files into artifact directory**

```bash
mkdir -p greengrass-components/artifacts/com.example.VlmHandler/1.0.0
cp greengrass-components/shared/cloud_shadow.py greengrass-components/artifacts/com.example.VlmHandler/1.0.0/
cp greengrass-components/artifacts/com.example.ModelManagerCore/1.0.0/get-pip.py greengrass-components/artifacts/com.example.VlmHandler/1.0.0/
```

- [ ] **Step 5: Commit**

```bash
git add greengrass-components/artifacts/com.example.VlmHandler/ greengrass-components/recipes/com.example.VlmHandler-1.0.0.yaml
git commit -m "feat(VlmHandler): new Greengrass component for VLM scene risk analysis"
```

---

## Task 11: Deploy Script Update

**Files:**
- Modify: `deploy_greengrass_components.py`

- [ ] **Step 1: Verify VlmHandler is auto-discovered**

The deploy script iterates all recipes in `greengrass-components/recipes/`. Since we added `com.example.VlmHandler-1.0.0.yaml`, it should be auto-discovered. Verify by checking the recipe iteration logic handles the new component without changes.

If the deploy script has hardcoded component lists, add `com.example.VlmHandler` to them. Otherwise no code change needed — just verify.

- [ ] **Step 2: Commit (if changes needed)**

```bash
git add deploy_greengrass_components.py
git commit -m "feat(deploy): include VlmHandler in deployment"
```

---

## Task 12: Remove InferencePanel

**Files:**
- Modify: `react-web/src/components/dashboard/Dashboard.tsx` (already done in Task 7)
- Delete: `react-web/src/components/dashboard/InferencePanel.tsx` (optional, can leave unused)

- [ ] **Step 1: Verify InferencePanel is no longer imported or used**

Confirm that `Dashboard.tsx` (updated in Task 7) no longer imports `InferencePanel`. The `useInferenceResults` hook is still used for the bounding box overlay — only the panel display is removed.

- [ ] **Step 2: Commit cleanup**

```bash
git rm react-web/src/components/dashboard/InferencePanel.tsx
git commit -m "refactor(ui): remove InferencePanel, CV results shown via overlay only"
```

---

## Task 13: Early Validation — OpenVINO GenAI on Device

**Files:** None (manual validation on device)

This is not a code task but a critical validation step that should happen early (ideally in parallel with React development).

- [ ] **Step 1: SSH to device and test openvino-genai install**

```bash
ssh -i /path/to/key user@device
python3 -m venv /tmp/vlm-test && source /tmp/vlm-test/bin/activate
export TMPDIR=/tmp/vlm-test
pip install openvino openvino-genai Pillow
python3 -c "import openvino_genai; print('openvino_genai imported successfully')"
```

- [ ] **Step 2: Test minimal VLMPipeline load (requires a model)**

This requires a converted model to be available on the device. If no model is available yet, the validation is: can `openvino_genai` import and initialise without segfault or permission errors?

- [ ] **Step 3: Document results**

If it fails: note the error and which fallback option (TMPDIR, dedicated snap, devmode) resolved it. Update the recipe environment variables accordingly.
