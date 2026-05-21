# VLM Integration Design

Edge Vision Language Model integration for scene risk analysis, running alongside existing CV models on Ubuntu Core with OpenVINO.

## Goals

- Run a VLM on the edge device for deeper scene analysis (workplace safety risk assessment)
- Manage VLM models using the same shadow-driven snap component provisioning as CV models
- Display VLM risk assessments in the React dashboard alongside the live video stream
- Allow the user to view and modify the VLM prompt from the React app in real time

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Edge Device (Ubuntu Core)                                   │
│                                                              │
│  ┌──────────────────┐   ┌──────────────────┐               │
│  │  InferenceHandler │   │   VlmHandler      │               │
│  │  (CV model)       │   │   (VLM model)     │               │
│  │  - OVMS gRPC      │   │   - OpenVINO GenAI│               │
│  │  - 1 Hz           │   │   - 10-30s cycle  │               │
│  │  → camera/inference│   │   → camera/vlm    │               │
│  └──────────────────┘   └──────────────────┘               │
│           │                       │                          │
│           │     ┌─────────────┐   │                          │
│           └────►│ KvsProducer │◄──┘  (both read snapshots)   │
│                 │ (snapshots) │                               │
│                 └─────────────┘                               │
│                                                              │
│  ┌──────────────────────────────────────┐                   │
│  │  ModelManagerCore                     │                   │
│  │  - Provisions CV + VLM models         │                   │
│  │  - Snap component install             │                   │
│  │  - Shadow reported state (both types) │                   │
│  └──────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
         │ MQTT                        │ IoT Data Plane (boto3)
         ▼                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Cloud (IoT Core + Shadow)                                   │
│  - model-config shadow (CV + VLM models, prompts)           │
│  - MQTT topics: camera/inference, camera/vlm                 │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  React Web App                                               │
│  - Video overlay (CV detections + risk level badge)          │
│  - VLM risk assessment panel (right of video)                │
│  - VLM analysis timeline (full width, below)                 │
│  - Prompt editor (settings drawer)                           │
│  - Model selector (CV + VLM independently)                   │
└─────────────────────────────────────────────────────────────┘
```

Key principles:
- VlmHandler is a new Greengrass component, separate from InferenceHandler
- Both read frames from the same snapshot directory written by KvsProducer
- ModelManagerCore handles provisioning for both CV and VLM models, distinguished by a `type` field
- VLM prompt config lives in the `model-config` shadow as a `vlm_config` section
- VLM results publish to a dedicated MQTT topic (`camera/vlm`)

## VLM Runtime

The VLM runs via the OpenVINO GenAI Python API (`openvino_genai.VLMPipeline`). This provides:
- Native OpenVINO hardware acceleration (CPU/GPU/NPU)
- Tokenizer management and KV-cache for autoregressive generation
- Direct model loading from OpenVINO IR files on disk

OVMS is not used for VLM inference because VLM text generation is stateful and iterative (autoregressive token-by-token), which does not map to OVMS's stateless tensor-in/tensor-out predict API.

## Shadow Schema

The existing `model-config` named shadow is extended. No new shadows are introduced.

### Desired State

```json
{
  "state": {
    "desired": {
      "models": {
        "faster-rcnn": { "source": "snap", "type": "cv" },
        "llava-phi": { "source": "snap", "type": "vlm" }
      },
      "active_model": "faster-rcnn",
      "active_vlm_model": "llava-phi",
      "vlm_config": {
        "system_prompt": "You are a workplace safety analyst. Analyse the image and return a JSON object with: risk_level (HIGH/MEDIUM/LOW/NONE), summary (one sentence), and risks (array of {description, severity, category}).",
        "user_prompt": "Assess workplace safety risks visible in this scene.",
        "inference_interval": 15,
        "max_tokens": 256
      }
    }
  }
}
```

### Reported State

```json
{
  "state": {
    "reported": {
      "models": {
        "faster-rcnn": {
          "status": "ready",
          "type": "cv",
          "model_metadata": { "..." }
        },
        "llava-phi": {
          "status": "ready",
          "type": "vlm",
          "model_metadata": {
            "model_name": "llava-phi",
            "version": "1.0.0",
            "architecture": "llava",
            "max_tokens": 512,
            "local_path": "/snap/ovms-engine/components/mnt/model-llava-phi/x1"
          }
        }
      },
      "active_model": "faster-rcnn",
      "active_vlm_model": "llava-phi",
      "vlm_config": {
        "system_prompt": "...",
        "user_prompt": "...",
        "inference_interval": 15,
        "max_tokens": 256
      }
    }
  }
}
```

Design decisions:
- `active_model` and `active_vlm_model` are independent fields, allowing CV and VLM models to be switched without affecting each other
- `active_model` is owned by InferenceHandler (reports it). `active_vlm_model` is owned by VlmHandler (reports it). ModelManagerCore does not write either field.
- `vlm_config` lives in the shadow (not in the model manifest) so prompts can be updated from the React app without redeployment
- The `type` field (`"cv"` or `"vlm"`) on each model entry lets each component filter for relevant models
- `inference_interval` in `vlm_config` controls how often the VLM runs (tunable during demos)

## VlmHandler Component

New Greengrass component: `com.example.VlmHandler`

### Lifecycle

```
Startup:
  1. Read shadow → get active_vlm_model + vlm_config
  2. Load model from local_path via VLMPipeline(model_path)
  3. Subscribe to shadow delta (active_vlm_model, vlm_config changes)
  4. Enter inference loop

Inference loop (every inference_interval seconds):
  1. Read latest snapshot from shared directory
  2. Build generation prompt from system_prompt + user_prompt
  3. Call pipeline.generate(prompt, image, max_tokens)
  4. Parse JSON response (with fallback for malformed output)
  5. Publish to camera/vlm MQTT topic
  6. Report timing stats

Delta handling:
  - active_vlm_model changed → unload current, load new model, report
  - vlm_config changed → update prompts/interval in-place (no model reload needed)
```

### MQTT Payload Schema

Topic: `camera/vlm`

```json
{
  "timestamp": 1779348123.4,
  "model_id": "llava-phi",
  "model_name": "llava-phi",
  "inference_time_ms": 4200,
  "prompt": {
    "system": "You are a workplace safety analyst...",
    "user": "Assess risks in this scene..."
  },
  "response": {
    "risk_level": "HIGH",
    "summary": "Person operating machinery without safety guard in place",
    "risks": [
      {
        "description": "Operator's hand within 30cm of unguarded blade",
        "severity": "HIGH",
        "category": "machinery"
      },
      {
        "description": "No safety goggles visible",
        "severity": "MEDIUM",
        "category": "ppe"
      }
    ]
  },
  "raw_output": "{ ... raw VLM text output ... }"
}
```

### Output Parsing Strategy

- System prompt instructs VLM to return JSON matching the schema above
- VlmHandler attempts `json.loads()` on the generation output
- If parse fails: publish with `response: null` and `raw_output` containing the unstructured text
- React app handles both cases (structured rendering when available, raw text fallback)
- This graceful degradation is important since small VLMs may not always produce valid JSON

### Recipe

- Component: `com.example.VlmHandler`
- Dependencies: `aws.greengrass.TokenExchangeService ^2.0.0`
- Access control: MQTT proxy for `camera/vlm` publish + `$aws/things/*/shadow/name/model-config/update/delta` subscribe
- Artifacts: `vlm_handler.py`, `cloud_shadow.py`, `get-pip.py`, `requirements.txt`
- Environment variables: `AWS_IOT_THING_NAME`, `SNAPSHOT_DIR`
- Python requirements: `openvino`, `openvino-genai`, `Pillow`, `boto3`, `awsiotsdk`

## ModelManagerCore Changes

Minimal changes to the existing component.

### Behaviour Changes

1. **Type-aware OVMS config**: When a model with `type: "vlm"` reaches `ready` status, do NOT add it to OVMS's `models_config.json`. VLM models are loaded directly by VlmHandler.

2. **Seed vlm_config defaults**: After the first VLM model reaches `ready`, if no `vlm_config` exists in the shadow reported state, seed it from the model's manifest defaults.

3. **Report type field**: Include `type` from the desired state when reporting model entries.

### VLM Model Manifest

VLM snap components contain a `manifest.json` with additional fields:

```json
{
  "model_name": "llava-phi",
  "version": "1.0.0",
  "type": "vlm",
  "architecture": "llava",
  "max_tokens": 512,
  "default_system_prompt": "You are a workplace safety analyst. Analyse the image and return a JSON object with: risk_level (HIGH/MEDIUM/LOW/NONE), summary (one sentence), and risks (array of {description, severity, category}).",
  "default_user_prompt": "Assess workplace safety risks visible in this scene."
}
```

The `default_system_prompt` and `default_user_prompt` seed the shadow's `vlm_config` on first install. If `vlm_config` already exists (user has customised it), manifest defaults are ignored.

## React App Changes

### Layout (normal screen, >= 1024px)

```
┌─────────────────────────────────────────────────────────────────┐
│ Header                                                           │
├────────────────────────────────────┬────────────────────────────┤
│                                    │  VLM Risk Assessment        │
│   KVS Video Stream                 │  ┌──────────────────────┐  │
│   + CV bounding box overlay        │  │ ● HIGH  risk badge   │  │
│   + Risk level badge (top-right)   │  │ Summary text...      │  │
│                                    │  │ ─────────────────    │  │
│                                    │  │ Risks:               │  │
│                                    │  │  ▸ description (SEV) │  │
│                                    │  │  ▸ description (SEV) │  │
│                                    │  │ ─────────────────    │  │
│                                    │  │ ⏱ 4.2s  |  model    │  │
│                                    │  └──────────────────────┘  │
├────────────────────────────────────┴────────────────────────────┤
│  VLM Analysis Timeline (full width, horizontal scroll)           │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                 │
│  │07:21 │ │07:06 │ │06:51 │ │06:36 │ │06:21 │                  │
│  │● HIGH│ │● MED │ │● LOW │ │● MED │ │● HIGH│                  │
│  │ text │ │ text │ │ text │ │ text │ │ text │                  │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

### Layout (narrow screen, < 1024px)

Video stacks above VLM panel, timeline below both.

### Removed

The existing `InferencePanel` component is removed. CV detection results are conveyed entirely via bounding box overlays on the video stream.

### New Components

**VlmPanel** — Right of video, shows latest VLM risk assessment:
- Risk level badge (colour-coded: red HIGH, amber MEDIUM, green LOW, grey NONE)
- Summary text
- Expandable risk list with severity and category
- Inference time and model name
- Staleness indicator (time since last result)
- Compact prompt preview (expandable)

**VlmTimeline** — Full-width below video+panel:
- Horizontal scrolling list of assessment cards
- Each card: timestamp, risk level badge, summary
- Colour-coded left border per risk level
- Most recent at left
- Last ~20 entries retained
- Click to expand full detail

**VlmPromptEditor** — In the settings slide-out drawer (left):
- System prompt textarea
- User prompt textarea
- Preset dropdown (workplace safety, traffic monitoring, retail security)
- Apply button (writes to `desired.vlm_config` in shadow)
- Shows sync state (current vs pending)

**Model Selector Extension** — Existing `ModelSelector` extended:
- Two groups: "CV Model" and "VLM Model"
- CV selection writes `desired.active_model`
- VLM selection writes `desired.active_vlm_model`
- Models filtered by `type` field from reported state

### Data Flow

- New MQTT subscription: `camera/vlm` topic (same MqttContext pattern)
- New hook: `useVlmResults()` — stores latest result + history array
- Shadow reads/writes for `vlm_config`: via existing `iotShadowService`
- New type: `VlmResult` interface matching the MQTT payload schema

### Video Overlay Addition

Small risk level badge in the top-right corner of the video overlay:
- Shows current risk level from latest VLM result
- Colour matches the risk panel badge
- Does not obscure CV bounding boxes

## Settings Drawer (Left Panel)

Extended layout:

```
┌─────────────────────┐
│ Data Sources         │
│  MQTT topic          │
│  Thing name          │
├─────────────────────┤
│ Inference Controls   │
│  Confidence threshold│
│  CV Model selector   │
│  VLM Model selector  │
├─────────────────────┤
│ VLM Prompt           │
│  System prompt [___] │
│  User prompt   [___] │
│  Presets: [▾ ...]    │
│  [Apply]             │
└─────────────────────┘
```

## Risks and Mitigations

### Risk 1: Snap confinement with openvino-genai (HIGH)

The `openvino-genai` wheel includes compiled C++ libraries that mmap model files and create temporary files for tokenizer state. In strict snap confinement, file access is restricted.

**Symptoms if this fails:** Segfault or permission error when VLMPipeline loads a model or during token generation.

**Fallback options (ordered by preference):**
1. **Env var workaround**: Set `TMPDIR`, `XDG_CACHE_HOME`, and OpenVINO cache dir to the component's work directory (writable in strict confinement)
2. **Dedicated vlm-engine snap**: Package the OpenVINO GenAI runtime into a new snap with content interfaces (mirrors the `ovms-engine` pattern for GStreamer/KVS)
3. **Devmode during validation**: Use `--devmode` confinement to identify exactly which paths need access, then add targeted snap interfaces

**Validation step (do early):** Before building the full component, pip-install `openvino-genai` in a venv on the device and run a minimal `VLMPipeline` load + generate to confirm it works within confinement.

### Risk 2: VLM model size vs device memory (MEDIUM)

Small VLMs (LLaVA-Phi-3, MobileVLM) are 2-4GB. The device needs enough RAM to hold both the OVMS-served CV model and the VLM simultaneously.

**Mitigation:** Target quantized models (INT4/INT8) which reduce memory by 2-4x. Document minimum RAM requirements per supported VLM model.

### Risk 3: VLM output quality with small models (MEDIUM)

Small quantized VLMs may not reliably produce valid JSON or provide accurate risk assessments.

**Mitigation:** Graceful fallback (raw_output field), system prompt engineering with explicit JSON schema examples, and the ability to tune prompts live via the React app.

### Risk 4: Inference latency perception (LOW)

VLM inference takes 1-10+ seconds. Users may think the system is unresponsive.

**Mitigation:** Staleness indicator on VLM panel, inference time display, and the independent timer means the CV overlay keeps updating at 1Hz regardless of VLM pace.

## Model Candidates

Suitable VLMs for OpenVINO edge deployment (in order of size/capability):

| Model | Size (FP16) | Size (INT4) | Notes |
|-------|-------------|-------------|-------|
| MobileVLM v2 | ~3GB | ~1GB | Smallest, may struggle with JSON output |
| LLaVA-Phi-3 | ~4GB | ~1.5GB | Good balance of size and capability |
| InternVL2-2B | ~4GB | ~1.5GB | Strong visual understanding |
| LLaVA-1.5-7B | ~14GB | ~4GB | Most capable, needs significant RAM |

Model selection depends on target hardware. The architecture supports any model that can be converted to OpenVINO IR format and loaded via `openvino_genai.VLMPipeline`.

## Out of Scope

- Chat/conversation interface (single prompt per frame, not multi-turn)
- CV-triggered VLM analysis (future enhancement — periodic only for now)
- VLM training or fine-tuning at edge
- Multi-frame temporal analysis (each VLM call analyses a single frame independently)
- Cloud VLM fallback (edge-only for this spec)
