# Improvement Recommendations

This document captures prioritised improvement ideas for the Ubuntu Core / AWS Greengrass / Intel OpenVINO computer vision edge demo. All recommendations retain the core technology stack.

---

## Priority Recommendations

| Priority | Improvement | Theme |
|---|---|---|
| 1 | [Confidence Threshold Filtering](#1-confidence-threshold-filtering) ✓ | Inference quality |
| 2 | [Motion-Triggered Inference](#2-motion-triggered-inference) | Edge intelligence |
| 3 | [IoT Device Shadow for Runtime Configuration](#3-iot-device-shadow-for-runtime-configuration) | Cloud-to-edge control |
| 4 | [Event-Driven Alerting on Specific Detections](#4-event-driven-alerting-on-specific-detections) | Real-world applicability |
| 5 | [Dashboard Bounding Box Overlay as Interactive Data](#5-dashboard-bounding-box-overlay-as-interactive-data) | Visualisation |
| 6 | [Multi-Model Support via OpenVINO Model Server](#6-multi-model-support-via-openvino-model-server) | AI capability breadth |
| 7 | [Model Download Management via S3Downloader Component](#7-model-download-management-via-s3downloader-component) | Model lifecycle management |

---

## 1. Confidence Threshold Filtering

> **Status: Implemented, not yet fully tested** — deployed with IoT Device Shadow integration for runtime control (see variation below).

### Problem

The `InferenceHandlerCore` currently renders the top 10 detections unconditionally — a bounding box with a confidence score of 0.01 is drawn identically to one scored 0.99. This produces visually noisy output and undermines confidence in the AI results.

### Solution

Add a configurable `confidence_threshold` parameter to the `InferenceHandlerCore` component. Only detections above this threshold are annotated on the image and included in the published MQTT payload.

Rather than making the threshold purely a static deployment-time setting, the implementation combines the recipe configuration with an AWS IoT Device Shadow (`inference-config`) so the threshold can be adjusted at runtime from the React dashboard without any redeployment.

### Implementation

**Recipe (`com.example.InferenceHandlerCore-1.0.0.yaml`):**

- `ConfidenceThreshold: "0.5"` added to `DefaultConfiguration`, passed as `CONFIDENCE_THRESHOLD` env var to the component
- `aws.greengrass.ShadowManager` added as a component dependency
- IPC access granted for `GetThingShadow` and `UpdateThingShadow` on the `inference-config` named shadow, and `SubscribeToTopic` on the shadow delta topic:

```yaml
aws.greengrass.ShadowManager:
  com.example.InferenceHandlerCore:shadow:3:
    policyDescription: 'Allows read and write access to the inference-config named shadow'
    operations:
      - 'aws.greengrass#GetThingShadow'
      - 'aws.greengrass#UpdateThingShadow'
    resources:
      - '$aws/things/*/shadow/name/inference-config'
```

**`inference_handler_core.py` — three-phase shadow integration:**

1. **Startup restore** — `load_shadow_config()` reads the `reported.confidence_threshold` from the shadow so the last operator-set value is applied immediately on component restart, taking precedence over the recipe default:

```python
response = self.ipc_client.get_thing_shadow(
    thing_name=self.thing_name, shadow_name='inference-config'
)
shadow = json.loads(response.payload)
reported = shadow.get('state', {}).get('reported', {})
if 'confidence_threshold' in reported:
    self.config['confidence_threshold'] = float(reported['confidence_threshold'])
```

2. **Runtime delta subscription** — `run()` subscribes to the shadow delta topic so updates from the dashboard take effect immediately without restarting the component:

```python
delta_topic = f"$aws/things/{self.thing_name}/shadow/name/inference-config/update/delta"
self.ipc_client.subscribe_to_topic(
    topic=delta_topic,
    on_stream_event=self.on_shadow_delta,
    ...
)
```

3. **Reported state sync** — after applying a delta (or on startup), `update_shadow_reported()` writes the active threshold back to `reported` so the shadow stays consistent and the dashboard always reflects the live device value.

**Detection loop filter** in `run_inference()`:

```python
threshold = self.config['confidence_threshold']
for i in range(self.config['detections_limit']):
    score = detection_scores[0, i]
    if score < threshold:
        continue
    # draw box and add to json_result
```

**React dashboard (`ConfidenceThresholdControl.tsx` + `iotShadowService.ts`):**

A slider control reads the current threshold from the `inference-config` named shadow on load (via `GetThingShadow`) and writes a `desired` state update (via `UpdateThingShadow`) when the operator clicks Apply. The IoT shadow service uses `IoTDataPlaneClient` with the Cognito-authenticated user credentials:

```ts
// Read current threshold
const shadow = await client.send(new GetThingShadowCommand({ thingName, shadowName: 'inference-config' }));

// Write new threshold
await client.send(new UpdateThingShadowCommand({
    thingName, shadowName: 'inference-config',
    payload: JSON.stringify({ state: { desired: { confidence_threshold: threshold } } })
}));
```

The component requires the operator to enter the IoT Thing Name in the dashboard — a `ThingNameInput` component was added alongside the threshold control.

### Value

- Immediate improvement to visual output quality with minimal code change
- Threshold is tuneable live from the dashboard without any redeployment or device access — the delta is applied to the next inference frame
- The `reported` state in the shadow means the dashboard always shows the threshold the device is actually using, not just what was last requested
- Cleaner MQTT payloads reduce downstream noise in the dashboard message feed
- Demonstrates the cloud-to-edge control pattern from recommendation 3, scoped to a single, immediately visible parameter

---

## 2. Motion-Triggered Inference

### Problem

The camera captures and submits an image to the inference pipeline every 30 seconds regardless of whether anything has changed in the scene. This wastes inference compute on the OpenVINO Model Server, generates unnecessary S3 uploads, and produces a flat, uninteresting stream of nearly identical images.

### Solution

Replace the fixed-interval capture loop with a continuous low-FPS capture loop that applies on-device motion detection (frame differencing or background subtraction) before triggering inference. Inference is only invoked when meaningful motion is detected.

### Implementation

- In `camera_handler_core.py`, replace the `time.sleep` loop with a persistent `cv2.VideoCapture` session
- Apply OpenCV background subtraction between frames using `cv2.createBackgroundSubtractorMOG2()`
- Count the number of changed pixels in the foreground mask against a configurable `motion_threshold`
- Only publish the image path to the `camera/images` MQTT topic when the threshold is exceeded
- Add `MotionThreshold` to the recipe configuration

```python
fgbg = cv2.createBackgroundSubtractorMOG2()
while True:
    ret, frame = cap.read()
    fgmask = fgbg.apply(frame)
    motion_area = cv2.countNonZero(fgmask)
    if motion_area > self.config['motion_threshold']:
        image_path = self.save_image(frame)
        self.publish_image_event(image_path)
    time.sleep(self.config['frame_interval'])
```

### Value

- Demonstrates genuine edge intelligence: the device makes a local decision before invoking the AI pipeline
- Reduces inference calls, S3 writes, and IoT Core message volume — quantifiably demonstrable during a demo
- Realistic pattern for security camera and industrial monitoring use cases
- Keeps inference results meaningful — when something is detected, something actually happened

---

## 3. IoT Device Shadow for Runtime Configuration

### Problem

Changing any configuration parameter (capture interval, confidence threshold, model name) currently requires a full Greengrass component redeployment, which takes several minutes and requires cloud connectivity to the Greengrass service. There is no way to adjust device behaviour in real time.

### Solution

Integrate AWS IoT Device Shadow with both Greengrass components so that configuration can be updated from the cloud and applied without redeployment. Each component subscribes to its shadow's `delta` document via Greengrass IPC and reconfigures itself when a change is received.

### Implementation

- Add `aws.greengrass.ShadowManager` as a dependency in both component recipes
- Grant each component IPC access to read and update the local device shadow
- In each component's main loop, subscribe to shadow delta events via the MQTT delta topic using `subscribe_to_topic` (the same pattern used in item 1's implemented `InferenceHandlerCore`):

```python
thing_name = os.environ.get('AWS_IOT_THING_NAME')
delta_topic = f"$aws/things/{thing_name}/shadow/name/camera-config/update/delta"
self.ipc_client.subscribe_to_topic(
    topic=delta_topic,
    on_stream_event=self.on_shadow_delta,
    on_stream_error=self.on_stream_error,
    on_stream_closed=self.on_stream_closed
)
```

- On delta receipt, update the in-memory config dict and apply changes (e.g., adjust the motion threshold, swap the active model name, change the capture interval)
- Report the accepted state back to the shadow to confirm

### Configurable Parameters via Shadow

| Parameter | Component | Effect |
|---|---|---|
| `capture_interval` | CameraHandlerCore | Change frame rate |
| `motion_threshold` | CameraHandlerCore | Sensitivity of motion trigger |
| `confidence_threshold` | InferenceHandlerCore | Filter detection noise |
| `model_name` | InferenceHandlerCore | Switch active OVMS model |
| `detections_limit` | InferenceHandlerCore | Cap number of drawn boxes |

### Value

- Enables live demo adjustment: increase sensitivity, switch models, tune confidence — all from the AWS Console or CLI with immediate effect on the device
- Tells a compelling story about cloud-to-edge control without requiring physical access to the device
- Realistic operational pattern — field technicians can tune devices remotely

---

## 4. Event-Driven Alerting on Specific Detections

### Problem

All inference results are published to a single `camera/inference` MQTT topic as raw JSON and displayed in the dashboard message feed. There is no distinction between a routine background frame and a significant detection event (e.g., a person entering a restricted area). Consumers of the data must filter all messages themselves.

### Solution

Add a configurable alert rules system to `InferenceHandlerCore`. When a detection matches a configured class above a configured threshold, publish an enriched alert message to a dedicated `camera/alerts` IoT Core topic. Wire this downstream to SNS for email/SMS notification.

### Implementation

**Recipe configuration additions:**

```yaml
AlertRules:
  - class: "person"
    threshold: 0.7
  - class: "vehicle"
    threshold: 0.6
AlertTopic: "camera/alerts"
```

**In `inference_handler_core.py`:**

```python
def check_alerts(self, detections):
    for rule in self.config['alert_rules']:
        for detection in detections.values():
            if (detection['detection_classes'] == rule['class'] and
                    detection['detection_scores'] >= rule['threshold']):
                self.publish_alert(detection, rule)

def publish_alert(self, detection, rule):
    alert = {
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "triggered_class": detection['detection_classes'],
        "score": float(detection['detection_scores']),
        "rule": rule,
        "image_s3_key": "camera/latest-inference.jpg"
    }
    self.ipc_client.publish_to_iot_core(
        topic_name=self.config['alert_topic'],
        qos='1',
        payload=json.dumps(alert).encode('utf-8')
    )
```

**AWS-side:**
- Create an IoT Core Rule that forwards `camera/alerts` messages to an SNS topic
- SNS delivers email/SMS notifications to subscribed endpoints
- Alert rules are updatable at runtime via Device Shadow (see recommendation 3)

### Value

- Highest demo impact: audience can see a real-world detection trigger a cloud notification in real time
- Directly applicable to security, safety, and industrial inspection use cases
- Demonstrates the full edge-to-cloud event pipeline without any server-side infrastructure (IoT Rules + SNS is fully managed)
- Alert rules configured via Device Shadow make the system tuneable without redeployment

---

## 5. Dashboard Bounding Box Overlay as Interactive Data

### Problem

The React dashboard displays the inference result as a JPEG with bounding boxes baked into the pixels by the `InferenceHandlerCore`. The detection metadata (class names, confidence scores, box coordinates) is published separately as JSON on the `camera/inference` MQTT topic and currently displayed only as raw JSON text in the message feed. The two data streams are not connected in the UI.

### Solution

Separate the visualisation from the edge processing. Upload the **raw** (unannotated) image to S3, and render bounding boxes in the browser using the detection JSON from MQTT. This makes the overlay interactive and decouples the UI presentation from the edge component.

### Implementation

**Edge changes (`inference_handler_core.py`):**
- Upload the original (pre-annotation) image to S3 instead of the annotated version
- Include normalised bounding box coordinates in the MQTT JSON payload:

```python
json_result[i] = {
    "detection_classes": detected_class_name,
    "detection_scores": float(score),
    "box": {
        "ymin": float(box[0]), "xmin": float(box[1]),
        "ymax": float(box[2]), "xmax": float(box[3])
    },
    "num_detections": int(num_detections[0])
}
```

**Dashboard changes (`ImageGallery.tsx` / new `DetectionOverlay.tsx`):**
- Render the S3 image in an `<img>` element inside a relatively-positioned container
- Overlay an `<svg>` or `<canvas>` element at the same dimensions
- Draw bounding boxes from the latest MQTT message using the normalised coordinates
- On hover over a bounding box, show a tooltip with class name and confidence score
- Colour-code boxes by class (consistent colour per class name using a hash)

```tsx
// Scale normalised coords to rendered image dimensions
const scaleBox = (box, imgWidth, imgHeight) => ({
  x: box.xmin * imgWidth,
  y: box.ymin * imgHeight,
  width: (box.xmax - box.xmin) * imgWidth,
  height: (box.ymax - box.ymin) * imgHeight,
});
```

### Value

- Transforms the dashboard from a passive image viewer into an interactive AI results display
- Demonstrates that the edge and cloud components are genuinely connected — new detections update the overlay in real time via MQTT
- Removes bounding box rendering from the constrained edge device, reducing CPU load
- Opens the door to dashboard-side filtering: users can toggle visibility of specific classes, set their own confidence threshold in the UI, and see the effect instantly without any device changes

---

## 6. Multi-Model Support via OpenVINO Model Server

### Problem

The current solution is locked to a single Faster R-CNN object detection model. Whilst effective for demonstrating detection, a single model type limits the range of AI use cases the demo can represent and does not showcase the full capability of OpenVINO Model Server, which is designed to serve multiple models simultaneously.

### Solution

Configure OVMS to serve multiple models concurrently and introduce a model pipeline concept within `InferenceHandlerCore`. Different models run in sequence or in parallel on the same frame, with each result enriching the final output. The active pipeline is selectable at runtime via Device Shadow (see recommendation 3).

### Models to Add

| Model Type | Example Model | Use Case | OpenVINO Support |
|---|---|---|---|
| Object detection | Faster R-CNN (existing) | Locate and classify objects | Native |
| Image classification | EfficientNet / MobileNet | Scene-level "what is this?" | Native |
| Anomaly detection | PADIM / PatchCore | Industrial defect detection | Intel AI Reference Models |
| Semantic segmentation | DeepLab v3 | Pixel-level scene understanding | Native |

### Implementation

**`OpenVINOModelServerContainerCore` recipe changes:**

Replace the single `--model_name` / `--model_path` Docker flags with a multi-model config file mounted into the container:

```yaml
# models_config.json (added as an artifact)
{
  "model_config_list": [
    { "config": { "name": "faster_rcnn",    "base_path": "/models/faster_rcnn" } },
    { "config": { "name": "efficientnet",   "base_path": "/models/efficientnet" } },
    { "config": { "name": "anomaly_detect", "base_path": "/models/anomaly_detect" } }
  ]
}
```

```bash
# Updated Docker run command in recipe
docker run -u 0 -d \
  -v {artifacts:decompressedPath}/models:/models \
  -v {artifacts:path}/models_config.json:/config/models_config.json \
  -p 9000:9000 \
  openvino/model_server:latest \
  --config_path /config/models_config.json \
  --port 9000
```

> **Ubuntu Core note:** The `{artifacts:decompressedPath}` path resolves to a Greengrass-managed artifact store, which is accessible on Ubuntu Core. This is appropriate for the bundled-artifact approach shown here. When integrating with the S3Downloader component (see recommendation 7), the models directory must be writable — switch the Docker mount to `{work:path}/models` instead, which is a Greengrass-managed writable directory scoped to this component and works on both Ubuntu Core and standard Linux.

**`InferenceHandlerCore` changes:**

Introduce a pipeline concept where multiple model calls are chained per frame:

```python
PIPELINES = {
    "detection_only": ["faster_rcnn"],
    "detection_and_classify": ["faster_rcnn", "efficientnet"],
    "anomaly": ["anomaly_detect"],
    "full": ["faster_rcnn", "efficientnet", "anomaly_detect"],
}

def run_inference(self, message):
    image = self.load_image(message['image_path'])
    pipeline = PIPELINES.get(self.config['active_pipeline'], ["faster_rcnn"])
    combined_result = {}

    for model_name in pipeline:
        result = self.run_model(image, model_name)
        combined_result[model_name] = result

    self.publish_results(combined_result)
    self.upload_to_s3(image)
```

Each model's results are published as a named key in the MQTT payload, so the dashboard can render them distinctly. The `active_pipeline` config key is switchable at runtime via Device Shadow.

**New Greengrass component for model management:**

A lightweight `com.example.ModelManagerCore` component could be added to handle downloading new model versions from S3 and notifying the inference handler to reload — decoupling model lifecycle from component deployment.

### Value

- Dramatically expands the range of AI scenarios the demo can represent from a single edge device
- OVMS multi-model serving is a key differentiator of the Intel OpenVINO stack — this directly showcases it
- Anomaly detection is a particularly compelling addition for industrial and manufacturing audiences: no labelled training data is needed for many use cases
- Pipeline switching via Device Shadow (recommendation 3) means the audience can see the device switch from object detection to anomaly detection mode live, without any redeployment
- Sets up the architecture for the OTA model update pipeline (backlog item)

---

## 7. Model Download Management via S3Downloader Component

### Problem

The current solution bundles the AI model as a ZIP artifact inside the `OpenVINOModelServerContainerCore` Greengrass component. This approach has several hard limitations:

- Greengrass component artifacts have a **5 GB size ceiling**, which is already constraining for Faster R-CNN and becomes a blocker as larger or multiple models are added (see recommendation 6)
- Every model update requires a full component redeployment, which re-uploads the entire artifact to S3 and re-pushes it to the device
- There is no visibility into download progress or the ability to pause, resume, or cancel a transfer
- The device has no registry of which models are available locally, making dynamic model switching (recommendation 3) fragile

### Solution

Integrate the [aws-samples/sample-model-downloader-greengrass-component](https://github.com/aws-samples/sample-model-downloader-greengrass-component) as an additional Greengrass component (`aws.samples.S3Downloader`). This component decouples model files from the component deployment lifecycle entirely: models live in S3 and are pulled to the device on demand via MQTT commands, with progress tracked and model metadata persisted in an IoT Device Shadow.

### How It Works

The S3Downloader component (`aws.samples.S3Downloader`) runs as a persistent service on the device and exposes a three-topic MQTT interface:

| Topic | Direction | Purpose |
|---|---|---|
| `s3downloader/{thingName}/commands` | Cloud → Device | Trigger download, pause, resume, cancel, list |
| `s3downloader/{thingName}/responses` | Device → Cloud | Command acknowledgement with `downloadId` |
| `s3downloader/{thingName}/status` | Device → Cloud | Real-time progress updates |

Downloads use **s5cmd** under the hood — a concurrent S3 transfer tool — with configurable parallelism and exponential backoff retry (up to 10 attempts), making it robust over unreliable edge connectivity.

When a download completes, the model is automatically registered in a named IoT Device Shadow called `models`:

```json
{
  "state": {
    "reported": {
      "models": {
        "faster_rcnn_v2": {
          "model_id": "faster_rcnn_v2",
          "model_name": "Faster R-CNN",
          "model_version": "2.0",
          "local_path": "<greengrass_work_root>/com.example.OpenVINOModelServerContainerCore/models/faster_rcnn",
          "last_updated": 1710000000
        },
        "efficientnet": {
          "model_id": "efficientnet",
          "model_name": "EfficientNet B0",
          "model_version": "1.0",
          "local_path": "<greengrass_work_root>/com.example.OpenVINOModelServerContainerCore/models/efficientnet",
          "last_updated": 1710000100
        }
      }
    }
  }
}
```

### Ubuntu Core Compatibility

Ubuntu Core uses a read-only root filesystem — directories such as `/data/` do not exist and cannot be created at runtime. All path references in this recommendation must use Greengrass-managed writable locations instead.

**`{work:path}` in the OVMS recipe**

The Greengrass recipe variable `{work:path}` resolves to a component-scoped writable directory managed entirely by Greengrass. Use this for the Docker volume mount in the `OpenVINOModelServerContainerCore` recipe — it works on both Ubuntu Core and standard Linux installations:

| System | `{work:path}` resolves to |
|---|---|
| Standard Linux (Greengrass installed at `/greengrass/v2`) | `/greengrass/v2/work/com.example.OpenVINOModelServerContainerCore/` |
| Ubuntu Core (Greengrass snap) | `/var/snap/aws-iot-greengrass/current/greengrass/v2/work/com.example.OpenVINOModelServerContainerCore/` |

**Cross-component download destination**

The S3Downloader runs as a separate component and cannot reference the OVMS component's `{work:path}` directly in its MQTT download commands. The `destination` field in each download command must be set to the OVMS component's resolved work path. The placeholder `<greengrass_work_root>` used in the examples below refers to this base:

- Standard Linux: `/greengrass/v2/work`
- Ubuntu Core: `/var/snap/aws-iot-greengrass/current/greengrass/v2/work`

The `deploy_greengrass_components.py` script should detect the correct base path at deploy time (e.g., by reading the Greengrass root from configuration or probing the filesystem) and substitute it when publishing download commands.

**`s5cmd` binary availability**

The S3Downloader component uses `s5cmd` for concurrent S3 transfers. On Ubuntu Core, `apt install` is not available, so `s5cmd` must be bundled as an artifact within the S3Downloader component itself. Before deploying, verify that the [aws-samples/sample-model-downloader-greengrass-component](https://github.com/aws-samples/sample-model-downloader-greengrass-component) bundles a pre-compiled `s5cmd` binary matching your device architecture (`amd64` or `arm64`). If it does not, a compiled binary for the target architecture must be added as a component artifact.

---

### Integration with This Solution

**Step 1 — Deploy the S3Downloader component** alongside the existing three components. Add it to `deploy_greengrass_components.py` and grant the Greengrass Token Exchange Role `s3:GetObject` and `s3:ListBucket` on the model S3 bucket.

**Step 2 — Remove model artifacts from `OpenVINOModelServerContainerCore`**. Strip the `object_detection_model.zip` artifact from the recipe. Instead, OVMS mounts a local directory that the S3Downloader populates:

```yaml
# Updated OpenVINOModelServerContainerCore recipe run script
docker run -u 0 -d \
  -v {work:path}/models:/models \
  -v {artifacts:path}/models_config.json:/config/models_config.json \
  -p 9000:9000 \
  openvino/model_server:latest \
  --config_path /config/models_config.json \
  --port 9000
```

**Step 3 — Trigger initial model downloads** from the deployment pipeline. After Greengrass deployment completes, `deploy_greengrass_components.py` publishes a download command per model via IoT Core:

```json
{
  "command": "download",
  "bucket": "your-model-bucket",
  "key": "models/faster_rcnn/",
  "destination": "<greengrass_work_root>/com.example.OpenVINOModelServerContainerCore/models/faster_rcnn",
  "model_meta": {
    "model_id": "faster_rcnn",
    "model_name": "Faster R-CNN",
    "model_version": "1.0"
  }
}
```

**Step 4 — Update `InferenceHandlerCore`** to discover available models from the `models` shadow before initialising the OVMS client, rather than relying on a hardcoded `MODEL_NAME` environment variable. This gives the component a live inventory of what is actually present on disk.

**Step 5 — Model updates without redeployment**. To push a new model version, upload the model files to S3 and publish a download command — no Greengrass deployment required. The S3Downloader handles the transfer, updates the shadow, and the inference component picks up the new model on its next shadow read or via a Device Shadow delta (recommendation 3).

### New Deployment Flow

```
Upload model to S3
       │
       ▼
Publish download command to s3downloader/{thingName}/commands
       │
       ▼
S3Downloader pulls model to OVMS component work directory with progress updates
       │
       ▼
Model registered in "models" Device Shadow
       │
       ▼
OVMS picks up new model from mounted /models directory
       │
       ▼
InferenceHandlerCore reads shadow → switches active model
```

### Value

- Removes the 5 GB artifact size ceiling entirely — models of any size can be deployed
- Model updates become a lightweight S3 upload + MQTT command, with no Greengrass redeployment and no downtime
- Real-time download progress is visible in the dashboard message feed via the status topic, making large model deployments transparent to operators
- The `models` Device Shadow gives the cloud a live inventory of exactly which model versions are present on every device in the fleet
- Directly enables the multi-model pipeline in recommendation 6 — each model in the pipeline can be downloaded and updated independently
- Pairs naturally with the OTA model update pipeline (backlog) — CodePipeline uploads to S3 and fires the MQTT command, completing the full MLOps loop without ever touching a Greengrass deployment

### Reference

- Repository: [aws-samples/sample-model-downloader-greengrass-component](https://github.com/aws-samples/sample-model-downloader-greengrass-component)

---

## Additional Recommendations (Backlog)

The following improvements were identified but are lower priority for the initial demo enhancement:

| Improvement | Description |
|---|---|
| **Greengrass Stream Manager** | Replace direct S3 uploads with Greengrass Stream Manager for reliable buffering, automatic retry, and bandwidth throttling during poor connectivity |
| **Image history archiving** | Write timestamped images to `camera/history/YYYYMMDD_HHMMSS.jpg` alongside `latest-inference.jpg` with S3 Lifecycle Rules for automatic expiry |
| **Inference metrics to CloudWatch** | Time each inference call; publish latency, detections-per-frame, and error rate via Greengrass telemetry to CloudWatch for fleet monitoring |
| **Multi-device fleet dashboard** | Add a device selector to the React dashboard; namespace MQTT topics and S3 prefixes per `thingName` to support monitoring multiple edge devices from one UI |
| **OTA model update pipeline** | CodePipeline + Lambda that watches an S3 model staging bucket, packages a new model as a Greengrass component version, and triggers a fleet deployment automatically |

---

*Document created: 2026-03-19*
