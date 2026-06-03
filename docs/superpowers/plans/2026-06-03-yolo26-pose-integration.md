# YOLO26-Pose Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add YOLO26-pose (skeleton/wireframe keypoint detection) as a new CV model alongside the existing detection models, served through OVMS and rendered in the React UI.

**Architecture:** Export YOLO26s-pose to OpenVINO IR with `end2end=False` to match the existing YOLOv8s tensor format pattern (`[1, 56, 8400]`). Extend the inference handler with a new pose-specific postprocessor that extracts both bounding boxes and 17 COCO keypoints. Extend the React frontend to render skeleton wireframes on the canvas overlay.

**Tech Stack:** Ultralytics >= 8.4.0 (YOLO26 ships inside the 8.x package), OpenVINO IR format, Python/numpy (inference handler), React/TypeScript/Canvas2D (frontend), OVMS gRPC (serving)

---

## Status (2026-06-03)

### Completed (all committed to main)
- [x] Task 1: Export script (`scripts/export-yolo26-pose.sh`) — runs successfully
- [x] Task 2: Snap component definition (`ovms-engine/components/model-yolo26pose/`)
- [x] Task 3: Inference handler pose postprocessor
- [x] Task 4: React TypeScript types (Keypoint, pose result_type)
- [x] Task 5: Skeleton wireframe rendering in InferenceOverlay
- [x] Task 6: Deployment shadow config entry

### Next Steps (requires build workstation)

Run these on the build workstation where the export script was executed:

**Step 1: Verify output tensor shape**
```bash
source scripts/venv-yolo26-export/bin/activate
python3 -c "
import openvino as ov
m = ov.Core().read_model('scripts/yolo26s-pose_openvino_model/yolo26s-pose.xml')
for o in m.outputs:
    print(f'Output: {o.get_any_name()} shape={o.shape}')
for i in m.inputs:
    print(f'Input: {i.get_any_name()} shape={i.shape}')
"
deactivate
```
Expected: `Output: output0 shape=[1,56,8400]` and `Input: x shape=[1,3,640,640]`

If the tensor name or shape differs, update `ovms-engine/components/model-yolo26pose/manifest.json` to match (fields: `input_name`, `output_names`, `input_shape`).

**Step 2: Copy model weights into snap component**
```bash
mkdir -p ovms-engine/components/model-yolo26pose/1/
cp scripts/yolo26s-pose_openvino_model/yolo26s-pose.xml ovms-engine/components/model-yolo26pose/1/yolo26pose.xml
cp scripts/yolo26s-pose_openvino_model/yolo26s-pose.bin ovms-engine/components/model-yolo26pose/1/yolo26pose.bin
```

**Step 3: (Optional) Test locally with Docker OVMS**
```bash
docker run -d --rm -p 9000:9000 \
  -v $(pwd)/ovms-engine/components/model-yolo26pose:/models/yolo26pose \
  openvino/model_server:2025.0 \
  --model_name yolo26pose \
  --model_path /models/yolo26pose \
  --port 9000

# Test with random input
source scripts/venv-yolo26-export/bin/activate
python3 -c "
from ovmsclient import make_grpc_client
import numpy as np
client = make_grpc_client('localhost:9000')
result = client.predict({'x': np.random.rand(1,3,640,640).astype(np.float32)}, 'yolo26pose')
if isinstance(result, dict):
    for k, v in result.items(): print(f'{k}: shape={v.shape}')
else:
    print(f'shape={result.shape}')
"
deactivate
```

**Step 4: Rebuild the snap**
```bash
cd ovms-engine && snapcraft --destructive-mode
```

**Step 5: Deploy to device**
Install the updated snap on the device. The ModelManagerCore will detect the new `model-yolo26pose` component. Switch to it via the UI's model selector or by setting `active_model: "yolo26pose"` in the shadow desired state.

---

## Dependencies & Compatibility Analysis

### OVMS Version Compatibility
- **Current OVMS:** The snap extraction script uses `openvino/model_server:2025.0` (see `ovms-engine/extract-ovms-libs.sh:OVMS_VERSION="2025.0"`)
- **YOLO26 export:** Uses OpenVINO IR format. IR format is backward-compatible across OVMS versions — a model exported with OpenVINO 2025.x will load on OVMS 2025.0.
- **Risk:** If Ultralytics 26.x ships with an openvino dependency newer than 2025.0 (docs reference "2026.2.0.dev"), the exported IR version number could be higher than what OVMS 2025.0 supports.
- **Mitigation:** Export with `end2end=False` and pin `openvino==2025.0.*` during conversion. Alternatively, validate the exported model loads on OVMS 2025.0 before packaging.

### YOLO26 Export Strategy
- **`end2end=False` (CHOSEN):** Produces `[1, 56, 8400]` tensor — same pattern as YOLOv8s `[1, 84, 8400]` but with 56 = 4 (box) + 1 (class score for "person") + 51 (17 keypoints × 3 [x, y, conf]). This means:
  - Existing `_is_yolov8_output()` heuristic (`dim1 < dim2 and dim1 >= 5`) **will match** this tensor shape
  - We need the new postprocessor to intercept BEFORE the generic YOLOv8 handler
  - NMS is required (we already have an NMS implementation)
- **`end2end=True` (REJECTED):** Produces `[1, 300, 56]` — simpler postprocessing (no NMS) but `dim1 > dim2` breaks the auto-detection heuristic and `300` fixed detections is a different paradigm from the existing pipeline.

### Ultralytics Package Version
- **Required:** `ultralytics >= 26.0.0` (based on YOLO26 availability)
- **Current YOLOv8s:** Was exported with `ultralytics==8.4.60`
- **Note:** The Ultralytics package is only needed on the dev/CI machine for export — it does NOT run on the device. The device only runs OVMS + the inference handler.

### Model Size Estimate
- YOLOv8s: 11M params, ~22MB weights (`.bin` file)
- YOLO26s: 9.5M params — expect ~19MB weights
- YOLO26s-pose will be similar (~20-25MB) — well within device storage constraints

### Licensing
- YOLO26 is AGPL-3.0 (same as YOLOv8s already in use)
- Weights are separate from runtime — model files are redistributable

### Output Tensor Format (end2end=False)
For YOLO26s-pose with single class ("person"):
```
Shape: [1, 56, 8400]
Transposed: [8400, 56] per detection candidate
  [0:4]   = x_center, y_center, width, height (in input pixels, 640x640)
  [4]     = person class confidence
  [5:56]  = 17 keypoints × 3 values each [x, y, visibility_confidence]
```

### COCO Keypoints (17 points, indexed 0-16)
```
0: nose, 1: left_eye, 2: right_eye, 3: left_ear, 4: right_ear,
5: left_shoulder, 6: right_shoulder, 7: left_elbow, 8: right_elbow,
9: left_wrist, 10: right_wrist, 11: left_hip, 12: right_hip,
13: left_knee, 14: right_knee, 15: left_ankle, 16: right_ankle
```

### COCO Skeleton Connections (for wireframe drawing)
```
[[16, 14], [14, 12], [17, 15], [15, 13], [12, 13], [6, 12], [7, 13],
 [6, 7], [6, 8], [7, 9], [8, 10], [9, 11], [2, 3], [1, 2], [1, 3],
 [2, 4], [3, 5], [4, 6], [5, 7]]
```
(Note: 1-indexed from COCO spec; in code we use 0-indexed)

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `ovms-engine/components/model-yolo26pose/manifest.json` | Model metadata for inference handler |
| Create | `ovms-engine/components/model-yolo26pose/component.yaml` | Snap component env var |
| Create | `ovms-engine/components/model-yolo26pose/labels.txt` | Class labels (just "person") |
| Create | `scripts/export-yolo26-pose.sh` | Model export/conversion script |
| Modify | `ovms-engine/snap/snapcraft.yaml` | Register new snap component |
| Modify | `greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/inference_handler.py` | Add pose postprocessor |
| Modify | `react-web/src/types/inference.ts` | Add keypoint types |
| Modify | `react-web/src/components/dashboard/InferenceOverlay.tsx` | Add skeleton rendering |
| Modify | `deploy_greengrass_components.py` | Add yolo26pose to shadow config |

---

## Task 1: Model Export Script

**Files:**
- Create: `scripts/export-yolo26-pose.sh`

This script runs on the development machine (not the device) to export YOLO26s-pose to OpenVINO IR format.

- [ ] **Step 1: Create the export script**

```bash
#!/bin/bash
set -euo pipefail

OUTPUT_DIR="./yolo26s-pose_openvino_model"
VENV_DIR="./venv-yolo26-export"

echo "=== Exporting YOLO26s-pose to OpenVINO IR ==="

# Create and activate venv
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python venv..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# Install dependencies
echo "Installing ultralytics..."
pip install --quiet --upgrade pip
pip install --quiet "ultralytics>=26.0.0" "openvino>=2025.0,<2026.0"

# Export model
python3 -c "
from ultralytics import YOLO

model = YOLO('yolo26s-pose.pt')
model.export(
    format='openvino',
    imgsz=640,
    half=False,
    dynamic=False,
    end2end=False,
)
print('Export complete.')
"

deactivate

echo "=== Export complete ==="
echo "Model directory: $OUTPUT_DIR"
echo "Model size: $(du -sh "$OUTPUT_DIR" | cut -f1)"
echo ""
echo "Next steps:"
echo "  1. Verify the model loads: python3 -c \"import openvino as ov; m = ov.Core().read_model('$OUTPUT_DIR/yolo26s-pose.xml'); print([o.shape for o in m.outputs])\""
echo "  2. Copy model files to ovms-engine/components/model-yolo26pose/1/"
```

- [ ] **Step 2: Make the script executable**

Run: `chmod +x scripts/export-yolo26-pose.sh`

- [ ] **Step 3: Commit**

```bash
git add scripts/export-yolo26-pose.sh
git commit -m "feat: add YOLO26s-pose OpenVINO export script"
```

---

## Task 2: Snap Component Definition

**Files:**
- Create: `ovms-engine/components/model-yolo26pose/manifest.json`
- Create: `ovms-engine/components/model-yolo26pose/component.yaml`
- Create: `ovms-engine/components/model-yolo26pose/labels.txt`
- Modify: `ovms-engine/snap/snapcraft.yaml`

- [ ] **Step 1: Create manifest.json**

```json
{
    "model_id": "yolo26pose",
    "model_name": "yolo26pose",
    "version": "1.0.0",
    "input_name": "x",
    "output_names": ["output0"],
    "input_shape": [1, 3, 640, 640],
    "input_dtype": "float32",
    "normalize": true,
    "output_format": "yolo26-pose",
    "num_keypoints": 17,
    "labels_file": "labels.txt"
}
```

Note: `output_format: "yolo26-pose"` is used by the inference handler to route to the correct postprocessor. The `num_keypoints` field allows future models with different keypoint counts.

- [ ] **Step 2: Create component.yaml**

```yaml
environment:
  - MODEL_YOLO26POSE_PATH=$COMPONENT
```

- [ ] **Step 3: Create labels.txt**

```
person
```

- [ ] **Step 4: Register component in snapcraft.yaml**

Add to the `component-local-files` part's `organize` section (after the model-yolov8s line):

```yaml
      "model-yolo26pose/*": (component/model-yolo26pose)/
```

Add to the `components` section (after model-yolov8s):

```yaml
  model-yolo26pose:
    type: standard
    summary: YOLO26s pose estimation model (OpenVINO IR)
    description: |
      YOLO26s-pose 17-keypoint COCO pose estimation model in OpenVINO IR
      format. 9.5M parameters, 640x640 input. Detects people and outputs
      skeleton keypoints for wireframe visualisation. Requires NMS
      postprocessing (end2end=false export).
      Includes manifest.json with model metadata for auto-configuration.
```

- [ ] **Step 5: Commit**

```bash
git add ovms-engine/components/model-yolo26pose/ ovms-engine/snap/snapcraft.yaml
git commit -m "feat: add yolo26pose snap component definition"
```

---

## Task 3: Inference Handler — Pose Postprocessor

**Files:**
- Modify: `greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/inference_handler.py`

This is the most complex task. The postprocessor must:
1. Detect YOLO26-pose output by checking `output_format` in metadata (preferred) or tensor shape
2. Parse the `[1, 56, 8400]` tensor into bounding boxes + keypoints
3. Apply NMS (reuse existing `_nms` method)
4. Normalize coordinates to [0, 1] range
5. Publish results with a `"pose"` result_type including keypoints

- [ ] **Step 1: Add pose output format detection**

Add this method after `_is_yolov8_output` (around line 364):

```python
    def _is_yolo_pose_output(self, result_dict):
        """Detect YOLO pose output: output_format is 'yolo26-pose' in metadata,
        or shape [1, 56, N] where 56 = 4 + 1 + 17*3."""
        output_format = self.model_metadata.get("output_format", "")
        if output_format == "yolo26-pose":
            return True
        num_kp = self.model_metadata.get("num_keypoints", 0)
        if num_kp > 0:
            expected_dim1 = 4 + 1 + num_kp * 3
            for val in result_dict.values():
                if hasattr(val, 'shape') and len(val.shape) == 3:
                    _, dim1, dim2 = val.shape
                    if dim1 == expected_dim1 and dim2 > dim1:
                        return True
        return False
```

- [ ] **Step 2: Add pose postprocessor method**

Add this method after `_postprocess_yolov8` (around line 441):

```python
    def _postprocess_yolo_pose(self, result_dict, frame_width, frame_height, inference_time_ms):
        """Parse YOLO pose output: single tensor [1, 4+1+num_kp*3, num_detections].

        For YOLO26s-pose with 17 COCO keypoints: [1, 56, 8400]
        Per detection (transposed): [x_c, y_c, w, h, conf, kp0_x, kp0_y, kp0_conf, ...]
        """
        output = None
        for val in result_dict.values():
            if hasattr(val, 'shape') and len(val.shape) == 3:
                output = val
                break
        if output is None:
            return None

        num_keypoints = self.model_metadata.get("num_keypoints", 17)
        predictions = np.squeeze(output).T  # [8400, 56]

        boxes_xywh = predictions[:, :4]
        scores = predictions[:, 4]
        kp_data = predictions[:, 5:]  # [8400, 51] for 17 keypoints

        mask = scores > self.confidence_threshold
        boxes_xywh = boxes_xywh[mask]
        scores = scores[mask]
        kp_data = kp_data[mask]

        if len(scores) == 0:
            return None

        input_shape = self.model_metadata.get("input_shape", [1, 3, 640, 640])
        input_h = input_shape[2]
        input_w = input_shape[3]

        # Convert boxes from xywh to normalized xyxy
        boxes_xyxy = np.zeros((len(boxes_xywh), 4))
        boxes_xyxy[:, 0] = (boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2) / input_w
        boxes_xyxy[:, 1] = (boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2) / input_h
        boxes_xyxy[:, 2] = (boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2) / input_w
        boxes_xyxy[:, 3] = (boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2) / input_h

        # NMS
        indices = self._nms(boxes_xyxy, scores, iou_threshold=0.5)
        boxes_xyxy = boxes_xyxy[indices]
        scores = scores[indices]
        kp_data = kp_data[indices]

        # Limit detections
        max_det = 20
        if len(scores) > max_det:
            top_indices = np.argsort(scores)[::-1][:max_det]
            boxes_xyxy = boxes_xyxy[top_indices]
            scores = scores[top_indices]
            kp_data = kp_data[top_indices]

        detections = []
        for i in range(len(scores)):
            # Parse keypoints: reshape [51] -> [17, 3] then normalize
            kps_raw = kp_data[i].reshape(num_keypoints, 3)
            keypoints = []
            for k in range(num_keypoints):
                kp_x = float(kps_raw[k, 0]) / input_w
                kp_y = float(kps_raw[k, 1]) / input_h
                kp_conf = float(kps_raw[k, 2])
                keypoints.append({
                    "x": round(np.clip(kp_x, 0, 1), 4),
                    "y": round(np.clip(kp_y, 0, 1), 4),
                    "confidence": round(kp_conf, 4),
                })

            detections.append({
                "label": "person",
                "score": round(float(scores[i]), 4),
                "box": {
                    "xmin": round(float(np.clip(boxes_xyxy[i, 0], 0, 1)), 4),
                    "ymin": round(float(np.clip(boxes_xyxy[i, 1], 0, 1)), 4),
                    "xmax": round(float(np.clip(boxes_xyxy[i, 2], 0, 1)), 4),
                    "ymax": round(float(np.clip(boxes_xyxy[i, 3], 0, 1)), 4),
                },
                "keypoints": keypoints,
            })

        if not detections:
            return None

        return {
            "timestamp": time.time(),
            "model_id": self.active_model_id,
            "model_name": self.model_metadata.get("model_name", ""),
            "result_type": "pose",
            "results": {"detections": detections, "count": len(detections)},
            "inference_time_ms": inference_time_ms,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "confidence_threshold": self.confidence_threshold,
        }
```

- [ ] **Step 3: Update `_postprocess` routing to check pose BEFORE yolov8**

Replace the `_postprocess` method's format detection (lines 323-336):

```python
    def _postprocess(self, result, output_names, frame_width, frame_height, inference_time_ms):
        result_dict = self._normalize_result(result)

        # Auto-detect output format:
        # Format 0: YOLO pose (check FIRST — shape overlaps with YOLOv8 detection)
        # Format 1: YOLOv8 single-tensor [1, 84, 8400] (transposed detection grid)
        # Format 2: OpenVINO zoo single-tensor [1,1,N,7] (detection_out)
        # Format 3: TF2 multi-tensor (detection_boxes, detection_scores, detection_classes)
        if self._is_yolo_pose_output(result_dict):
            return self._postprocess_yolo_pose(result_dict, frame_width, frame_height, inference_time_ms)
        if self._is_yolov8_output(result_dict):
            return self._postprocess_yolov8(result_dict, frame_width, frame_height, inference_time_ms)
        if self._is_tf2_detection_output(result_dict):
            return self._postprocess_tf2_detection(result_dict, frame_width, frame_height, inference_time_ms)
        if "detection_out" in output_names or self._is_ov_detection_output(result_dict):
            return self._postprocess_ov_detection(result_dict, frame_width, frame_height, inference_time_ms)
        return self._postprocess_classification(result_dict, inference_time_ms)
```

- [ ] **Step 4: Verify existing models still work**

The key invariant: `_is_yolo_pose_output` returns `False` for YOLOv8s because:
- YOLOv8s manifest has `"output_format": "yolov8"` (not `"yolo26-pose"`)
- YOLOv8s manifest has no `"num_keypoints"` field

So the routing remains: yolov8s → `_postprocess_yolov8`, yolo26pose → `_postprocess_yolo_pose`.

- [ ] **Step 5: Commit**

```bash
git add greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/inference_handler.py
git commit -m "feat: add YOLO26-pose postprocessor to inference handler"
```

---

## Task 4: React Types — Add Keypoint & Pose Types

**Files:**
- Modify: `react-web/src/types/inference.ts`

- [ ] **Step 1: Add keypoint types and extend InferenceResult**

Replace the entire contents of `react-web/src/types/inference.ts` with:

```typescript
export interface BoundingBox {
  xmin: number;
  ymin: number;
  xmax: number;
  ymax: number;
}

export interface Keypoint {
  x: number;
  y: number;
  confidence: number;
}

export interface Detection {
  label: string;
  score: number;
  box: BoundingBox;
  keypoints?: Keypoint[];
}

export interface Classification {
  label: string;
  confidence: number;
  class_index: number;
}

export interface DetectionResults {
  detections: Detection[];
  count: number;
}

export interface ClassificationResults {
  classifications: Classification[];
}

export interface InferenceResult {
  timestamp: number;
  model_id: string;
  model_name: string;
  result_type: 'detection' | 'classification' | 'pose';
  results: DetectionResults | ClassificationResults;
  inference_time_ms: number;
  frame_width?: number;
  frame_height?: number;
  confidence_threshold?: number;
}
```

Changes: Added `Keypoint` interface, added optional `keypoints` to `Detection`, added `'pose'` to `result_type` union.

- [ ] **Step 2: Commit**

```bash
git add react-web/src/types/inference.ts
git commit -m "feat: add Keypoint type and pose result_type to inference types"
```

---

## Task 5: React InferenceOverlay — Skeleton Wireframe Rendering

**Files:**
- Modify: `react-web/src/components/dashboard/InferenceOverlay.tsx`

- [ ] **Step 1: Add skeleton constants and pose drawing function**

Add these constants after the existing `STALE_TIMEOUT_MS` constant (line 14):

```typescript
const SKELETON_COLOR = '#00ccff';
const KEYPOINT_COLOR = '#ff3366';
const KEYPOINT_RADIUS = 4;
const SKELETON_LINE_WIDTH = 2;
const KEYPOINT_CONFIDENCE_THRESHOLD = 0.3;

// COCO skeleton connections (0-indexed keypoint pairs)
const SKELETON_CONNECTIONS: [number, number][] = [
  [15, 13], [13, 11], [16, 14], [14, 12], [11, 12],
  [5, 11], [6, 12], [5, 6], [5, 7], [6, 8],
  [7, 9], [8, 10], [1, 2], [0, 1], [0, 2],
  [1, 3], [2, 4], [3, 5], [4, 6],
];
```

- [ ] **Step 2: Add the drawPoseDetections function**

Add this function after the existing `drawClassificationBadge` function:

```typescript
function drawPoseDetections(
  ctx: CanvasRenderingContext2D,
  detections: Detection[],
  canvasWidth: number,
  canvasHeight: number
) {
  for (const det of detections) {
    // Draw bounding box
    const x = det.box.xmin * canvasWidth;
    const y = det.box.ymin * canvasHeight;
    const w = (det.box.xmax - det.box.xmin) * canvasWidth;
    const h = (det.box.ymax - det.box.ymin) * canvasHeight;

    ctx.strokeStyle = BOX_COLOR;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(x, y, w, h);
    ctx.setLineDash([]);

    // Draw label
    const label = `${det.label} ${(det.score * 100).toFixed(0)}%`;
    ctx.font = FONT;
    const textWidth = ctx.measureText(label).width;
    ctx.fillStyle = TEXT_BG;
    ctx.fillRect(x, y - 20, textWidth + 8, 20);
    ctx.fillStyle = TEXT_COLOR;
    ctx.fillText(label, x + 4, y - 5);

    // Draw skeleton
    if (!det.keypoints || det.keypoints.length < 17) continue;

    // Draw connections (lines between keypoints)
    ctx.strokeStyle = SKELETON_COLOR;
    ctx.lineWidth = SKELETON_LINE_WIDTH;
    for (const [i, j] of SKELETON_CONNECTIONS) {
      const kpA = det.keypoints[i];
      const kpB = det.keypoints[j];
      if (kpA.confidence < KEYPOINT_CONFIDENCE_THRESHOLD) continue;
      if (kpB.confidence < KEYPOINT_CONFIDENCE_THRESHOLD) continue;

      const ax = kpA.x * canvasWidth;
      const ay = kpA.y * canvasHeight;
      const bx = kpB.x * canvasWidth;
      const by = kpB.y * canvasHeight;

      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
      ctx.stroke();
    }

    // Draw keypoint circles
    for (const kp of det.keypoints) {
      if (kp.confidence < KEYPOINT_CONFIDENCE_THRESHOLD) continue;
      const kx = kp.x * canvasWidth;
      const ky = kp.y * canvasHeight;

      ctx.beginPath();
      ctx.arc(kx, ky, KEYPOINT_RADIUS, 0, 2 * Math.PI);
      ctx.fillStyle = KEYPOINT_COLOR;
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }
}
```

- [ ] **Step 3: Update the useEffect to handle 'pose' result_type**

Replace the rendering block inside the useEffect (lines 44-52) with:

```typescript
    if (result.result_type === 'detection') {
      const detections = (result.results as { detections: Detection[] }).detections ?? [];
      drawDetections(ctx, detections, canvas.width, canvas.height);
    } else if (result.result_type === 'pose') {
      const detections = (result.results as { detections: Detection[] }).detections ?? [];
      drawPoseDetections(ctx, detections, canvas.width, canvas.height);
    } else if (result.result_type === 'classification') {
      const classifications = (result.results as { classifications: { label: string; confidence: number }[] }).classifications;
      if (classifications.length > 0) {
        drawClassificationBadge(ctx, classifications[0], canvas.width);
      }
    }
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd react-web && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 5: Commit**

```bash
git add react-web/src/components/dashboard/InferenceOverlay.tsx
git commit -m "feat: add skeleton wireframe rendering for pose model results"
```

---

## Task 6: Deployment Config Update

**Files:**
- Modify: `deploy_greengrass_components.py`

- [ ] **Step 1: Add yolo26pose to model-config shadow**

In `deploy_greengrass_components.py`, in the `ensure_device_shadows` method, add to the `model-config` shadow's `models` dict (after the `yolov8s` entry around line 359):

```python
                        'yolo26pose': {'source': 'snap', 'type': 'cv'},
```

- [ ] **Step 2: Commit**

```bash
git add deploy_greengrass_components.py
git commit -m "feat: add yolo26pose to default model-config shadow"
```

---

## Task 7: Validate Model Export & Tensor Shape

This task validates the full pipeline before packaging into the snap. Run on a development machine with GPU/CPU.

**Files:**
- No file changes — validation only

- [ ] **Step 1: Run the export script**

Run: `./scripts/export-yolo26-pose.sh`
Expected: Creates `yolo26s-pose_openvino_model/` directory with `.xml`, `.bin`, and `metadata.yaml` files.

- [ ] **Step 2: Verify output tensor shape**

Run:
```bash
python3 -c "
import openvino as ov
core = ov.Core()
model = core.read_model('yolo26s-pose_openvino_model/yolo26s-pose.xml')
for output in model.outputs:
    print(f'{output.get_any_name()}: {output.shape}')
for inp in model.inputs:
    print(f'Input: {inp.get_any_name()}: {inp.shape}')
"
```
Expected output (approximately):
```
output0: [1, 56, 8400]
Input: x: [1, 3, 640, 640]
```

**If the output shape is different** (e.g., `[1, 300, 56]` meaning end2end was not respected, or different tensor name), update `manifest.json` fields:
- Change `input_name` if the input tensor name differs from `"x"`
- Change `output_names` if the output tensor name differs from `"output0"`
- If shape is `[1, 300, 56]`, we need to adjust the postprocessor to not transpose and skip NMS

- [ ] **Step 3: Copy model files to component directory**

Run:
```bash
mkdir -p ovms-engine/components/model-yolo26pose/1/
cp yolo26s-pose_openvino_model/yolo26s-pose.xml ovms-engine/components/model-yolo26pose/1/yolo26pose.xml
cp yolo26s-pose_openvino_model/yolo26s-pose.bin ovms-engine/components/model-yolo26pose/1/yolo26pose.bin
```

Note: Model files go in a `1/` subdirectory — this is OVMS's versioning convention (see `model-efficientnet/1/`). The model files themselves are `.gitignore`d due to size; they're packaged into the snap during build.

- [ ] **Step 4: Test with local OVMS (optional but recommended)**

If OVMS is available locally via Docker:
```bash
docker run -d --rm -p 9000:9000 -p 8081:8081 \
  -v $(pwd)/ovms-engine/components/model-yolo26pose:/models/yolo26pose \
  openvino/model_server:2025.0 \
  --model_name yolo26pose \
  --model_path /models/yolo26pose \
  --port 9000

# Test inference
python3 -c "
from ovmsclient import make_grpc_client
import numpy as np
client = make_grpc_client('localhost:9000')
input_data = np.random.rand(1, 3, 640, 640).astype(np.float32)
result = client.predict({'x': input_data}, 'yolo26pose')
print(f'Result type: {type(result)}')
if hasattr(result, 'shape'):
    print(f'Shape: {result.shape}')
elif isinstance(result, dict):
    for k, v in result.items():
        print(f'{k}: shape={v.shape}')
"
```

---

## Task 8: Snap Build & Integration Test

**Files:**
- No source changes — build validation

- [ ] **Step 1: Verify snapcraft.yaml is valid**

Run: `cd ovms-engine && snapcraft --destructive-mode --dry-run` (or just validate YAML syntax)

- [ ] **Step 2: Build the snap**

Run: `cd ovms-engine && snapcraft --destructive-mode`
Expected: Snap builds successfully with the new `model-yolo26pose` component included.

- [ ] **Step 3: Verify component is installable**

Run: `snap info ovms-engine_*.snap` or install on a test device and verify:
```bash
sudo snap install ovms-engine_1.0.0_amd64.snap --dangerous
ovms-engine components list
```
Expected: `model-yolo26pose` appears in the component list.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| YOLO26 export produces unexpected tensor shape | Medium | High | Task 7 validates shape before integration; postprocessor uses metadata-driven routing |
| OpenVINO IR version too new for OVMS 2025.0 | Low | High | Pin `openvino>=2025.0,<2026.0` in export script |
| Ultralytics 26.x not yet released / API changes | Low | Medium | The metadata.yaml shows it's already available (version field exists in docs); fallback to YOLOv8-pose if YOLO26 unavailable |
| OVMS gRPC response format differs for pose model | Low | Medium | Task 7 step 4 validates end-to-end with OVMS before device deployment |
| Keypoint rendering performance on complex scenes | Low | Low | Cap at 20 detections; keypoint confidence threshold filters noise |

---

## MQTT Message Format (for reference)

The inference handler will publish pose results to `camera/inference` with this structure:

```json
{
  "timestamp": 1717430000.123,
  "model_id": "yolo26pose",
  "model_name": "yolo26pose",
  "result_type": "pose",
  "results": {
    "detections": [
      {
        "label": "person",
        "score": 0.92,
        "box": {"xmin": 0.1, "ymin": 0.15, "xmax": 0.4, "ymax": 0.85},
        "keypoints": [
          {"x": 0.25, "y": 0.18, "confidence": 0.95},
          {"x": 0.24, "y": 0.16, "confidence": 0.88},
          {"x": 0.26, "y": 0.16, "confidence": 0.91},
          ...
        ]
      }
    ],
    "count": 1
  },
  "inference_time_ms": 38.5,
  "frame_width": 1280,
  "frame_height": 720,
  "confidence_threshold": 0.4
}
```

The React frontend's `useInferenceResults` hook already handles this — it parses any JSON with `result_type` and `results` fields from the `camera/inference` topic.
