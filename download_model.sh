#!/bin/bash

# Download and prepare OpenVINO IR models for the ovms-engine snap components.
#
# Downloads two models:
#   1. person-detection-retail-0013 (Intel model zoo, 2-class person detection)
#   2. Faster R-CNN ResNet50 (Kaggle/TF2, 90-class COCO object detection)
#
# Prerequisites:
#   pip install openvino openvino-dev[tensorflow2] tensorflow
#
# Run from the repo root directory.

set -e

PERSON_DET_DIR="ovms-engine/components/model-person-detection/1"
FASTER_RCNN_DIR="ovms-engine/components/model-faster-rcnn/1"
TEMP_DIR="temp_model_download"

echo "=== Model Download and Conversion ==="
echo ""

mkdir -p "$PERSON_DET_DIR"
mkdir -p "$FASTER_RCNN_DIR"
mkdir -p "$TEMP_DIR"

# ─── Model 1: Person Detection (Intel Model Zoo) ────────────────────────────

echo "─── [1/2] Person Detection (person-detection-retail-0013) ───"
echo ""

PERSON_DET_URL="https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1/person-detection-retail-0013/FP32"

echo "Downloading model files..."
curl -L --progress-bar "$PERSON_DET_URL/person-detection-retail-0013.xml" -o "$PERSON_DET_DIR/saved_model.xml"
curl -L --progress-bar "$PERSON_DET_URL/person-detection-retail-0013.bin" -o "$PERSON_DET_DIR/saved_model.bin"

if [ -f "$PERSON_DET_DIR/saved_model.xml" ] && [ -f "$PERSON_DET_DIR/saved_model.bin" ]; then
    echo "  $PERSON_DET_DIR/saved_model.xml ($(du -h "$PERSON_DET_DIR/saved_model.xml" | cut -f1))"
    echo "  $PERSON_DET_DIR/saved_model.bin ($(du -h "$PERSON_DET_DIR/saved_model.bin" | cut -f1))"
    echo "  Done."
else
    echo "ERROR: Person detection model download failed."
    exit 1
fi

echo ""

# ─── Model 2: Faster R-CNN COCO (Kaggle TF2 → OpenVINO conversion) ──────────

echo "─── [2/2] Faster R-CNN ResNet50 COCO 90-class ───"
echo ""

if [ -f "$TEMP_DIR/saved_model.pb" ]; then
    echo "Using cached download in $TEMP_DIR/"
else
    echo "Step 1: Downloading from Kaggle..."
    curl -L --progress-bar \
        https://www.kaggle.com/api/v1/models/tensorflow/faster-rcnn-resnet-v1/tensorFlow2/faster-rcnn-resnet50-v1-640x640/1/download \
        -o "$TEMP_DIR/model.tar.gz"

    echo "Step 2: Extracting..."
    tar xzf "$TEMP_DIR/model.tar.gz" -C "$TEMP_DIR"
    rm -f "$TEMP_DIR/model.tar.gz"
fi

echo "Step 3: Converting to OpenVINO IR (fixed 640x640 input shape)..."
ovc "$TEMP_DIR" \
    --input "[1,640,640,3]" \
    --output_model "$FASTER_RCNN_DIR/saved_model"

if [ -f "$FASTER_RCNN_DIR/saved_model.xml" ] && [ -f "$FASTER_RCNN_DIR/saved_model.bin" ]; then
    echo "  $FASTER_RCNN_DIR/saved_model.xml ($(du -h "$FASTER_RCNN_DIR/saved_model.xml" | cut -f1))"
    echo "  $FASTER_RCNN_DIR/saved_model.bin ($(du -h "$FASTER_RCNN_DIR/saved_model.bin" | cut -f1))"
    echo "  Done."
else
    echo "ERROR: Faster R-CNN conversion failed."
    echo "Ensure openvino-dev is installed: pip install openvino-dev[tensorflow2] tensorflow"
    exit 1
fi

# ─── Clean up ────────────────────────────────────────────────────────────────

rm -rf "$TEMP_DIR"

echo ""
echo "=== All models ready ==="
echo ""
echo "Model components:"
echo "  ovms-engine/components/model-person-detection/"
echo "    manifest.json  - 2-class person detection, [1,3,320,544] NCHW, float32"
echo "    labels.txt     - background, person"
echo "    1/saved_model.xml + .bin"
echo ""
echo "  ovms-engine/components/model-faster-rcnn/"
echo "    manifest.json  - 90-class COCO detection, [1,640,640,3] NHWC, uint8"
echo "    labels.txt     - 91 COCO classes"
echo "    1/saved_model.xml + .bin"
echo ""
echo "Next: run 'snapcraft' in ovms-engine/ to build the snap with both model components."
