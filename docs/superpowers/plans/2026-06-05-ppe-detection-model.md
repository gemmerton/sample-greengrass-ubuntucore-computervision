# PPE Detection Model Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PPE (Personal Protective Equipment) detection model that identifies hard hats, safety vests, safety goggles, gloves, and masks — served through the existing OVMS infrastructure and rendered in the React UI with bounding boxes and PPE-class labels.

**Architecture:** Fine-tune YOLO11s (latest stable, well-supported OpenVINO export) on a curated PPE dataset, export to OpenVINO IR format at 640x640, and integrate as a new snap component `model-ppe-detection` alongside existing models. The output tensor format matches YOLOv8/YOLO11 detection format `[1, num_classes+4, 8400]`, so the existing `_postprocess_yolov8` handler works without modification — only labels differ.

**Tech Stack:** Ultralytics >= 8.4.0 (YOLO11 ships in the 8.x package), OpenVINO IR format, Python/numpy (inference handler), React/TypeScript (frontend labels), OVMS gRPC (serving)

---

## Model Selection Rationale

### Why YOLO11s (not YOLO26s)?

| Factor | YOLO11s | YOLO26s |
|--------|---------|---------|
| OpenVINO export stability | Mature, well-tested | Very new, export quirks possible |
| Fine-tuning ecosystem | Extensive tutorials, proven PPE results | Limited community fine-tuning examples |
| Output format | `[1, 84+N, 8400]` — matches existing postprocessor | Same format, but `end2end=True` default may differ |
| Edge performance (CPU) | ~65ms on Intel Core Ultra | ~87ms (larger architecture) |
| Accuracy (COCO mAP) | 47.0 | 48.6 |
| Community PPE models | Many available as starting weights | None yet |

**Decision:** Use **YOLO11s** for the PPE model. It's the best balance of stability, ecosystem support for fine-tuning, and proven OpenVINO compatibility. The 2% mAP gap vs YOLO26s is irrelevant when fine-tuning on a domain-specific dataset — fine-tuning quality dominates.

### PPE Classes (7 classes)

```
0: hard-hat
1: no-hard-hat
2: safety-vest
3: no-safety-vest
4: safety-goggles
5: gloves
6: mask
```

Including "no-hard-hat" and "no-safety-vest" negative classes is standard practice for PPE models — it enables compliance detection (detecting a person's head WITHOUT a hard hat is as important as detecting the hat itself).

### Dataset Recommendation

**Primary:** [Roboflow Construction Safety PPE Dataset](https://universe.roboflow.com/roboflow-universe-projects/construction-site-safety) — 2,800+ images, 6 PPE classes, YOLO format, permissive license. Well-annotated, diverse conditions.

**Alternative / augmentation:** Combine with [Safety Helmet Detection Dataset](https://www.kaggle.com/datasets/andrewmvd/hard-hat-detection) (5,000 images) for hard hat robustness.

**Target:** Minimum 1,500 images per class after augmentation for production-quality results.

---

## File Structure

```
ovms-engine/components/model-ppe-detection/
├── manifest.json          # Model metadata (input/output shapes, labels_file)
├── labels.txt             # 7 PPE class labels
├── component.yaml         # Snap component environment variable
└── 1/                     # Model version directory (created during export)
    ├── ppe_detection.xml  # OpenVINO IR model definition
    └── ppe_detection.bin  # OpenVINO IR model weights

scripts/
├── export-ppe-detection.sh        # Export/fine-tune script
└── ppe-training/                   # Training configuration (gitignored weights)
    └── ppe_dataset.yaml            # Ultralytics dataset config

ovms-engine/snap/snapcraft.yaml     # Add model-ppe-detection component
```

---

## Task 1: Create Model Component Metadata

**Files:**
- Create: `ovms-engine/components/model-ppe-detection/manifest.json`
- Create: `ovms-engine/components/model-ppe-detection/labels.txt`
- Create: `ovms-engine/components/model-ppe-detection/component.yaml`

- [ ] **Step 1: Create manifest.json**

```json
{
    "model_id": "ppe-detection",
    "model_name": "ppe_detection",
    "version": "1.0.0",
    "input_name": "images",
    "output_names": ["output0"],
    "input_shape": [1, 3, 640, 640],
    "input_dtype": "float32",
    "normalize": true,
    "output_format": "yolov8",
    "labels_file": "labels.txt"
}
```

Note: `input_name` is `"images"` for YOLO11 exports (differs from YOLOv8's `"x"`). Verify after export — if the export produces a different tensor name, update this field to match.

- [ ] **Step 2: Create labels.txt**

```
hard-hat
no-hard-hat
safety-vest
no-safety-vest
safety-goggles
gloves
mask
```

- [ ] **Step 3: Create component.yaml**

```yaml
environment:
  - MODEL_PPE_DETECTION_PATH=$COMPONENT
```

- [ ] **Step 4: Commit**

```bash
git add ovms-engine/components/model-ppe-detection/
git commit -m "feat(model): add PPE detection component metadata and labels"
```

---

## Task 2: Create Export / Fine-Tuning Script

**Files:**
- Create: `scripts/export-ppe-detection.sh`
- Create: `scripts/ppe-training/ppe_dataset.yaml`

- [ ] **Step 1: Create dataset configuration**

Create `scripts/ppe-training/ppe_dataset.yaml`:

```yaml
# PPE Detection Dataset Configuration
# Download dataset from Roboflow in YOLOv8 format and place in this directory.
# Expected structure:
#   scripts/ppe-training/
#   ├── ppe_dataset.yaml (this file)
#   ├── train/
#   │   ├── images/
#   │   └── labels/
#   ├── valid/
#   │   ├── images/
#   │   └── labels/
#   └── test/
#       ├── images/
#       └── labels/

path: ./scripts/ppe-training
train: train/images
val: valid/images
test: test/images

nc: 7
names:
  0: hard-hat
  1: no-hard-hat
  2: safety-vest
  3: no-safety-vest
  4: safety-goggles
  5: gloves
  6: mask
```

- [ ] **Step 2: Create export script**

Create `scripts/export-ppe-detection.sh`:

```bash
#!/bin/bash
set -euo pipefail

# PPE Detection Model: Fine-tune + Export to OpenVINO IR
#
# Prerequisites:
#   1. Download PPE dataset from Roboflow in YOLOv8 format
#      Place in scripts/ppe-training/{train,valid,test}/
#   2. Run this script from the repository root:
#      cd /path/to/repo && bash scripts/export-ppe-detection.sh
#
# Modes:
#   --export-only   Skip training, just export an existing best.pt
#   --pretrained    Use a pre-trained PPE model (provide .pt path as next arg)

MODEL_SIZE="yolo11s"  # small: best speed/accuracy trade-off for edge
OUTPUT_DIR="./scripts/ppe_detection_openvino_model"
VENV_DIR="./scripts/venv-ppe-export"
DATASET_YAML="./scripts/ppe-training/ppe_dataset.yaml"
EPOCHS=300
BATCH=16
IMGSZ=640

EXPORT_ONLY=false
PRETRAINED_PATH=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --export-only) EXPORT_ONLY=true; shift ;;
        --pretrained) PRETRAINED_PATH="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=== PPE Detection Model Pipeline ==="
echo "Model: ${MODEL_SIZE}"
echo "Image size: ${IMGSZ}x${IMGSZ}"

# Create and activate venv
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python venv..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# Install dependencies
echo "Installing ultralytics + openvino..."
pip install --quiet --upgrade pip
pip install --quiet "ultralytics>=8.4.0" "openvino>=2024.0"

if [ "$EXPORT_ONLY" = true ]; then
    echo "=== Export-only mode ==="
    BEST_PT="${PRETRAINED_PATH:-./scripts/ppe-training/runs/detect/train/weights/best.pt}"
    if [ ! -f "$BEST_PT" ]; then
        echo "ERROR: No trained model found at $BEST_PT"
        echo "Run training first (without --export-only) or provide --pretrained <path>"
        exit 1
    fi
elif [ -n "$PRETRAINED_PATH" ]; then
    echo "=== Using pre-trained model: $PRETRAINED_PATH ==="
    BEST_PT="$PRETRAINED_PATH"
else
    echo "=== Training Phase ==="
    if [ ! -f "$DATASET_YAML" ]; then
        echo "ERROR: Dataset config not found at $DATASET_YAML"
        echo "Download PPE dataset from Roboflow and place in scripts/ppe-training/"
        exit 1
    fi

    python3 -c "
from ultralytics import YOLO

model = YOLO('${MODEL_SIZE}.pt')
results = model.train(
    data='${DATASET_YAML}',
    epochs=${EPOCHS},
    batch=${BATCH},
    imgsz=${IMGSZ},
    project='./scripts/ppe-training/runs/detect',
    name='train',
    exist_ok=True,
    patience=50,
    save=True,
    plots=True,
)
print(f'Training complete. Best mAP50: {results.results_dict.get(\"metrics/mAP50(B)\", \"N/A\")}')
"
    BEST_PT="./scripts/ppe-training/runs/detect/train/weights/best.pt"
fi

echo "=== Export Phase ==="
echo "Exporting $BEST_PT to OpenVINO IR..."

python3 -c "
from ultralytics import YOLO

model = YOLO('${BEST_PT}')
model.export(
    format='openvino',
    imgsz=${IMGSZ},
    half=False,
    dynamic=False,
    end2end=False,
)
print('Export complete.')
"

deactivate

echo "=== Export complete ==="
echo "Model directory: $OUTPUT_DIR"
echo ""
echo "Next steps:"
echo "  1. Verify model: python3 -c \"import openvino as ov; m = ov.Core().read_model('$OUTPUT_DIR/best.xml'); print([o.shape for o in m.outputs])\""
echo "  2. Copy to snap component:"
echo "     mkdir -p ovms-engine/components/model-ppe-detection/1/"
echo "     cp $OUTPUT_DIR/best.xml ovms-engine/components/model-ppe-detection/1/ppe_detection.xml"
echo "     cp $OUTPUT_DIR/best.bin ovms-engine/components/model-ppe-detection/1/ppe_detection.bin"
echo "  3. Verify manifest.json input_name matches export (check metadata.yaml in output dir)"
echo "  4. Rebuild snap: cd ovms-engine && snapcraft --destructive-mode"
```

- [ ] **Step 3: Make script executable and commit**

```bash
chmod +x scripts/export-ppe-detection.sh
git add scripts/export-ppe-detection.sh scripts/ppe-training/ppe_dataset.yaml
git commit -m "feat(model): add PPE detection training and export script"
```

---

## Task 3: Register Component in Snap

**Files:**
- Modify: `ovms-engine/snap/snapcraft.yaml`

- [ ] **Step 1: Add organize rule in component-local-files part**

In the `component-local-files` part's `organize` section (around line 122), add:

```yaml
      "model-ppe-detection/*": (component/model-ppe-detection)/
```

After existing model entries.

- [ ] **Step 2: Add snap component definition**

In the `components:` section (after the `model-yolo26pose` block, around line 225), add:

```yaml
  model-ppe-detection:
    type: standard
    summary: PPE detection model (OpenVINO IR)
    description: |
      YOLO11s-based PPE (Personal Protective Equipment) detection model
      fine-tuned for 7 classes: hard-hat, no-hard-hat, safety-vest,
      no-safety-vest, safety-goggles, gloves, mask. 640x640 input,
      OpenVINO IR format. Requires NMS postprocessing (end2end=false).
      Includes manifest.json with model metadata for auto-configuration.
```

- [ ] **Step 3: Commit**

```bash
git add ovms-engine/snap/snapcraft.yaml
git commit -m "feat(snap): register model-ppe-detection component in snapcraft.yaml"
```

---

## Task 4: Verify Inference Handler Compatibility

The existing `_postprocess_yolov8` handler in `inference_handler.py` already supports any model with `output_format: "yolov8"` — it reads label count from the tensor shape dynamically (`class_scores = predictions[:, 4:]`). No code changes needed for inference.

**Files:**
- Create: `tests/test_ppe_detection_inference.py`

- [ ] **Step 1: Write test verifying PPE model output parsing**

```python
"""Unit tests verifying PPE detection model output is correctly parsed.

The PPE model uses the same YOLOv8 output format [1, 11, 8400] where
11 = 4 (box coords) + 7 (PPE classes). This test confirms the existing
_postprocess_yolov8 path handles 7-class PPE output correctly.
"""

import sys
import os
import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.InferenceHandler', '1.0.0'
))

mock_clientv2 = MagicMock()
sys.modules['awsiot'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc.clientv2'] = mock_clientv2

mock_ovmsclient = MagicMock()
sys.modules['ovmsclient'] = mock_ovmsclient

from tests.conftest import real_cv2 as _real_cv2
sys.modules['cv2'] = _real_cv2

if 'inference_handler' in sys.modules:
    del sys.modules['inference_handler']

import inference_handler
inference_handler.cv2 = _real_cv2
from inference_handler import InferenceHandler


PPE_LABELS = {
    0: "hard-hat",
    1: "no-hard-hat",
    2: "safety-vest",
    3: "no-safety-vest",
    4: "safety-goggles",
    5: "gloves",
    6: "mask",
}

PPE_METADATA = {
    "model_id": "ppe-detection",
    "model_name": "ppe_detection",
    "input_name": "images",
    "output_names": ["output0"],
    "input_shape": [1, 3, 640, 640],
    "input_dtype": "float32",
    "normalize": True,
    "output_format": "yolov8",
    "labels_file": "labels.txt",
}


@pytest.fixture
def handler():
    with patch.dict(os.environ, {
        "AWS_IOT_THING_NAME": "",
        "OVMS_GRPC_URL": "localhost:9000",
    }):
        h = InferenceHandler()
        h.model_metadata = PPE_METADATA
        h.active_model_id = "ppe-detection"
        h.labels = PPE_LABELS
        h.confidence_threshold = 0.5
        return h


def _make_yolov8_output(detections, num_classes=7, grid_size=8400):
    """Create a synthetic YOLOv8 output tensor [1, 4+num_classes, grid_size].

    detections: list of (cx, cy, w, h, class_id, score) in pixel coords (640x640).
    """
    output = np.zeros((1, 4 + num_classes, grid_size), dtype=np.float32)
    for i, (cx, cy, w, h, class_id, score) in enumerate(detections):
        if i >= grid_size:
            break
        output[0, 0, i] = cx
        output[0, 1, i] = cy
        output[0, 2, i] = w
        output[0, 3, i] = h
        output[0, 4 + class_id, i] = score
    return output


class TestPpeDetectionOutput:
    """Verify the YOLOv8 postprocessor handles 7-class PPE output."""

    def test_detects_hard_hat(self, handler):
        # Hard hat detection at center of frame
        output = _make_yolov8_output([(320, 100, 80, 60, 0, 0.92)])
        result = handler._postprocess_yolov8(
            {"output0": output}, 1920, 1080, 25.0
        )
        assert result is not None
        assert result["result_type"] == "detection"
        assert result["model_id"] == "ppe-detection"
        assert len(result["results"]["detections"]) == 1
        det = result["results"]["detections"][0]
        assert det["label"] == "hard-hat"
        assert det["score"] >= 0.9

    def test_detects_multiple_ppe_classes(self, handler):
        # Hard hat + safety vest on same frame
        output = _make_yolov8_output([
            (320, 100, 80, 60, 0, 0.88),   # hard-hat
            (320, 300, 150, 200, 2, 0.85),  # safety-vest
        ])
        result = handler._postprocess_yolov8(
            {"output0": output}, 1920, 1080, 30.0
        )
        assert result is not None
        labels = {d["label"] for d in result["results"]["detections"]}
        assert "hard-hat" in labels
        assert "safety-vest" in labels

    def test_no_hard_hat_detection(self, handler):
        # Detects person without hard hat (compliance violation)
        output = _make_yolov8_output([(320, 100, 80, 60, 1, 0.78)])
        result = handler._postprocess_yolov8(
            {"output0": output}, 1920, 1080, 22.0
        )
        assert result is not None
        det = result["results"]["detections"][0]
        assert det["label"] == "no-hard-hat"

    def test_filters_below_threshold(self, handler):
        # Low-confidence detection should be filtered
        output = _make_yolov8_output([(320, 100, 80, 60, 0, 0.3)])
        result = handler._postprocess_yolov8(
            {"output0": output}, 1920, 1080, 20.0
        )
        assert result is None

    def test_output_shape_7_classes(self, handler):
        # Verify tensor shape [1, 11, 8400] is detected as yolov8 output
        output = np.random.rand(1, 11, 8400).astype(np.float32) * 0.01
        assert handler._is_yolov8_output({"output0": output}) is True
        assert handler._is_yolo_pose_output({"output0": output}) is False
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
pytest tests/test_ppe_detection_inference.py -v
```

Expected: All 5 tests PASS — confirming the existing postprocessor handles 7-class PPE output without modification.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ppe_detection_inference.py
git commit -m "test(ppe): verify inference handler handles PPE model output format"
```

---

## Task 5: Add .gitignore Entries for Training Artifacts

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add training artifact exclusions**

Add these entries to `.gitignore`:

```
# PPE model training artifacts
scripts/ppe-training/train/
scripts/ppe-training/valid/
scripts/ppe-training/test/
scripts/ppe-training/runs/
scripts/ppe_detection_openvino_model/
scripts/venv-ppe-export/

# Model weight binaries (large files)
ovms-engine/components/model-ppe-detection/1/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore PPE training artifacts and model weights"
```

---

## Task 6: Training & Export (Manual — Requires GPU Workstation)

This task is NOT automatable — it requires a workstation with GPU access and manual dataset download.

- [ ] **Step 1: Download PPE dataset from Roboflow**

1. Go to [Roboflow Construction Site Safety](https://universe.roboflow.com/roboflow-universe-projects/construction-site-safety)
2. Export in "YOLOv8" format
3. Extract to `scripts/ppe-training/{train,valid,test}/`
4. Verify class mapping in downloaded `data.yaml` matches `ppe_dataset.yaml` — if it differs, update `scripts/ppe-training/ppe_dataset.yaml` class names and `ovms-engine/components/model-ppe-detection/labels.txt` to match

- [ ] **Step 2: Run training + export**

```bash
bash scripts/export-ppe-detection.sh
```

Training takes ~2-4 hours on a GPU, ~12+ hours on CPU only.

- [ ] **Step 3: Verify exported model**

```bash
source scripts/venv-ppe-export/bin/activate
python3 -c "
import openvino as ov
m = ov.Core().read_model('scripts/ppe_detection_openvino_model/best.xml')
for o in m.outputs:
    print(f'Output: {o.get_any_name()} shape={o.shape}')
for i in m.inputs:
    print(f'Input: {i.get_any_name()} shape={i.shape}')
"
deactivate
```

Expected output:
```
Output: output0 shape=[1,11,8400]
Input: images shape=[1,3,640,640]
```

If tensor names differ, update `manifest.json` `input_name` and `output_names` to match.

- [ ] **Step 4: Copy model to snap component**

```bash
mkdir -p ovms-engine/components/model-ppe-detection/1/
cp scripts/ppe_detection_openvino_model/best.xml ovms-engine/components/model-ppe-detection/1/ppe_detection.xml
cp scripts/ppe_detection_openvino_model/best.bin ovms-engine/components/model-ppe-detection/1/ppe_detection.bin
```

- [ ] **Step 5: Test locally with Docker OVMS**

```bash
docker run -d --rm -p 9001:9000 \
  -v $(pwd)/ovms-engine/components/model-ppe-detection:/models/ppe_detection \
  openvino/model_server:2025.0 \
  --model_name ppe_detection \
  --model_path /models/ppe_detection \
  --port 9000

source scripts/venv-ppe-export/bin/activate
python3 -c "
from ovmsclient import make_grpc_client
import numpy as np
client = make_grpc_client('localhost:9001')
result = client.predict({'images': np.random.rand(1,3,640,640).astype(np.float32)}, 'ppe_detection')
if isinstance(result, dict):
    for k, v in result.items(): print(f'{k}: shape={v.shape}')
else:
    print(f'shape={result.shape}')
"
deactivate
docker stop $(docker ps -q --filter ancestor=openvino/model_server:2025.0)
```

---

## Task 7: Device Deployment

- [ ] **Step 1: Rebuild snap with new model component**

```bash
cd ovms-engine && snapcraft --destructive-mode
```

- [ ] **Step 2: Upload snap + component to S3**

Upload `ovms-engine_1.0.0_amd64.snap` and the `ovms-engine+model-ppe-detection_1.0.0.comp` file to the S3 bucket configured for the device.

- [ ] **Step 3: Install on device**

```bash
# SSH to device
sudo snap install ovms-engine_1.0.0_amd64.snap --dangerous
sudo snap install ovms-engine+model-ppe-detection --dangerous
```

Or via ModelManagerCore shadow provisioning:

```json
{
  "state": {
    "desired": {
      "provision_model": {
        "model_id": "ppe-detection",
        "source": "snap-component"
      }
    }
  }
}
```

- [ ] **Step 4: Switch active model via shadow**

```json
{
  "state": {
    "desired": {
      "active_model": "ppe-detection"
    }
  }
}
```

Or via the React UI model selector dropdown.

---

## Task 8: React UI Label Colours (Optional Enhancement)

**Files:**
- Modify: React inference overlay component (the file rendering bounding boxes)

- [ ] **Step 1: Add PPE-specific colour mapping**

Add a colour map so PPE classes render with meaningful colours:

```typescript
const PPE_COLORS: Record<string, string> = {
  "hard-hat": "#22c55e",       // green — compliant
  "no-hard-hat": "#ef4444",    // red — violation
  "safety-vest": "#22c55e",    // green — compliant
  "no-safety-vest": "#ef4444", // red — violation
  "safety-goggles": "#3b82f6", // blue
  "gloves": "#a855f7",         // purple
  "mask": "#06b6d4",           // cyan
};
```

This enables at-a-glance compliance status: green = good, red = violation.

- [ ] **Step 2: Commit**

```bash
git add <react-overlay-file>
git commit -m "feat(ui): add PPE-specific colour coding for compliance status"
```

---

## Summary: What's Automatable vs Manual

| Task | Automatable? | Notes |
|------|:---:|-------|
| 1. Component metadata | Yes | Files only |
| 2. Export script | Yes | Files only |
| 3. Snap registration | Yes | File edit |
| 4. Inference tests | Yes | Verify existing handler works |
| 5. Gitignore | Yes | File edit |
| 6. Training & export | **No** | Requires GPU + dataset download |
| 7. Device deployment | **No** | Requires device access |
| 8. UI colours | Yes | Optional enhancement |

Tasks 1-5 can be implemented immediately. Task 6 requires a build workstation with GPU access and manual dataset curation. Task 7 requires device access.

---

## Alternative: Pre-Trained PPE Model (Skip Training)

If you want to avoid fine-tuning entirely, several community-trained PPE models are available on Roboflow that can be downloaded as `.pt` files and exported directly:

```bash
# Example: download a pre-trained PPE model and export
bash scripts/export-ppe-detection.sh --pretrained /path/to/downloaded-ppe-model.pt
```

The trade-off: pre-trained community models may have different class names or fewer classes. You'd need to update `labels.txt` and `ppe_dataset.yaml` to match whatever the model was trained on.
