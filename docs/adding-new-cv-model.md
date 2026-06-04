# Adding a New CV Model

This guide covers every step required to introduce a new computer vision model to the Greengrass edge pipeline — from initial model export through to validated deployment on device.

## Overview

A new CV model requires artefacts across four layers:

| Layer | What's needed |
|-------|---------------|
| **Snap component** | Model weights (`.xml` + `.bin`), `manifest.json`, `labels.txt`, `component.yaml` |
| **S3** | `.comp` file, manifest copy, labels copy |
| **Inference handler** | Postprocessor function (if output format is new) |
| **React frontend** | Renderer for the result type (if result type is new) |
| **Device shadow** | Entry in `model-config` shadow desired state |

## Prerequisites

- Build workstation with `snapcraft` installed
- Python venv with `openvino` and model framework (e.g. `ultralytics`)
- Access to the `gg-ge-test` S3 bucket (eu-west-1)
- SSH access to the target device

---

## Step 1: Export the Model to OpenVINO IR

Export your model to OpenVINO Intermediate Representation (`.xml` + `.bin` files).

Example for a YOLO model via Ultralytics:

```bash
python3 -c "
from ultralytics import YOLO
model = YOLO('your-model.pt')
model.export(format='openvino', imgsz=640, half=False, dynamic=False, end2end=False)
"
```

Key considerations:
- Use `end2end=False` for YOLO models to get raw tensor output compatible with our postprocessors
- Use `dynamic=False` for fixed input shape (required by OVMS)
- Note the input and output tensor shapes — you'll need these for the manifest

---

## Step 2: Verify Tensor Shapes

Confirm the exported model has the expected input/output shapes:

```bash
python3 -c "
import openvino as ov
m = ov.Core().read_model('path/to/model.xml')
for i in m.inputs:
    names = i.get_names()
    name = next(iter(names)) if names else 'unnamed'
    print(f'Input:  {name} shape={list(i.shape)}')
for o in m.outputs:
    names = o.get_names()
    name = next(iter(names)) if names else 'unnamed'
    print(f'Output: {name} shape={list(o.shape)}')
"
```

Record:
- **Input name** (e.g. `x`, `input_tensor`)
- **Input shape** (e.g. `[1, 3, 640, 640]`)
- **Input dtype** (e.g. `float32`, `uint8`)
- **Output name(s)** (e.g. `output0`, or multiple like `detection_boxes`, `detection_scores`)
- **Output shape(s)** (e.g. `[1, 56, 8400]`)

These values go directly into `manifest.json`.

---

## Step 3: Create the Snap Component Directory

Create the component directory structure under `ovms-engine/components/`:

```
ovms-engine/components/model-<model_id>/
├── 1/
│   ├── <model_name>.xml      # OpenVINO model definition
│   └── <model_name>.bin      # OpenVINO model weights
├── manifest.json              # Model metadata for ModelManagerCore
├── labels.txt                 # One label per line
└── component.yaml             # Snap component environment
```

### 3a: Copy Model Weights

```bash
mkdir -p ovms-engine/components/model-<model_id>/1/
cp exported_model.xml ovms-engine/components/model-<model_id>/1/<model_name>.xml
cp exported_model.bin ovms-engine/components/model-<model_id>/1/<model_name>.bin
```

### 3b: Create `manifest.json`

This is the critical metadata file that tells ModelManagerCore and InferenceHandler how to serve and interpret the model.

```json
{
    "model_id": "<model_id>",
    "model_name": "<model_name>",
    "version": "1.0.0",
    "input_name": "<from step 2>",
    "output_names": ["<from step 2>"],
    "input_shape": [1, 3, 640, 640],
    "input_dtype": "float32",
    "normalize": true,
    "labels_file": "labels.txt"
}
```

Field reference:

| Field | Description | Example |
|-------|-------------|---------|
| `model_id` | Unique identifier, used in shadow state and UI | `"yolo26pose"` |
| `model_name` | Name used in OVMS `models_config.json` | `"yolo26pose"` |
| `version` | Semantic version | `"1.0.0"` |
| `input_name` | Tensor input name from step 2 | `"x"` or `"input_tensor"` |
| `output_names` | Array of output tensor names | `["output0"]` |
| `input_shape` | Input tensor dimensions | `[1, 3, 640, 640]` |
| `input_dtype` | Input data type | `"float32"` or `"uint8"` |
| `normalize` | Whether to normalize pixel values to 0-1 | `true` for float32 inputs |
| `labels_file` | Filename of labels file (relative to component dir) | `"labels.txt"` |
| `output_format` | (Optional) Explicit routing hint for postprocessor | `"yolo26-pose"` |
| `num_keypoints` | (Optional) For pose models | `17` |

### 3c: Create `labels.txt`

One label per line, index 0 first:

```
person
car
bicycle
...
```

### 3d: Create `component.yaml`

```yaml
environment:
  - MODEL_<UPPER_ID>_PATH=$COMPONENT
```

Example: `MODEL_YOLO26POSE_PATH=$COMPONENT`

---

## Step 4: Rebuild the Snap

On the build workstation:

```bash
cd ovms-engine && snapcraft --destructive-mode
```

This produces the updated `ovms-engine.snap` and the `.comp` file:
`ovms-engine/ovms-engine+model-<model_id>.comp`

---

## Step 5: Upload Artefacts to S3

Three artefacts must be uploaded. All three are required — the device cannot access files inside the sideloaded snap due to snap confinement.

```bash
# 1. The .comp file (model weights packaged as snap component)
aws s3 cp ovms-engine/ovms-engine+model-<model_id>.comp \
  s3://gg-ge-test/components/ovms-engine+model-<model_id>.comp \
  --region eu-west-1

# 2. The manifest (ModelManagerCore downloads this to configure OVMS)
aws s3 cp ovms-engine/components/model-<model_id>/manifest.json \
  s3://gg-ge-test/components/manifests/model-<model_id>.json \
  --region eu-west-1

# 3. The labels file (InferenceHandler needs this for human-readable output)
aws s3 cp ovms-engine/components/model-<model_id>/labels.txt \
  s3://gg-ge-test/components/labels/<model_id>.txt \
  --region eu-west-1
```

**Why all three?** The snap is sideloaded (not store-installed), so ModelManagerCore cannot read files from inside the snap's component directory. It falls back to S3 for both the manifest and labels.

---

## Step 6: Install Updated Snap on Device

Copy the rebuilt snap to the device and install:

```bash
scp ovms-engine/ovms-engine_*.snap user@device:/tmp/
ssh user@device "sudo snap install /tmp/ovms-engine_*.snap --dangerous"
```

---

## Step 7: Add Model to Device Shadow

Add the model entry to the `model-config` named shadow:

```bash
aws iot-data update-thing-shadow \
  --thing-name <thing-name> \
  --shadow-name model-config \
  --cli-binary-format raw-in-base64-out \
  --payload '{"state":{"desired":{"models":{"<model_id>":{"source":"snap","type":"cv"}}}}}' \
  --region eu-west-1 \
  /dev/stdout | python3 -m json.tool
```

This merges the new model into the existing `models` map without overwriting other entries.

---

## Step 8: Validate Deployment

After updating the shadow, ModelManagerCore will:

1. Receive the shadow delta
2. Download the `.comp` from S3
3. Sideload the component via snapd
4. Download `manifest.json` from S3
5. Configure OVMS with the model
6. Copy labels to shared writable area
7. Report model status as `ready` in shadow reported state

**Check reported state:**

```bash
aws iot-data get-thing-shadow \
  --thing-name <thing-name> \
  --shadow-name model-config \
  --region eu-west-1 \
  /dev/stdout | python3 -m json.tool
```

Look for your model under `state.reported.models.<model_id>` with `"status": "ready"`.

**Switch to the model:**

Either use the React UI model selector, or update the shadow:

```bash
aws iot-data update-thing-shadow \
  --thing-name <thing-name> \
  --shadow-name model-config \
  --cli-binary-format raw-in-base64-out \
  --payload '{"state":{"desired":{"active_model":"<model_id>"}}}' \
  --region eu-west-1 \
  /dev/stdout | python3 -m json.tool
```

---

## Step 9: Update Deploy Script

Add the model to `scripts/deploy_greengrass_components.py` in the `ensure_device_shadows` method so new devices get the model automatically:

```python
'models': {
    ...
    '<model_id>': {'source': 'snap', 'type': 'cv'},
}
```

---

## When a New Postprocessor is Needed

The inference handler auto-detects output format based on tensor shape and manifest metadata. Existing postprocessors handle:

| Format | Detection method | result_type |
|--------|-----------------|-------------|
| YOLO pose | `output_format == "yolo26-pose"` or shape `[1, 56, N]` | `pose` |
| YOLOv8 detection | Shape `[1, C, N]` where C < N and C >= 5 | `detection` |
| TF2 detection | Output names include `detection_boxes`, `detection_scores`, `detection_classes` | `detection` |
| OpenVINO detection | Shape `[1, 1, N, 7]` or output named `detection_out` | `detection` |
| Classification | Fallback (none of the above match) | `classification` |

If your model's output format doesn't match any of these patterns, you need to:

1. Add a detection method (e.g. `_is_<format>_output()`) in `inference_handler.py`
2. Add a postprocessor method (e.g. `_postprocess_<format>()`)
3. Add routing in `_postprocess()` — order matters: more specific checks first

If you need a new `result_type` (not `detection`, `pose`, or `classification`), you also need to add a renderer in `react-web/src/components/dashboard/InferenceOverlay.tsx`.

---

## When a New result_type Renderer is Needed

The React overlay dispatches on `result.result_type`:

- `detection` → `drawDetections()` — bounding boxes with labels
- `pose` → `drawPoseDetections()` — bounding boxes + skeleton wireframes
- `classification` → `drawClassificationBadge()` — top-left label badge

To add a new renderer:
1. Add a drawing function in `InferenceOverlay.tsx`
2. Add an `else if` branch in the render dispatch
3. Define any new TypeScript types in the inference types file

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `"status": "failed"`, reason: "manifest.json not accessible" | Manifest not uploaded to S3 | Upload to `s3://gg-ge-test/components/manifests/model-<model_id>.json` |
| Model shows in shadow but not in UI | Model still installing, or reported state not yet updated | Wait 30s, check reported state again |
| Model installs but inference fails | Tensor shape mismatch between manifest and actual model | Re-verify with openvino, update manifest |
| Model installs but no labels | Labels file not uploaded to S3 | Upload to `s3://gg-ge-test/components/labels/<model_id>.txt` |
| Postprocessor produces garbage | Wrong `output_format` in manifest, or shape detection routing to wrong postprocessor | Set explicit `output_format` in manifest |
| `.comp` download fails | File not in S3 or wrong path | Check `s3://gg-ge-test/components/ovms-engine+model-<model_id>.comp` exists |

---

## Checklist

Use this checklist when adding any new CV model:

- [ ] Model exported to OpenVINO IR (`.xml` + `.bin`)
- [ ] Tensor shapes verified (input name, shape, dtype; output names, shapes)
- [ ] Component directory created: `ovms-engine/components/model-<model_id>/`
- [ ] `manifest.json` created with correct tensor metadata
- [ ] `labels.txt` created
- [ ] `component.yaml` created
- [ ] Snap rebuilt (`snapcraft --destructive-mode`)
- [ ] `.comp` file uploaded to S3
- [ ] `manifest.json` uploaded to S3 (`components/manifests/model-<model_id>.json`)
- [ ] `labels.txt` uploaded to S3 (`components/labels/<model_id>.txt`)
- [ ] Updated snap installed on device
- [ ] Model added to device shadow (`model-config` desired state)
- [ ] Model status confirmed as `ready` in shadow reported state
- [ ] Model switch tested (via UI or shadow)
- [ ] Inference output validated (correct bounding boxes/labels/keypoints)
- [ ] Deploy script updated for new devices
- [ ] Postprocessor added (only if new output format)
- [ ] React renderer added (only if new result_type)
