# Unified Inference Pipeline Design

## Summary

Replace the static DetectionHandler and ClassificationHandler with a single
shadow-reactive InferenceHandler that dynamically adapts to whichever model is
active. Add bounding box / classification overlay to the React dashboard's KVS
video player, plus a structured results panel.

## Architecture

```
Camera (/dev/video1)
  │
  ├──► KvsProducer (GStreamer → KVS @ 15-30fps, unchanged)
  │
  └──► InferenceHandler (OpenCV capture @ configurable interval, e.g. 1 frame/sec)
           │
           ├── reads model-config local shadow → gets active model metadata
           ├── pre-processes frame based on model input_shape
           ├── calls OVMS gRPC (localhost:9000) with model_name from metadata
           ├── post-processes based on output structure (detection vs classification)
           └── publishes to local MQTT: camera/inference
                    │
                    └──► ShadowManager syncs to cloud
                         └──► React app subscribes via IoT Core WebSocket
                              ├── Overlays results on KVS video player
                              └── Shows structured results in side panel
```

## InferenceHandler Component

### Model selection

- Reads the `model-config` named shadow via Greengrass IPC (local shadow)
- Looks for an `active_model` field in desired state, OR uses the first model
  with `status: "ready"` in reported state
- On model change: re-reads metadata (input_shape, output_names, model_name),
  resets pre/post-processing pipeline. No restart needed.

### Frame capture

- Opens camera device directly via OpenCV (`cv2.VideoCapture`)
- Captures one frame every N seconds (configurable via shadow, default 1s)
- Same device as KvsProducer (`/dev/video1`) — V4L2 allows multiple readers
- Runs inside the `aws-iot-greengrass` snap which has the `camera` interface
- Resolution: match model input or capture at native and resize in pre-processing

### Pre-processing

Driven by model metadata from the shadow:
- `input_shape`: determines resize target (e.g., [1,3,320,544] for detection)
- `input_name`: determines the input tensor name for OVMS
- Format: NCHW (OpenVINO standard), BGR→RGB conversion, float32 normalisation

### Inference

- Uses `ovmsclient` gRPC to call OVMS at `localhost:9000`
- `client.predict({input_name: frame_tensor}, model_name)`
- Model name comes from shadow metadata (`model_name` field)

### Post-processing

Determined by model metadata `output_names`:
- If outputs include a detection-style tensor (e.g., `detection_out` with shape
  [1,1,N,7]): parse as SSD-style detections → extract boxes, labels, scores
- If outputs are classification-style (e.g., `prob` with shape [1,N]): parse as
  top-K class probabilities
- The handler doesn't hardcode model-specific logic — it uses output tensor
  shapes to determine the result type

### Publishing

Topic: `camera/inference` (local MQTT via Greengrass IPC, syncs to cloud)

Unified payload format:
```json
{
  "timestamp": 1779272406.123,
  "model_id": "faster-rcnn",
  "model_name": "faster_rcnn",
  "result_type": "detection",
  "results": {
    "detections": [
      {
        "label": "person",
        "score": 0.92,
        "box": { "xmin": 0.12, "ymin": 0.05, "xmax": 0.45, "ymax": 0.88 }
      }
    ],
    "count": 1
  },
  "inference_time_ms": 45,
  "frame_width": 544,
  "frame_height": 320
}
```

For classification:
```json
{
  "timestamp": 1779272407.456,
  "model_id": "efficientnet",
  "model_name": "efficientnet",
  "result_type": "classification",
  "results": {
    "classifications": [
      { "label": "person", "confidence": 0.87, "class_index": 1 }
    ]
  },
  "inference_time_ms": 12,
  "frame_width": 62,
  "frame_height": 62
}
```

### Configuration (via shadow and deployment config)

| Parameter | Source | Default |
|-----------|--------|---------|
| Camera device | Deployment config | /dev/video1 |
| Inference interval (seconds) | Shadow desired state | 1.0 |
| Confidence threshold | Shadow desired state | 0.5 |
| OVMS gRPC URL | Deployment config | localhost:9000 |
| Publish topic | Deployment config | camera/inference |

### Shadow interaction

- Reads from: `model-config` named shadow (local, via ShadowManager IPC)
- Watches for changes to: `active_model`, model `status`, confidence threshold
- Does NOT write to the shadow — ModelManagerCore owns reported state

## React Dashboard Changes

### Video overlay

- Subscribe to `camera/inference` via IoT Core MQTT WebSocket
- When `result_type === "detection"`: draw bounding boxes on a transparent
  `<canvas>` element positioned over the `<video>` KVS player
- Box coordinates are normalised (0-1), scale to video element dimensions
- Labels and confidence scores drawn above each box
- When `result_type === "classification"`: show top result as a text badge
  overlay in the corner of the video

### Video/inference timing

KVS HLS playback has ~5+ seconds latency. Inference results arrive via MQTT
at approximately the same effective delay (frame captured → inference → publish
→ MQTT delivery ≈ sub-second; but the corresponding video frame arrives via
KVS with the same ~5s HLS buffer delay). No explicit synchronisation needed —
both the video frame and its inference result reach the browser at roughly the
same time due to the shared pipeline latency.

The overlay simply displays the **latest** inference result. For a relatively
static camera scene (typical demo: people walking through frame), this produces
a visually coherent overlay.

### Results panel

- Slide-out panel (already exists as MessageFeed) repurposed/enhanced:
  - Model name and ID shown at top
  - Inference time (ms) shown
  - For detections: table of label / score / box coordinates
  - For classifications: ranked list of class / confidence
  - Live updating with each new MQTT message
  - Last N results kept (scrollable)

### Model switching UI

The existing `ModelSelector` component already updates the shadow. With the
unified handler watching the shadow, switching models in the UI will:
1. Update shadow desired `active_model`
2. ModelManagerCore installs new model if needed, reports ready
3. InferenceHandler picks up the new model metadata
4. Results start flowing with the new model
5. React UI updates overlay style based on `result_type`

## Components to create/modify

| Component | Action |
|-----------|--------|
| `com.example.InferenceHandler` | NEW — replaces Detection + Classification handlers |
| `com.example.DetectionHandler` | REMOVE from deployment |
| `com.example.ClassificationHandler` | REMOVE from deployment |
| `com.example.KvsProducer` | UNCHANGED |
| `com.example.ModelManagerCore` | UNCHANGED (already handles model lifecycle) |
| React: `InferenceOverlay.tsx` | NEW — canvas overlay on video |
| React: `InferencePanel.tsx` | NEW — structured results panel |
| React: `Dashboard.tsx` | MODIFY — integrate overlay and panel |

## Constraints (Ubuntu Core / snap confinement)

- Camera access requires `camera` interface on the Greengrass snap (already connected)
- OpenCV (`cv2`) needs to be installed in the component's venv — no system-level packages
- All inter-component communication via Greengrass IPC (local shadow, local MQTT)
- OVMS is accessed via network (localhost:9000) — requires no special interface
- Frame capture at low FPS (1/sec) to keep CPU usage reasonable on edge hardware

## Success criteria

1. Push a model to the shadow → InferenceHandler starts producing results within 10s
2. Switch model via React UI → results change to new model type within 15s
3. Bounding boxes visible on video overlay in React dashboard
4. Classification results shown as text overlay when classification model active
5. No camera device conflicts between KvsProducer and InferenceHandler
