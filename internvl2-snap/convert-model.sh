#!/bin/bash
set -euo pipefail

OUTPUT_DIR="./components/model-internvl2-4b-ov-int4"
VENV_DIR="./venv-convert"

echo "=== Converting InternVL2-4B to OpenVINO INT4 ==="

# Create and activate venv
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python venv..."
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# Install dependencies
echo "Installing optimum-intel..."
pip install --quiet --upgrade pip
pip install --quiet "optimum[openvino]"

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/meta"

# Export model to OpenVINO format with INT4 quantization
optimum-cli export openvino \
    --model OpenGVLab/InternVL2-4B \
    --weight-format int4 \
    "$OUTPUT_DIR/InternVL2-4B-ov-int4"

deactivate

# Create component metadata
cat > "$OUTPUT_DIR/meta/component.yaml" << 'EOF'
component: internvl2+model-internvl2-4b-ov-int4
type: standard
summary: InternVL2-4B OpenVINO INT4
description: InternVL2-4B vision-language model in OpenVINO IR format, INT4 quantized
EOF

echo "=== Model conversion complete ==="
echo "Model size: $(du -sh "$OUTPUT_DIR/InternVL2-4B-ov-int4" | cut -f1)"
