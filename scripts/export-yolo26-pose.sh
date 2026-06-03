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
