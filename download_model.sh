#!/bin/bash

# Download and convert Faster R-CNN ResNet50 v1 (COCO 90-class) to OpenVINO IR format
# for the ovms-engine snap model component.
#
# This model detects 90 object categories (person, car, bicycle, dog, chair, etc.)
# and outputs in the TF2 multi-tensor detection format.
#
# Prerequisites:
#   pip install openvino openvino-dev[tensorflow2] tensorflow
#
# Output files go into ovms-engine/components/model-faster-rcnn/1/
# which is the OVMS model repository layout (model_name/version/model.xml+bin)

set -e

COMPONENT_DIR="ovms-engine/components/model-faster-rcnn"
MODEL_DIR="$COMPONENT_DIR/1"
TEMP_DIR="temp_model_download"

echo "=== Faster R-CNN ResNet50 v1 640x640 (COCO 90-class) ==="
echo ""

# Create directories
mkdir -p "$MODEL_DIR"
mkdir -p "$TEMP_DIR"

# Step 1: Download
echo "Step 1: Downloading model from Kaggle..."
curl -L --progress-bar \
    https://www.kaggle.com/api/v1/models/tensorflow/faster-rcnn-resnet-v1/tensorFlow2/faster-rcnn-resnet50-v1-640x640/1/download \
    -o "$TEMP_DIR/model.tar.gz"

# Step 2: Extract
echo "Step 2: Extracting..."
tar xzf "$TEMP_DIR/model.tar.gz" -C "$TEMP_DIR"

# Step 3: Convert to OpenVINO IR
echo "Step 3: Converting to OpenVINO IR format with ovc..."
ovc "$TEMP_DIR/saved_model" \
    --output_model "$MODEL_DIR/saved_model"

# Step 4: Verify
echo ""
echo "Step 4: Verifying output..."
if [ -f "$MODEL_DIR/saved_model.xml" ] && [ -f "$MODEL_DIR/saved_model.bin" ]; then
    echo "  $MODEL_DIR/saved_model.xml ($(du -h "$MODEL_DIR/saved_model.xml" | cut -f1))"
    echo "  $MODEL_DIR/saved_model.bin ($(du -h "$MODEL_DIR/saved_model.bin" | cut -f1))"
    echo ""
    echo "Conversion successful."
else
    echo "ERROR: Expected output files not found."
    echo "Ensure openvino-dev is installed: pip install openvino-dev[tensorflow2]"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Clean up temp download
rm -rf "$TEMP_DIR"

echo ""
echo "=== Done ==="
echo ""
echo "Component directory: $COMPONENT_DIR/"
echo "  manifest.json         - model metadata (NHWC uint8 640x640, TF2 output format)"
echo "  labels.txt            - COCO 91-class labels (index 0 = background)"
echo "  1/saved_model.xml     - OpenVINO IR graph"
echo "  1/saved_model.bin     - OpenVINO IR weights"
echo ""
echo "Next steps:"
echo "  1. Rebuild the ovms-engine snap to include this model component"
echo "  2. Install the snap on the device: sudo snap install ovms-engine+model-faster-rcnn.snap --devmode"
echo "  3. Add 'faster-rcnn' to desired.models in the shadow with type: 'cv'"
