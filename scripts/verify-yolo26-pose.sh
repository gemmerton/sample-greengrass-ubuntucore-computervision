#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="${SCRIPT_DIR}/yolo26s-pose_openvino_model"
VENV_DIR="${SCRIPT_DIR}/venv-yolo26-export"

if [ ! -f "${MODEL_DIR}/yolo26s-pose.xml" ]; then
    echo "ERROR: Model file not found at ${MODEL_DIR}/yolo26s-pose.xml"
    echo "Run export-yolo26-pose.sh first."
    exit 1
fi

if [ ! -d "${VENV_DIR}" ]; then
    echo "ERROR: Virtual environment not found at ${VENV_DIR}"
    echo "Run export-yolo26-pose.sh first to create the venv."
    exit 1
fi

source "${VENV_DIR}/bin/activate"

python3 -c "
import openvino as ov

model_path = '${MODEL_DIR}/yolo26s-pose.xml'
m = ov.Core().read_model(model_path)

print('=== YOLO26-Pose Tensor Verification ===')
print()

for i in m.inputs:
    print(f'Input:  {i.get_any_name()} shape={i.shape}')
for o in m.outputs:
    print(f'Output: {o.get_any_name()} shape={o.shape}')

print()

# Validate expected shapes
input_ok = len(m.inputs) == 1 and list(m.inputs[0].shape) == [1, 3, 640, 640]
output_ok = len(m.outputs) == 1 and list(m.outputs[0].shape) == [1, 56, 8400]

if input_ok and output_ok:
    print('PASS: Shapes match expected [1,3,640,640] -> [1,56,8400]')
else:
    print('MISMATCH: Update ovms-engine/components/model-yolo26pose/manifest.json')
    print('  Expected input:  [1, 3, 640, 640]')
    print('  Expected output: [1, 56, 8400]')
    exit(1)
"

deactivate
