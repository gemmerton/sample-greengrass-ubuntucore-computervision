# Construction Site Intelligence — Scene Queries, Alert Rules, and CV-Triggered VLM

## Overview

Extends the existing VLM inference system with three capabilities tailored to construction site monitoring (excavator operations):

1. **VLM Assessment Modes** — Switch between continuous (timer-based) and CV-triggered inference
2. **Interactive Scene Queries** — One-shot natural language questions about the current frame
3. **Natural Language Alert Rules** — User-defined watchdog conditions evaluated every VLM cycle

All processing remains on-device (edge). No cloud inference.

## Architecture Context

Current system:
- **InferenceHandler** (CV): Captures frames, runs OVMS gRPC inference, publishes detections to `camera/inference`
- **VlmInferenceHandler** (VLM): Runs on a fixed timer, sends snapshots to VLM snap (OpenAI-compatible API on localhost:9090), publishes structured risk assessments to `camera/vlm`
- **React UI**: Displays video (KVS), CV bounding boxes, VLM risk panel, VLM timeline, and config editors
- **IoT Shadow** (`vlm-config`): Stores system/user prompts, inference interval, max tokens

---

## Feature 1: VLM Assessment Modes

### Shadow Config Extension

The `vlm-config` shadow gains three new fields:

```json
{
  "vlm_config": {
    "system_prompt": "...",
    "user_prompt": "...",
    "inference_interval": 15,
    "max_tokens": 256,
    "mode": "continuous",
    "trigger_classes": ["person", "truck"],
    "trigger_cooldown": 10
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `"continuous" \| "triggered"` | `"continuous"` | Assessment mode |
| `trigger_classes` | `string[]` | `["person"]` | CV detection labels that trigger VLM |
| `trigger_cooldown` | `number` (seconds) | `10` | Minimum gap between triggered assessments |

### Device-Side Behaviour (VlmInferenceHandler)

- **Continuous mode**: Unchanged — runs inference every `inference_interval` seconds.
- **Triggered mode**: Subscribes to `camera/inference` via IoT Core IPC. When a message arrives containing a detection with a label matching any entry in `trigger_classes`, initiates a VLM inference cycle. Respects `trigger_cooldown` to prevent flooding.
- Mode, trigger_classes, and trigger_cooldown are reactive to shadow deltas (same pattern as existing config fields).

### React UI

In the VLM settings panel (left drawer, VLM tab):
- A toggle/segmented control: "Continuous" / "CV-Triggered"
- When "CV-Triggered" is selected, show:
  - A multi-select or checkbox list of trigger classes (populated from the labels of the currently active CV model, read from `model-config` shadow)
  - A cooldown input (seconds, min 5, max 120)
- All saved to shadow via existing `setVlmConfig` pattern

---

## Feature 2: Interactive Scene Queries

### MQTT Topics

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `camera/vlm-query` | UI -> Device | User's question |
| `camera/vlm-response` | Device -> UI | VLM's answer |

### Message Schemas

**Request** (`camera/vlm-query`):
```json
{
  "query_id": "uuid-string",
  "question": "How many workers are near the trench?",
  "timestamp": 1717200000
}
```

**Response** (`camera/vlm-response`):
```json
{
  "query_id": "uuid-string",
  "question": "How many workers are near the trench?",
  "answer": "I can see 3 workers within approximately 2 metres of the trench edge...",
  "timestamp": 1717200005,
  "inference_time_ms": 4200
}
```

### Device-Side Behaviour (VlmInferenceHandler)

- Subscribes to `camera/vlm-query` via IoT Core IPC.
- At the start of each loop iteration (before scheduled/triggered assessment), checks for a pending query.
- If a query is pending: processes it using the latest snapshot with the user's question as the only user content. System prompt is a brief instruction: "Answer the user's question about the image concisely and factually." (No risk-assessment framing.) Publishes response to `camera/vlm-response`. Then resumes normal operation.
- If multiple queries arrive between cycles, only the latest is processed (prevents queue buildup).
- Queries work identically in both continuous and triggered modes.

### React UI

A chat-style panel — either a new section in the VLM area or accessible via its own drawer/tab:
- Text input at the bottom (submit on Enter or button click)
- Scrollable Q&A history above (session-only, not persisted)
- Each entry shows: question, answer text, inference time
- "Clear" button to reset history
- Visual indicator while a query is in-flight (waiting for response)
- Generates a UUID `query_id` for correlation

---

## Feature 3: Natural Language Alert Rules

### Shadow Config Extension

```json
{
  "vlm_config": {
    ...existing fields...,
    "alert_rules": [
      "Alert if anyone enters the excavation zone without a hard hat",
      "Alert if a worker is within the excavator swing radius while it is operating"
    ]
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `alert_rules` | `string[]` | `[]` | Up to 3 natural-language alert conditions |

### VLM Prompt Injection

When `alert_rules` is non-empty, the VlmHandler appends to the system prompt:

```
Additionally, evaluate the following alert rules against the scene. For each rule that is TRIGGERED, include it in a separate "alerts" array in your JSON response. Each alert object has: {rule (the original rule text), triggered (boolean), detail (one sentence explaining why it triggered)}. Only include rules that are currently triggered.

Rules:
1. <rule text>
2. <rule text>
```

### VLM Output Extension

The existing JSON response gains an optional `alerts` array:

```json
{
  "risk_level": "HIGH",
  "summary": "...",
  "risks": [...],
  "alerts": [
    {
      "rule": "Alert if anyone enters the excavation zone without a hard hat",
      "triggered": true,
      "detail": "Worker in orange vest near the trench is not wearing head protection"
    }
  ]
}
```

The `_parse_response` method in VlmHandler is extended to extract the `alerts` field alongside existing fields.

### MQTT Payload Extension

The `camera/vlm` payload includes the alerts:

```json
{
  "timestamp": 1717200000,
  "model_id": "gemma3",
  "inference_time_ms": 5000,
  "prompt": { "system": "...", "user": "..." },
  "response": {
    "risk_level": "HIGH",
    "summary": "...",
    "risks": [...],
    "alerts": [...]
  },
  "raw_output": "..."
}
```

### React UI — Alert Rule Editor

In the VLM settings panel, below the prompt editor:
- Up to 3 text inputs for natural-language rules
- Add/remove buttons (minimum 0, maximum 3)
- Saved to shadow as part of the VLM config (same Apply button)

### React UI — Alert Display

A dedicated alert section, visually distinct from the general risk panel:
- Positioned above or as a banner over the VLM panel
- When alerts trigger: red/amber styling, the rule text, and the detail explanation
- Alert history log: accumulates triggered alerts with timestamps (separate from VLM timeline)
- Alerts auto-dismiss visually after a period or manual dismiss
- When no alerts are active, the section is minimal/collapsed

---

## TypeScript Type Extensions

```typescript
// vlm.ts additions
export interface VlmAlert {
  rule: string;
  triggered: boolean;
  detail: string;
}

export interface VlmResponse {
  risk_level: RiskLevel;
  summary: string;
  risks: Risk[];
  alerts?: VlmAlert[];  // new
}

export interface VlmConfig {
  system_prompt: string;
  user_prompt: string;
  inference_interval: number;
  max_tokens: number;
  mode: 'continuous' | 'triggered';  // new
  trigger_classes: string[];          // new
  trigger_cooldown: number;           // new
  alert_rules: string[];              // new
}

export interface VlmQuery {
  query_id: string;
  question: string;
  timestamp: number;
}

export interface VlmQueryResponse {
  query_id: string;
  question: string;
  answer: string;
  timestamp: number;
  inference_time_ms: number;
}
```

---

## Component Summary

| Component | Changes |
|-----------|---------|
| `VlmInferenceHandler` (Python) | Add mode switching, `camera/inference` subscription for triggers, `camera/vlm-query` subscription for queries, alert rule prompt injection, cooldown logic |
| `VlmPromptEditor` (React) | Add mode toggle, trigger class selector, cooldown input, alert rule inputs |
| `VlmPanel` (React) | Extend to render alerts distinctly |
| New: `SceneQueryPanel` (React) | Chat-style Q&A interface |
| New: `AlertBanner` (React) | Dedicated alert display + history |
| `iotShadowService` (React) | Extend `setVlmConfig`/`getVlmConfig` for new fields |
| `useVlmResults` hook (React) | Extract alerts from VLM messages |
| New: `useSceneQuery` hook (React) | Publish queries, subscribe to responses, manage Q&A history |
| `vlm.ts` types | Add alert, query, mode types |

---

## Out of Scope

- Cloud inference or cloud-side alert evaluation
- Zone-based spatial triggers (drawing zones on the video)
- Persistent alert storage or notification integrations (email, SMS)
- Multi-turn conversational queries
- More than 3 simultaneous alert rules
