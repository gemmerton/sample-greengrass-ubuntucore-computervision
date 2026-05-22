# VLM Integration Design

Edge Vision Language Model integration for scene risk analysis, running alongside existing CV models on Ubuntu Core. The VLM runs inside a dedicated inference snap that uses OpenVINO for Intel hardware acceleration.

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
│  │  (CV model)       │   │   (Greengrass)    │               │
│  │  - OVMS gRPC      │   │   - HTTP client   │               │
│  │  - 1 Hz           │   │   - 10-30s cycle  │               │
│  │  → camera/inference│   │   → camera/vlm    │               │
│  └──────────────────┘   └────────┬───────────┘               │
│           │                       │ HTTP :9090               │
│           │     ┌─────────────┐   │  (base64 image in req)   │
│           └────►│ KvsProducer │◄──┘                          │
│                 │ (snapshots) │       ┌──────────────────┐   │
│                 └─────────────┘       │  VLM Inference   │   │
│                       ▲               │  Snap (e.g.      │   │
│                       │               │  qwen-vl)        │   │
│                       │               │  - OpenVINO      │   │
│                (VlmHandler reads      │  - OpenAI API    │   │
│                 snapshots, sends      └──────────────────┘   │
│                 to snap via HTTP)                             │
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
- VlmHandler is a lightweight HTTP client — the heavy VLM runtime lives in a dedicated inference snap
- The inference snap (e.g. `qwen-vl`) runs OpenVINO internally for Intel hardware acceleration, exposing an OpenAI-compatible API on port 9090
- VlmHandler reads snapshots from KvsProducer's shared directory and sends them as base64 images to the inference snap via HTTP
- ModelManagerCore handles provisioning for both CV and VLM models, distinguished by a `type` field
- VLM prompt config lives in the `model-config` shadow as a `vlm_config` section
- VLM results publish to a dedicated MQTT topic (`camera/vlm`)

## VLM Runtime

The VLM runs inside a dedicated **inference snap** installed on the Ubuntu Core device (e.g. `qwen-vl`, `gemma3`). The snap encapsulates:
- The VLM model weights (OpenVINO IR format)
- The OpenVINO runtime for Intel hardware acceleration (CPU/GPU/NPU)
- Tokenizer management and KV-cache for autoregressive generation
- An OpenAI-compatible HTTP API server on port 9090

VlmHandler does **not** load the model directly. It is a thin Greengrass component that:
1. Reads camera snapshots from the shared directory
2. Sends them as base64-encoded images to the snap's `/v1/chat/completions` endpoint
3. Parses the structured response and publishes to MQTT

This approach was chosen over direct `openvino_genai.VLMPipeline` usage because:
- **Snap confinement**: The VLM runtime's C++ libraries, mmap'd model files, and tokenizer temp files are fully contained within the snap's confinement, avoiding complex interface/plug requirements
- **Separation of concerns**: The inference runtime lifecycle (model loading, memory management, GPU allocation) is independent of the Greengrass component lifecycle
- **Reusability**: The same inference snap can be used by other consumers on the device
- **Upgradability**: The VLM model/runtime can be upgraded by refreshing the snap without redeploying the Greengrass component

OVMS is not used for VLM inference because VLM text generation is stateful and iterative (autoregressive token-by-token), which does not map to OVMS's stateless tensor-in/tensor-out predict API. The inference snap handles this statefulness internally.

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
  2. Poll inference snap health endpoint (GET /v1/models) until available
  3. Subscribe to shadow delta (active_vlm_model, vlm_config changes)
  4. Enter inference loop

Inference loop (every inference_interval seconds):
  1. Check inference snap health (skip cycle if unavailable)
  2. Read latest snapshot from shared directory
  3. Base64-encode the image
  4. POST to snap's /v1/chat/completions with system_prompt + user_prompt + image
  5. Parse JSON response (with fallback for malformed output)
  6. Publish to camera/vlm MQTT topic
  7. Report timing stats

Delta handling:
  - active_vlm_model changed → report new model ID (snap manages model loading)
  - vlm_config changed → update prompts/interval in-place (no restart needed)
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
- Environment variables: `AWS_IOT_THING_NAME`, `SNAPSHOT_DIR`, `VLM_ENDPOINT`
- Configuration: `VlmEndpoint` (default: `http://localhost:9090/v1/chat/completions`)
- Python requirements: `requests`, `boto3`, `awsiotsdk` (lightweight — no OpenVINO dependencies)

## ModelManagerCore Changes

Minimal changes to the existing component.

### Behaviour Changes

1. **Type-aware OVMS config**: When a model with `type: "vlm"` reaches `ready` status, do NOT add it to OVMS's `models_config.json`. VLM models are served by the inference snap, not OVMS.

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

### Risk 1: Inference snap availability (MEDIUM)

The VLM inference snap must be installed and running before VlmHandler can operate. If the snap is not installed, crashes, or is still loading the model, VlmHandler has no inference backend.

**Mitigation:** VlmHandler polls the snap's `/v1/models` health endpoint before each inference cycle. If unavailable, it logs and retries every 10 seconds. The React dashboard shows a "Waiting for VLM analysis..." placeholder until results arrive.

### Risk 2: VLM model size vs device memory (MEDIUM)

Small VLMs (Qwen-VL, Gemma3) are 2-4GB. The device needs enough RAM to hold both the OVMS-served CV model and the VLM simultaneously.

**Mitigation:** Target quantized models (INT4/INT8) which reduce memory by 2-4x. The inference snap handles model loading and memory management independently of Greengrass. Document minimum RAM requirements per supported VLM snap.

### Risk 3: VLM output quality with small models (MEDIUM)

Small quantized VLMs may not reliably produce valid JSON or provide accurate risk assessments.

**Mitigation:** Graceful fallback (raw_output field), system prompt engineering with explicit JSON schema examples, and the ability to tune prompts live via the React app.

### Risk 4: Inference latency perception (LOW)

VLM inference takes 1-10+ seconds. Users may think the system is unresponsive.

**Mitigation:** Staleness indicator on VLM panel, inference time display, and the independent timer means the CV overlay keeps updating at 1Hz regardless of VLM pace.

## Inference Snap Convention

VLM inference snaps follow these conventions:

| Property | Convention |
|----------|------------|
| API port | 9090 |
| API format | OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) |
| Image input | Base64-encoded JPEG in `image_url` content block |
| Runtime | OpenVINO (optimised for Intel CPU/GPU/NPU) |
| Install | `sudo snap install <snap-name>` |
| Model loading | Automatic on snap start (model weights bundled in snap) |

Example snaps: `qwen-vl`, `gemma3`

## Model Candidates

Suitable VLMs for inference snap deployment on Intel hardware (in order of size/capability):

| Model | Size (INT4) | Snap Name | Notes |
|-------|-------------|-----------|-------|
| Qwen-VL | ~2GB | `qwen-vl` | Good balance of size, vision capability, and JSON output |
| Gemma 3 | ~2.5GB | `gemma3` | Strong instruction following |
| LLaVA-Phi-3 | ~1.5GB | TBD | Smaller, may struggle with structured output |
| InternVL2-2B | ~1.5GB | TBD | Strong visual understanding |

Model selection depends on available snap packages and device RAM. All models use OpenVINO IR format internally within the snap.

## Out of Scope

- Chat/conversation interface (single prompt per frame, not multi-turn)
- CV-triggered VLM analysis (future enhancement — periodic only for now)
- VLM training or fine-tuning at edge
- Multi-frame temporal analysis (each VLM call analyses a single frame independently)
- Cloud VLM fallback (edge-only for this spec)
