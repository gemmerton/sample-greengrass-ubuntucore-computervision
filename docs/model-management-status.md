# Model Management - Status & Next Steps

## Status: Full demo pipeline working end-to-end (2026-05-20)

The complete inference pipeline is operational: shadow-driven model management,
live OVMS inference, real-time MQTT results, and React dashboard with bounding
box overlays and model switching.

### What works

1. **Shadow-driven model install**: Push `desired.models.<id>.source = "snap"` →
   ModelManagerCore downloads .comp from S3, sideloads via snapd, writes OVMS
   config via content interface, reports ready
2. **OVMS serving inference**: OpenVINO Model Server runs as snap daemon,
   hot-loads/unloads models from config file polling
3. **Unified InferenceHandler**: Reads frames from KvsProducer snapshots, calls
   OVMS gRPC, publishes results to `camera/inference` via IoT Core MQTT
4. **Dynamic model switching**: React app sets `desired.active_model` →
   InferenceHandler receives delta, switches model, reports back. ~2-3 second
   switch time.
5. **Shadow sync**: Reported state (models + active_model) syncs to cloud,
   visible in AWS Console and React dashboard
6. **KVS video streaming**: Live camera feed via Kinesis Video Streams HLS
7. **React dashboard**: Live video + bounding box overlay + inference results
   panel + model selector + settings drawer

### Architecture

```
Camera (/dev/video0)
  │
  ├──► KvsProducer (GStreamer → KVS @ 15fps)
  │     └── writes snapshot JPEGs to shared directory
  │
  └──► InferenceHandler (reads snapshots @ 1fps)
         ├── reads active model from model-config shadow
         ├── calls OVMS gRPC (localhost:9000)
         ├── post-processes (detection boxes or classification probs)
         ├── publishes to camera/inference via IoT Core MQTT
         └── reports active_model to shadow
              │
              └──► React dashboard
                    ├── KVS HLS video player
                    ├── Canvas overlay (bounding boxes / classification badge)
                    ├── Inference results panel
                    └── Model selector (updates shadow desired.active_model)
```

### Model switch flow

1. React UI sets `desired.active_model = "<model-id>"`
2. Shadow delta propagates to device via ShadowManager
3. InferenceHandler receives delta → reads model metadata from reported state
4. Switches OVMS model name, updates pre/post-processing
5. Reports `reported.active_model = "<model-id>"` to shadow
6. React UI polls shadow, sees reported matches desired → confirms switch

### Startup priority for active model

On restart/deployment, InferenceHandler uses this priority chain:
1. `desired.active_model` — user explicitly requested (pending switch)
2. `reported.active_model` — persisted from previous run (survives restarts)
3. First ready model — cold start fallback

### Camera sharing

The Logitech BRIO USB camera does not support concurrent V4L2 access.
KvsProducer owns the camera exclusively and writes snapshot JPEGs.
InferenceHandler reads from the snapshot directory (no camera access needed).
Camera device: `/dev/video0` (KvsProducer), snapshots read by InferenceHandler.

### S3 bucket layout

```
s3://gg-ge-test/components/
├── manifests/
│   ├── model-faster-rcnn.json
│   └── model-efficientnet.json
├── ovms-engine+model-faster-rcnn.comp    (1.3 MB)
├── ovms-engine+model-efficientnet.comp   (3.2 MB)
├── ovms-engine+ovms-cpu.comp             (83 MB)
├── ovms-engine+ovms-gpu.comp             (83 MB)
└── ovms-engine+ovms-npu.comp             (83 MB)
```

### Current models

| Model ID | Actual Model | Purpose | Input | Inference Time |
|----------|-------------|---------|-------|---------------|
| faster-rcnn | person-detection-retail-0013 | Person detection | [1,3,320,544] NCHW | ~70ms |
| efficientnet | age-gender-recognition-retail-0013 | Age/gender classification | [1,3,62,62] NCHW | ~10ms |

### Key components

| Component | Version | Role |
|-----------|---------|------|
| com.example.ModelManagerCore | 1.0.x | Shadow-driven model lifecycle (install/remove/config) |
| com.example.InferenceHandler | 1.0.x | Unified inference (frame capture, OVMS call, MQTT publish) |
| com.example.KvsProducer | 1.0.x | Camera capture, KVS streaming, snapshot writing |
| ovms-engine (snap) | 1.0.0 | OpenVINO Model Server daemon |

## Resolved issues (2026-05-20)

1. ~~Shadow sync~~: IoT policy missing shadow actions → fixed
2. ~~OVMS missing shared libs~~: Full transitive deps + symlink dereferencing
3. ~~OVMS server startup~~: Bypassed modelctl, set LD_LIBRARY_PATH/PYTHONHOME
4. ~~Content interface~~: Works correctly from inside snap namespace
5. ~~Component path resolution~~: snapd API query for sideloaded revision
6. ~~Camera contention~~: InferenceHandler reads KvsProducer snapshots
7. ~~Model switch reliability~~: Proper priority chain + delta-driven switching

## Known issues

1. **Snapshot freshness**: If KvsProducer stops writing snapshots (camera
   disconnect), InferenceHandler silently stops inferring (frame returns None).
   No error reported to user.

2. **Model labels**: Only person-detection has a human-readable label mapping.
   Classification model outputs `class_N` indices without label names.

## Next steps

1. **Add more models** to demonstrate switching variety
2. **Improve React overlay** with confidence threshold slider affecting display
3. **Add inference metrics** to dashboard (FPS, latency graph)
