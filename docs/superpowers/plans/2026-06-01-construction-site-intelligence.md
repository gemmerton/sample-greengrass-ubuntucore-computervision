# Construction Site Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CV-triggered VLM assessment, interactive scene queries, and natural language alert rules to the edge computer vision system.

**Architecture:** Extends VlmInferenceHandler with mode switching (continuous/triggered), an MQTT query handler, and alert rule prompt injection. React UI gains mode controls, a scene query chat panel, and a dedicated alert banner. All processing stays on-device.

**Tech Stack:** Python (Greengrass component), React/TypeScript (Vite + Vitest), AWS IoT MQTT, IoT Device Shadow

---

## File Structure

### Python (Device-Side)

| File | Responsibility |
|------|---------------|
| `greengrass-components/artifacts/com.example.VlmInferenceHandler/1.0.0/vlm_handler.py` | Modify: add mode switching, CV trigger subscription, query handling, alert prompt injection |
| `tests/test_vlm_handler.py` | Create: unit tests for VlmHandler |

### TypeScript (React UI)

| File | Responsibility |
|------|---------------|
| `react-web/src/types/vlm.ts` | Modify: add alert, query, and mode types |
| `react-web/src/services/iotShadowService.ts` | Modify: extend VlmConfig handling for new fields |
| `react-web/src/components/controls/VlmPromptEditor.tsx` | Modify: add mode toggle, trigger class selector, cooldown, alert rule inputs |
| `react-web/src/components/controls/VlmPromptEditor.css` | Modify: styles for new controls |
| `react-web/src/hooks/useVlmResults.ts` | Modify: extract alerts from VLM messages |
| `react-web/src/hooks/useSceneQuery.ts` | Create: publish queries, subscribe to responses, manage Q&A history |
| `react-web/src/components/dashboard/SceneQueryPanel.tsx` | Create: chat-style Q&A interface |
| `react-web/src/components/dashboard/SceneQueryPanel.css` | Create: styles for scene query panel |
| `react-web/src/components/dashboard/AlertBanner.tsx` | Create: dedicated alert display + history |
| `react-web/src/components/dashboard/AlertBanner.css` | Create: styles for alert banner |
| `react-web/src/components/dashboard/Dashboard.tsx` | Modify: integrate AlertBanner and SceneQueryPanel |
| `react-web/src/components/dashboard/VlmPanel.tsx` | Modify: pass alerts through (no rendering change here — alerts go to AlertBanner) |

---

## Task 1: Extend TypeScript Types

**Files:**
- Modify: `react-web/src/types/vlm.ts`

- [ ] **Step 1: Add alert and query types to vlm.ts**

```typescript
// Add after existing VlmConfig interface:

export interface VlmAlert {
  rule: string;
  triggered: boolean;
  detail: string;
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

// Modify existing VlmResponse to add optional alerts:
// alerts?: VlmAlert[];

// Modify existing VlmConfig to add new fields:
// mode: 'continuous' | 'triggered';
// trigger_classes: string[];
// trigger_cooldown: number;
// alert_rules: string[];
```

The full updated `VlmResponse` interface:

```typescript
export interface VlmResponse {
  risk_level: RiskLevel;
  summary: string;
  risks: Risk[];
  alerts?: VlmAlert[];
}
```

The full updated `VlmConfig` interface:

```typescript
export interface VlmConfig {
  system_prompt: string;
  user_prompt: string;
  inference_interval: number;
  max_tokens: number;
  mode: 'continuous' | 'triggered';
  trigger_classes: string[];
  trigger_cooldown: number;
  alert_rules: string[];
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd react-web && npx tsc --noEmit 2>&1 | head -30`

Expected: Type errors in files that reference VlmConfig (iotShadowService, VlmPromptEditor) because they don't yet pass the new required fields. This is expected — we'll fix them in subsequent tasks.

- [ ] **Step 3: Commit**

```bash
git add react-web/src/types/vlm.ts
git commit -m "feat(types): add VLM alert, query, and mode types"
```

---

## Task 2: Update IoT Shadow Service

**Files:**
- Modify: `react-web/src/services/iotShadowService.ts`

- [ ] **Step 1: Update parseVlmConfigShadow to handle new fields**

In `parseVlmConfigShadow`, extend the `reported_vlm_config` parsing to include the new fields with sensible defaults:

```typescript
const reported_vlm_config: VlmConfig | null = rawVlmConfig
  ? {
      system_prompt: rawVlmConfig.system_prompt ?? '',
      user_prompt: rawVlmConfig.user_prompt ?? '',
      inference_interval: rawVlmConfig.inference_interval ?? 15,
      max_tokens: rawVlmConfig.max_tokens ?? 256,
      mode: rawVlmConfig.mode ?? 'continuous',
      trigger_classes: Array.isArray(rawVlmConfig.trigger_classes) ? rawVlmConfig.trigger_classes : ['person'],
      trigger_cooldown: rawVlmConfig.trigger_cooldown ?? 10,
      alert_rules: Array.isArray(rawVlmConfig.alert_rules) ? rawVlmConfig.alert_rules : [],
    }
  : null;
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd react-web && npx tsc --noEmit 2>&1 | head -30`

Expected: Remaining errors only in VlmPromptEditor (which still constructs a partial VlmConfig). We fix that next.

- [ ] **Step 3: Commit**

```bash
git add react-web/src/services/iotShadowService.ts
git commit -m "feat(shadow): parse new VLM config fields (mode, triggers, alerts)"
```

---

## Task 3: Update VlmPromptEditor — Mode Toggle and Trigger Controls

**Files:**
- Modify: `react-web/src/components/controls/VlmPromptEditor.tsx`
- Modify: `react-web/src/components/controls/VlmPromptEditor.css`

- [ ] **Step 1: Add state for new fields in VlmPromptEditor**

Add state variables after the existing ones (`maxTokens` state):

```typescript
const [mode, setMode] = useState<'continuous' | 'triggered'>('continuous');
const [triggerClasses, setTriggerClasses] = useState<string[]>(['person']);
const [triggerCooldown, setTriggerCooldown] = useState(10);
const [alertRules, setAlertRules] = useState<string[]>([]);
```

- [ ] **Step 2: Update the load effect to read new fields**

In the `load` async function inside `useEffect`, after setting existing fields:

```typescript
if (config) {
  setSystemPrompt(config.system_prompt);
  setUserPrompt(config.user_prompt);
  setInferenceInterval(config.inference_interval);
  setMaxTokens(config.max_tokens);
  setMode(config.mode);
  setTriggerClasses(config.trigger_classes);
  setTriggerCooldown(config.trigger_cooldown);
  setAlertRules(config.alert_rules);
}
```

- [ ] **Step 3: Update handleApply to include new fields**

```typescript
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
    };
    await iotShadowService.setVlmConfig(thingName, credentials, region, config);
    setSaveState('saved');
    setTimeout(() => setSaveState('idle'), 2000);
  } catch {
    setSaveState('error');
    setTimeout(() => setSaveState('idle'), 3000);
  }
};
```

- [ ] **Step 4: Add mode toggle UI**

After the presets section and before the system prompt field, add:

```tsx
<div className="vlm-prompt-editor__field">
  <label className="vlm-prompt-editor__label">Assessment Mode</label>
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
```

- [ ] **Step 5: Add alert rules UI**

After the max tokens row and before the Apply button, add:

```tsx
<div className="vlm-prompt-editor__field">
  <label className="vlm-prompt-editor__label">Alert Rules (max 3)</label>
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
</div>
```

- [ ] **Step 6: Add CSS for new controls**

Append to `VlmPromptEditor.css`:

```css
.vlm-prompt-editor__mode-toggle {
  display: flex;
  gap: 0;
  border-radius: 4px;
  overflow: hidden;
  border: 1px solid var(--border, #333);
}

.vlm-prompt-editor__mode-btn {
  flex: 1;
  padding: 6px 12px;
  background: var(--bg-subtle, #2a2a3e);
  color: var(--text-muted, #888);
  border: none;
  font-size: 0.8rem;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.vlm-prompt-editor__mode-btn--active {
  background: var(--accent, #3b82f6);
  color: #fff;
}

.vlm-prompt-editor__mode-btn:hover:not(.vlm-prompt-editor__mode-btn--active) {
  background: var(--bg-hover, #333);
}

.vlm-prompt-editor__trigger-config {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  background: var(--bg-subtle, #1e1e2e);
  border-radius: 4px;
  border: 1px solid var(--border, #333);
}

.vlm-prompt-editor__hint {
  font-size: 0.7rem;
  color: var(--text-muted, #666);
  margin-top: 2px;
}

.vlm-prompt-editor__alert-rules {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.vlm-prompt-editor__alert-rule-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

.vlm-prompt-editor__alert-rule-row .vlm-prompt-editor__input {
  flex: 1;
}

.vlm-prompt-editor__rule-remove {
  background: none;
  border: none;
  color: var(--text-muted, #888);
  font-size: 1.2rem;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
}

.vlm-prompt-editor__rule-remove:hover {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

.vlm-prompt-editor__rule-add {
  background: none;
  border: 1px dashed var(--border, #444);
  color: var(--text-muted, #888);
  padding: 6px;
  border-radius: 4px;
  font-size: 0.8rem;
  cursor: pointer;
}

.vlm-prompt-editor__rule-add:hover {
  border-color: var(--accent, #3b82f6);
  color: var(--accent, #3b82f6);
}
```

- [ ] **Step 7: Verify TypeScript compiles and dev server starts**

Run: `cd react-web && npx tsc --noEmit && npm run dev -- --host 2>&1 | head -10`

Expected: Clean compile, dev server starts.

- [ ] **Step 8: Commit**

```bash
git add react-web/src/components/controls/VlmPromptEditor.tsx react-web/src/components/controls/VlmPromptEditor.css
git commit -m "feat(react): add VLM mode toggle, trigger config, and alert rule editor"
```

---

## Task 4: VlmHandler — Mode Switching and CV-Triggered Assessment

**Files:**
- Modify: `greengrass-components/artifacts/com.example.VlmInferenceHandler/1.0.0/vlm_handler.py`
- Create: `tests/test_vlm_handler.py`

- [ ] **Step 1: Write tests for mode switching and trigger logic**

Create `tests/test_vlm_handler.py`:

```python
"""Unit tests for VlmHandler mode switching, CV triggers, and alert rules."""

import sys
import os
import json
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.VlmInferenceHandler', '1.0.0'
))

mock_clientv2 = MagicMock()
sys.modules['awsiot'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc.clientv2'] = mock_clientv2
sys.modules['requests'] = MagicMock()

import requests


@pytest.fixture
def mock_ipc_client():
    mock = MagicMock()
    return mock


@pytest.fixture
def handler(mock_ipc_client):
    mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client
    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'VLM_ENDPOINT': 'http://localhost:9090/v3/chat/completions',
    }):
        with patch('vlm_handler.CloudShadowClient') as mock_shadow:
            mock_shadow.return_value.get_shadow.return_value = {'state': {'reported': {}, 'desired': {}}}
            from vlm_handler import VlmHandler
            h = VlmHandler()
            h.ipc_client = mock_ipc_client
            yield h


class TestModeConfig:
    def test_default_mode_is_continuous(self, handler):
        assert handler.mode == 'continuous'

    def test_default_trigger_classes(self, handler):
        assert handler.trigger_classes == ['person']

    def test_default_trigger_cooldown(self, handler):
        assert handler.trigger_cooldown == 10

    def test_shadow_delta_updates_mode(self, handler):
        handler._apply_vlm_config({
            'mode': 'triggered',
            'trigger_classes': ['person', 'truck'],
            'trigger_cooldown': 15,
        })
        assert handler.mode == 'triggered'
        assert handler.trigger_classes == ['person', 'truck']
        assert handler.trigger_cooldown == 15


class TestTriggerLogic:
    def test_should_trigger_matches_class(self, handler):
        handler.mode = 'triggered'
        handler.trigger_classes = ['person', 'truck']
        detections = [{'label': 'person', 'score': 0.9, 'box': {}}]
        assert handler._should_trigger(detections) is True

    def test_should_trigger_no_match(self, handler):
        handler.mode = 'triggered'
        handler.trigger_classes = ['person']
        detections = [{'label': 'car', 'score': 0.9, 'box': {}}]
        assert handler._should_trigger(detections) is False

    def test_should_trigger_respects_cooldown(self, handler):
        handler.mode = 'triggered'
        handler.trigger_classes = ['person']
        handler.trigger_cooldown = 10
        handler._last_trigger_time = time.time() - 5  # 5s ago, within cooldown
        detections = [{'label': 'person', 'score': 0.9, 'box': {}}]
        assert handler._should_trigger(detections) is False

    def test_should_trigger_after_cooldown_expires(self, handler):
        handler.mode = 'triggered'
        handler.trigger_classes = ['person']
        handler.trigger_cooldown = 10
        handler._last_trigger_time = time.time() - 15  # 15s ago, past cooldown
        detections = [{'label': 'person', 'score': 0.9, 'box': {}}]
        assert handler._should_trigger(detections) is True


class TestAlertRules:
    def test_build_system_prompt_without_rules(self, handler):
        handler.system_prompt = 'You are a safety analyst.'
        handler.alert_rules = []
        result = handler._build_system_prompt()
        assert result == 'You are a safety analyst.'

    def test_build_system_prompt_with_rules(self, handler):
        handler.system_prompt = 'You are a safety analyst.'
        handler.alert_rules = ['Alert if no hard hat', 'Alert if in trench']
        result = handler._build_system_prompt()
        assert 'Alert if no hard hat' in result
        assert 'Alert if in trench' in result
        assert '"alerts"' in result

    def test_parse_response_with_alerts(self, handler):
        raw = json.dumps({
            'risk_level': 'HIGH',
            'summary': 'Unsafe scene',
            'risks': [],
            'alerts': [{'rule': 'No hard hat', 'triggered': True, 'detail': 'Worker without PPE'}]
        })
        result = handler._parse_response(raw)
        assert result['alerts'][0]['rule'] == 'No hard hat'

    def test_parse_response_without_alerts(self, handler):
        raw = json.dumps({
            'risk_level': 'LOW',
            'summary': 'Safe scene',
            'risks': []
        })
        result = handler._parse_response(raw)
        assert result.get('alerts', []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/gemmerto/local-dev/Git-Github/sample-greengrass-ubuntucore-computervision && python -m pytest tests/test_vlm_handler.py -v 2>&1 | tail -20`

Expected: FAIL — `handler.mode` attribute doesn't exist, `_should_trigger` method doesn't exist, etc.

- [ ] **Step 3: Implement mode switching in VlmHandler**

In `vlm_handler.py`, add to `__init__` after existing attributes:

```python
self.mode = 'continuous'
self.trigger_classes = ['person']
self.trigger_cooldown = 10
self.alert_rules = []
self._last_trigger_time = 0
self._pending_query = None
```

Add new method `_apply_vlm_config`:

```python
def _apply_vlm_config(self, vlm_config):
    """Apply VLM config fields from shadow delta or initial load."""
    if vlm_config.get("system_prompt"):
        self.system_prompt = vlm_config["system_prompt"]
    if vlm_config.get("user_prompt"):
        self.user_prompt = vlm_config["user_prompt"]
    if vlm_config.get("inference_interval"):
        self.inference_interval = int(vlm_config["inference_interval"])
    if vlm_config.get("max_tokens"):
        self.max_tokens = int(vlm_config["max_tokens"])
    if "mode" in vlm_config:
        self.mode = vlm_config["mode"]
    if "trigger_classes" in vlm_config:
        self.trigger_classes = vlm_config["trigger_classes"]
    if "trigger_cooldown" in vlm_config:
        self.trigger_cooldown = int(vlm_config["trigger_cooldown"])
    if "alert_rules" in vlm_config:
        self.alert_rules = vlm_config["alert_rules"]
    logger.info("VLM config updated: mode=%s, interval=%ds, trigger_classes=%s",
                self.mode, self.inference_interval, self.trigger_classes)
    self._report_vlm_config()
```

Update `_on_shadow_delta` to use the new method — replace the `if "vlm_config" in state:` block:

```python
if "vlm_config" in state:
    self._apply_vlm_config(state["vlm_config"])
```

Update `_load_config` to read new fields — in the vlm_config section after existing fields:

```python
self.mode = vlm_config.get("mode", "continuous")
self.trigger_classes = vlm_config.get("trigger_classes", ["person"])
self.trigger_cooldown = vlm_config.get("trigger_cooldown", 10)
self.alert_rules = vlm_config.get("alert_rules", [])
```

- [ ] **Step 4: Implement `_should_trigger` method**

```python
def _should_trigger(self, detections):
    """Check if CV detections should trigger a VLM assessment."""
    if self.mode != 'triggered':
        return False
    now = time.time()
    if now - self._last_trigger_time < self.trigger_cooldown:
        return False
    for det in detections:
        if det.get('label', '').lower() in [c.lower() for c in self.trigger_classes]:
            return True
    return False
```

- [ ] **Step 5: Implement `_build_system_prompt` method**

```python
def _build_system_prompt(self):
    """Build the full system prompt, injecting alert rules if defined."""
    prompt = self.system_prompt
    if not self.alert_rules:
        return prompt
    rules_text = "\n".join(f"{i+1}. {rule}" for i, rule in enumerate(self.alert_rules) if rule.strip())
    if not rules_text:
        return prompt
    prompt += (
        "\n\nAdditionally, evaluate the following alert rules against the scene. "
        "For each rule that is TRIGGERED, include it in a separate \"alerts\" array in your JSON response. "
        "Each alert object has: {rule (the original rule text), triggered (boolean), detail (one sentence explaining why it triggered)}. "
        "Only include rules that are currently triggered.\n\n"
        f"Rules:\n{rules_text}"
    )
    return prompt
```

- [ ] **Step 6: Update `_parse_response` to extract alerts**

Replace the existing `_parse_response` method:

```python
def _parse_response(self, raw_output):
    try:
        text = raw_output.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        parsed = json.loads(text)
        if "risk_level" in parsed and "summary" in parsed:
            result = {
                "risk_level": parsed["risk_level"],
                "summary": parsed["summary"],
                "risks": parsed.get("risks", []),
                "alerts": parsed.get("alerts", []),
            }
            return result
    except (json.JSONDecodeError, IndexError, KeyError):
        pass
    return None
```

- [ ] **Step 7: Update `_inference_cycle` to use `_build_system_prompt`**

In `_inference_cycle`, replace:
```python
if self.system_prompt:
    messages.append({"role": "system", "content": self.system_prompt})
```

with:
```python
system_prompt = self._build_system_prompt()
if system_prompt:
    messages.append({"role": "system", "content": system_prompt})
```

- [ ] **Step 8: Subscribe to CV inference topic for triggers**

Add a method to subscribe to CV output:

```python
def _subscribe_to_cv_inference(self):
    """Subscribe to camera/inference to receive CV detection results."""
    cv_topic = "camera/inference"
    self.ipc_client.subscribe_to_iot_core(
        topic_name=cv_topic,
        qos="1",
        on_stream_event=self._on_cv_inference,
        on_stream_error=lambda e: logger.error("CV inference stream error: %s", e),
        on_stream_closed=lambda: logger.warning("CV inference stream closed"),
    )
    logger.info("Subscribed to CV inference: %s", cv_topic)

def _on_cv_inference(self, event):
    """Handle incoming CV inference results — trigger VLM if configured."""
    if self.mode != 'triggered':
        return
    try:
        payload = json.loads(event.message.payload)
        detections = payload.get("results", {}).get("detections", [])
        if self._should_trigger(detections):
            self._last_trigger_time = time.time()
            logger.info("CV trigger fired: detected %s", [d['label'] for d in detections if d.get('label', '').lower() in [c.lower() for c in self.trigger_classes]])
            self._inference_cycle()
    except Exception as e:
        logger.error("Failed to handle CV inference event: %s", e)
```

Call `self._subscribe_to_cv_inference()` in the `run()` method after `_subscribe_to_shadow_delta()`.

- [ ] **Step 9: Update the main loop to respect mode**

Replace the `run()` method's while loop:

```python
def run(self):
    self._subscribe_to_shadow_delta()
    self._subscribe_to_cv_inference()
    self._subscribe_to_queries()
    self._load_config()

    while True:
        if not self._endpoint_healthy():
            logger.info("VLM endpoint not available at %s, waiting...", self.vlm_endpoint)
            time.sleep(10)
            continue

        # Handle pending query (pre-empts scheduled assessment)
        if self._pending_query:
            try:
                self._handle_query(self._pending_query)
            except Exception as e:
                logger.error("Query handling failed: %s", e)
            self._pending_query = None

        # Only run scheduled inference in continuous mode
        if self.mode == 'continuous':
            try:
                self._inference_cycle()
            except Exception as e:
                logger.error("VLM inference cycle failed: %s", e)
                traceback.print_exc()

        time.sleep(self.inference_interval)
```

- [ ] **Step 10: Update `_report_vlm_config` to include new fields**

```python
def _report_vlm_config(self):
    self.shadow_client.update_reported({
        "vlm_config": {
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
            "inference_interval": self.inference_interval,
            "max_tokens": self.max_tokens,
            "mode": self.mode,
            "trigger_classes": self.trigger_classes,
            "trigger_cooldown": self.trigger_cooldown,
            "alert_rules": self.alert_rules,
        }
    })
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `cd /Users/gemmerto/local-dev/Git-Github/sample-greengrass-ubuntucore-computervision && python -m pytest tests/test_vlm_handler.py -v`

Expected: All tests pass.

- [ ] **Step 12: Commit**

```bash
git add greengrass-components/artifacts/com.example.VlmInferenceHandler/1.0.0/vlm_handler.py tests/test_vlm_handler.py
git commit -m "feat(vlm-handler): add mode switching, CV triggers, and alert rule injection"
```

---

## Task 5: VlmHandler — Scene Query Handling

**Files:**
- Modify: `greengrass-components/artifacts/com.example.VlmInferenceHandler/1.0.0/vlm_handler.py`
- Modify: `tests/test_vlm_handler.py`

- [ ] **Step 1: Add query handling tests**

Append to `tests/test_vlm_handler.py`:

```python
class TestQueryHandling:
    def test_pending_query_set_on_message(self, handler):
        query = {'query_id': 'abc123', 'question': 'How many workers?', 'timestamp': 1717200000}
        event = MagicMock()
        event.message.payload = json.dumps(query).encode('utf-8')
        handler._on_query_message(event)
        assert handler._pending_query == query

    def test_latest_query_wins(self, handler):
        q1 = {'query_id': 'q1', 'question': 'First?', 'timestamp': 1717200000}
        q2 = {'query_id': 'q2', 'question': 'Second?', 'timestamp': 1717200001}
        event1 = MagicMock()
        event1.message.payload = json.dumps(q1).encode('utf-8')
        event2 = MagicMock()
        event2.message.payload = json.dumps(q2).encode('utf-8')
        handler._on_query_message(event1)
        handler._on_query_message(event2)
        assert handler._pending_query['query_id'] == 'q2'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vlm_handler.py::TestQueryHandling -v`

Expected: FAIL — `_on_query_message` doesn't exist.

- [ ] **Step 3: Implement query subscription and handling**

Add to `vlm_handler.py`:

```python
QUERY_TOPIC = "camera/vlm-query"
RESPONSE_TOPIC = "camera/vlm-response"

def _subscribe_to_queries(self):
    """Subscribe to scene query topic."""
    self.ipc_client.subscribe_to_iot_core(
        topic_name=QUERY_TOPIC,
        qos="1",
        on_stream_event=self._on_query_message,
        on_stream_error=lambda e: logger.error("Query stream error: %s", e),
        on_stream_closed=lambda: logger.warning("Query stream closed"),
    )
    logger.info("Subscribed to query topic: %s", QUERY_TOPIC)

def _on_query_message(self, event):
    """Receive a scene query — stores latest only."""
    try:
        payload = json.loads(event.message.payload)
        if 'query_id' in payload and 'question' in payload:
            self._pending_query = payload
            logger.info("Query received: %s", payload.get('question', '')[:80])
    except Exception as e:
        logger.error("Failed to parse query message: %s", e)

def _handle_query(self, query):
    """Process a scene query: send question + image to VLM, publish response."""
    image_b64 = self._get_latest_snapshot_b64()
    if image_b64 is None:
        logger.warning("No snapshot available for query")
        return

    start_time = time.time()

    messages = [
        {"role": "system", "content": "Answer the user's question about the image concisely and factually."},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            {"type": "text", "text": query["question"]},
        ]},
    ]

    request_body = {
        "model": self._serving_model_name or self.active_model_id,
        "messages": messages,
        "max_tokens": self.max_tokens,
        "temperature": 0.1,
        "stream": False,
    }

    try:
        resp = requests.post(self.vlm_endpoint, json=request_body, timeout=120)
        if resp.status_code != 200:
            logger.error("VLM query API error %d: %s", resp.status_code, resp.text[:200])
            return
        result = resp.json()
    except requests.RequestException as e:
        logger.error("VLM query request failed: %s", e)
        return

    inference_time_ms = round((time.time() - start_time) * 1000, 1)
    answer = result.get("choices", [{}])[0].get("message", {}).get("content", "")

    response_payload = {
        "query_id": query["query_id"],
        "question": query["question"],
        "answer": answer,
        "timestamp": time.time(),
        "inference_time_ms": inference_time_ms,
    }

    try:
        encoded = json.dumps(response_payload).encode("utf-8")
        self.ipc_client.publish_to_iot_core(
            topic_name=RESPONSE_TOPIC,
            qos="1",
            payload=encoded,
        )
        logger.info("Published query response: %s (%.1fs)", query["query_id"], inference_time_ms / 1000)
    except Exception as e:
        logger.error("Failed to publish query response: %s", e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vlm_handler.py -v`

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add greengrass-components/artifacts/com.example.VlmInferenceHandler/1.0.0/vlm_handler.py tests/test_vlm_handler.py
git commit -m "feat(vlm-handler): add scene query handling via MQTT"
```

---

## Task 6: React — useSceneQuery Hook

**Files:**
- Create: `react-web/src/hooks/useSceneQuery.ts`

- [ ] **Step 1: Create the useSceneQuery hook**

```typescript
import { useState, useEffect, useCallback } from 'react';
import { useMqtt } from '../contexts/MqttContext';
import { mqttService } from '../services/mqttService';
import type { VlmQueryResponse } from '../types/vlm';

const QUERY_TOPIC = 'camera/vlm-query';
const RESPONSE_TOPIC = 'camera/vlm-response';
const MAX_HISTORY = 20;

export interface QueryHistoryEntry {
  query_id: string;
  question: string;
  answer: string | null;
  timestamp: number;
  inference_time_ms: number | null;
  pending: boolean;
}

export function useSceneQuery() {
  const { state } = useMqtt();
  const [history, setHistory] = useState<QueryHistoryEntry[]>([]);
  const [pendingQueryId, setPendingQueryId] = useState<string | null>(null);

  useEffect(() => {
    if (!state.lastMessage) return;
    if (state.lastMessage.topic !== RESPONSE_TOPIC) return;

    try {
      const parsed: VlmQueryResponse = JSON.parse(state.lastMessage.payload);
      if (parsed.query_id && parsed.answer) {
        setHistory((prev) =>
          prev.map((entry) =>
            entry.query_id === parsed.query_id
              ? { ...entry, answer: parsed.answer, inference_time_ms: parsed.inference_time_ms, pending: false }
              : entry
          )
        );
        setPendingQueryId(null);
      }
    } catch {
      // Not a valid response
    }
  }, [state.lastMessage]);

  const submitQuery = useCallback(async (question: string) => {
    if (!question.trim()) return;

    const query_id = crypto.randomUUID();
    const timestamp = Date.now() / 1000;

    const entry: QueryHistoryEntry = {
      query_id,
      question,
      answer: null,
      timestamp,
      inference_time_ms: null,
      pending: true,
    };

    setHistory((prev) => [entry, ...prev].slice(0, MAX_HISTORY));
    setPendingQueryId(query_id);

    const payload = JSON.stringify({ query_id, question, timestamp });
    await mqttService.publishMessage(QUERY_TOPIC, payload);
  }, []);

  const clearHistory = useCallback(() => {
    setHistory([]);
    setPendingQueryId(null);
  }, []);

  return { history, pendingQueryId, submitQuery, clearHistory };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd react-web && npx tsc --noEmit 2>&1 | grep useSceneQuery`

Expected: No errors for this file.

- [ ] **Step 3: Commit**

```bash
git add react-web/src/hooks/useSceneQuery.ts
git commit -m "feat(react): add useSceneQuery hook for MQTT-based scene queries"
```

---

## Task 7: React — SceneQueryPanel Component

**Files:**
- Create: `react-web/src/components/dashboard/SceneQueryPanel.tsx`
- Create: `react-web/src/components/dashboard/SceneQueryPanel.css`

- [ ] **Step 1: Create SceneQueryPanel component**

```typescript
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
```

- [ ] **Step 2: Create SceneQueryPanel CSS**

```css
.scene-query-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 200px;
}

.scene-query-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid var(--border, #333);
}

.scene-query-panel__title {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-primary, #eee);
  margin: 0;
}

.scene-query-panel__clear {
  background: none;
  border: none;
  color: var(--text-muted, #888);
  font-size: 0.75rem;
  cursor: pointer;
}

.scene-query-panel__clear:hover {
  color: var(--text-primary, #eee);
}

.scene-query-panel__history {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
  display: flex;
  flex-direction: column-reverse;
  gap: 10px;
}

.scene-query-panel__placeholder {
  color: var(--text-muted, #666);
  font-size: 0.8rem;
  text-align: center;
  padding: 20px;
}

.scene-query-panel__entry {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.scene-query-panel__question {
  font-size: 0.8rem;
  color: var(--text-primary, #eee);
}

.scene-query-panel__q-label {
  font-weight: 700;
  color: var(--accent, #3b82f6);
  margin-right: 4px;
}

.scene-query-panel__answer {
  font-size: 0.8rem;
  color: var(--text-secondary, #bbb);
  padding-left: 8px;
  border-left: 2px solid var(--border, #444);
}

.scene-query-panel__a-label {
  font-weight: 700;
  color: var(--text-muted, #888);
  margin-right: 4px;
}

.scene-query-panel__pending {
  color: var(--text-muted, #888);
  font-style: italic;
}

.scene-query-panel__time {
  font-size: 0.7rem;
  color: var(--text-muted, #666);
  margin-left: 8px;
}

.scene-query-panel__form {
  display: flex;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--border, #333);
}

.scene-query-panel__input {
  flex: 1;
  background: var(--bg-subtle, #2a2a3e);
  border: 1px solid var(--border, #333);
  border-radius: 4px;
  color: var(--text-primary, #eee);
  padding: 8px;
  font-size: 0.8rem;
}

.scene-query-panel__input:disabled {
  opacity: 0.6;
}

.scene-query-panel__submit {
  padding: 8px 14px;
  background: var(--accent, #3b82f6);
  color: #fff;
  border: none;
  border-radius: 4px;
  font-size: 0.8rem;
  cursor: pointer;
}

.scene-query-panel__submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.scene-query-panel__submit:hover:not(:disabled) {
  background: var(--accent-hover, #2563eb);
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd react-web && npx tsc --noEmit`

Expected: Clean compile.

- [ ] **Step 4: Commit**

```bash
git add react-web/src/components/dashboard/SceneQueryPanel.tsx react-web/src/components/dashboard/SceneQueryPanel.css
git commit -m "feat(react): add SceneQueryPanel chat-style component"
```

---

## Task 8: React — AlertBanner Component

**Files:**
- Create: `react-web/src/components/dashboard/AlertBanner.tsx`
- Create: `react-web/src/components/dashboard/AlertBanner.css`

- [ ] **Step 1: Create AlertBanner component**

```typescript
import React, { useState, useEffect } from 'react';
import type { VlmAlert } from '../../types/vlm';
import './AlertBanner.css';

interface AlertBannerProps {
  alerts: VlmAlert[];
  timestamp: number | null;
}

interface AlertHistoryEntry {
  alert: VlmAlert;
  timestamp: number;
  id: string;
}

const MAX_ALERT_HISTORY = 20;

export const AlertBanner: React.FC<AlertBannerProps> = ({ alerts, timestamp }) => {
  const [alertHistory, setAlertHistory] = useState<AlertHistoryEntry[]>([]);
  const [historyExpanded, setHistoryExpanded] = useState(false);

  useEffect(() => {
    if (!alerts || alerts.length === 0 || !timestamp) return;

    const newEntries: AlertHistoryEntry[] = alerts
      .filter((a) => a.triggered)
      .map((alert, i) => ({
        alert,
        timestamp,
        id: `${timestamp}-${i}`,
      }));

    if (newEntries.length > 0) {
      setAlertHistory((prev) => [...newEntries, ...prev].slice(0, MAX_ALERT_HISTORY));
    }
  }, [alerts, timestamp]);

  const activeAlerts = alerts?.filter((a) => a.triggered) ?? [];
  const hasActiveAlerts = activeAlerts.length > 0;

  if (!hasActiveAlerts && alertHistory.length === 0) {
    return null;
  }

  return (
    <div className={`alert-banner ${hasActiveAlerts ? 'alert-banner--active' : 'alert-banner--inactive'}`}>
      {hasActiveAlerts && (
        <div className="alert-banner__live">
          <span className="alert-banner__icon">&#9888;</span>
          <div className="alert-banner__alerts">
            {activeAlerts.map((alert, i) => (
              <div key={i} className="alert-banner__alert-item">
                <span className="alert-banner__rule">{alert.rule}</span>
                <span className="alert-banner__detail">{alert.detail}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {alertHistory.length > 0 && (
        <div className="alert-banner__history-section">
          <button
            className="alert-banner__history-toggle"
            onClick={() => setHistoryExpanded(!historyExpanded)}
            type="button"
          >
            Alert History ({alertHistory.length}) {historyExpanded ? '▾' : '▸'}
          </button>
          {historyExpanded && (
            <ul className="alert-banner__history-list">
              {alertHistory.map((entry) => (
                <li key={entry.id} className="alert-banner__history-item">
                  <span className="alert-banner__history-time">
                    {new Date(entry.timestamp * 1000).toLocaleTimeString()}
                  </span>
                  <span className="alert-banner__history-rule">{entry.alert.rule}</span>
                  <span className="alert-banner__history-detail">{entry.alert.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 2: Create AlertBanner CSS**

```css
.alert-banner {
  border-radius: 6px;
  overflow: hidden;
}

.alert-banner--active {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.alert-banner--inactive {
  background: var(--bg-subtle, #1e1e2e);
  border: 1px solid var(--border, #333);
}

.alert-banner__live {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  align-items: flex-start;
}

.alert-banner__icon {
  font-size: 1.2rem;
  color: #ef4444;
  flex-shrink: 0;
}

.alert-banner__alerts {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}

.alert-banner__alert-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.alert-banner__rule {
  font-size: 0.8rem;
  font-weight: 600;
  color: #ef4444;
}

.alert-banner__detail {
  font-size: 0.75rem;
  color: var(--text-secondary, #bbb);
}

.alert-banner__history-section {
  padding: 6px 12px 8px;
  border-top: 1px solid var(--border, #333);
}

.alert-banner__history-toggle {
  background: none;
  border: none;
  color: var(--text-muted, #888);
  font-size: 0.75rem;
  cursor: pointer;
  padding: 2px 0;
}

.alert-banner__history-toggle:hover {
  color: var(--text-primary, #eee);
}

.alert-banner__history-list {
  list-style: none;
  padding: 0;
  margin: 6px 0 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 150px;
  overflow-y: auto;
}

.alert-banner__history-item {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 0.7rem;
}

.alert-banner__history-time {
  color: var(--text-muted, #666);
  flex-shrink: 0;
}

.alert-banner__history-rule {
  color: var(--text-secondary, #bbb);
  font-weight: 500;
}

.alert-banner__history-detail {
  color: var(--text-muted, #888);
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd react-web && npx tsc --noEmit`

Expected: Clean compile.

- [ ] **Step 4: Commit**

```bash
git add react-web/src/components/dashboard/AlertBanner.tsx react-web/src/components/dashboard/AlertBanner.css
git commit -m "feat(react): add AlertBanner component with live alerts and history"
```

---

## Task 9: React — Update useVlmResults to Extract Alerts

**Files:**
- Modify: `react-web/src/hooks/useVlmResults.ts`

- [ ] **Step 1: Extend useVlmResults to expose alerts**

The hook already parses VlmResult which contains `response`. Since `VlmResponse` now includes the optional `alerts` field, no parsing change is needed — the alerts will be available via `latestResult.response?.alerts`. However, we'll add a convenience accessor:

```typescript
import { useState, useEffect, useCallback } from 'react';
import { useMqtt } from '../contexts/MqttContext';
import type { VlmResult, VlmAlert } from '../types/vlm';

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

  const latestAlerts: VlmAlert[] = latestResult?.response?.alerts ?? [];
  const latestTimestamp: number | null = latestResult?.timestamp ?? null;

  return { latestResult, history, clearHistory, latestAlerts, latestTimestamp };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd react-web && npx tsc --noEmit`

Expected: Clean compile.

- [ ] **Step 3: Commit**

```bash
git add react-web/src/hooks/useVlmResults.ts
git commit -m "feat(react): expose latestAlerts from useVlmResults hook"
```

---

## Task 10: React — Integrate AlertBanner and SceneQueryPanel into Dashboard

**Files:**
- Modify: `react-web/src/components/dashboard/Dashboard.tsx`

- [ ] **Step 1: Import new components**

Add imports at the top of Dashboard.tsx:

```typescript
import { AlertBanner } from './AlertBanner';
import { SceneQueryPanel } from './SceneQueryPanel';
```

- [ ] **Step 2: Update useVlmResults destructuring**

Change:
```typescript
const { latestResult: vlmLatestResult, history: vlmHistory } = useVlmResults();
```

to:
```typescript
const { latestResult: vlmLatestResult, history: vlmHistory, latestAlerts, latestTimestamp } = useVlmResults();
```

- [ ] **Step 3: Add AlertBanner above the content section**

Inside the `{credentials && (...)}` block, add `AlertBanner` just before the `<section className="dashboard__content">`:

```tsx
{credentials && (
  <>
    {latestAlerts.length > 0 && (
      <AlertBanner alerts={latestAlerts} timestamp={latestTimestamp} />
    )}
    <section className="dashboard__content" aria-label="Live video and analysis">
      ...
    </section>
    ...
  </>
)}
```

Wait — the spec says AlertBanner should also show history when no alerts are active. So render it unconditionally:

```tsx
{credentials && (
  <>
    <AlertBanner alerts={latestAlerts} timestamp={latestTimestamp} />
    <section className="dashboard__content" aria-label="Live video and analysis">
      ...
    </section>
    ...
  </>
)}
```

- [ ] **Step 4: Add SceneQueryPanel to the VLM panel area**

Add `SceneQueryPanel` below the VlmPanel in the aside:

```tsx
<aside className="dashboard__vlm-panel" aria-label="VLM Risk Assessment">
  <VlmPanel latestResult={vlmLatestResult} />
  <SceneQueryPanel />
</aside>
```

- [ ] **Step 5: Verify TypeScript compiles and dev server runs**

Run: `cd react-web && npx tsc --noEmit && npm run dev -- --host 2>&1 | head -10`

Expected: Clean compile, Vite starts.

- [ ] **Step 6: Commit**

```bash
git add react-web/src/components/dashboard/Dashboard.tsx
git commit -m "feat(react): integrate AlertBanner and SceneQueryPanel into dashboard"
```

---

## Task 11: Visual Testing and Polish

**Files:**
- Various CSS adjustments as needed

- [ ] **Step 1: Start the dev server and inspect the UI**

Run: `cd react-web && npm run dev -- --host`

Open in browser. Check:
- VLM settings panel: mode toggle renders, switches between Continuous/CV-Triggered
- Trigger config appears only in CV-Triggered mode
- Alert rules section: add/remove rules up to 3
- SceneQueryPanel renders below VlmPanel
- AlertBanner area is present (will be empty with no data)

- [ ] **Step 2: Fix any layout issues**

Adjust CSS in `Dashboard.css`, `SceneQueryPanel.css`, or `AlertBanner.css` as needed to ensure:
- AlertBanner doesn't collapse to nothing when empty (component returns null, which is correct)
- SceneQueryPanel doesn't overflow its container
- Mode toggle buttons are aligned properly

- [ ] **Step 3: Commit any CSS fixes**

```bash
git add -A
git commit -m "fix(react): polish layout for alert banner and scene query panel"
```

---

## Task 12: End-to-End Verification

- [ ] **Step 1: Run all Python tests**

Run: `cd /Users/gemmerto/local-dev/Git-Github/sample-greengrass-ubuntucore-computervision && python -m pytest tests/test_vlm_handler.py -v`

Expected: All pass.

- [ ] **Step 2: Run TypeScript type check**

Run: `cd react-web && npx tsc --noEmit`

Expected: Clean compile.

- [ ] **Step 3: Run React tests (if any exist for affected files)**

Run: `cd react-web && npx vitest run 2>&1 | tail -20`

Expected: All existing tests pass (no regressions).

- [ ] **Step 4: Final commit if any remaining changes**

```bash
git status
# If clean, done. If changes, stage and commit.
```
