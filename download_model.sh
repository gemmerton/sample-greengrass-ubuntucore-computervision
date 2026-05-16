#!/bin/bash

# Download and prepare OpenVINO IR models for the ovms-engine snap components.
# Downloads Faster R-CNN (object detection) and prepares it in OpenVINO IR format
# for packaging as a snap component.

set -e

COMPONENT_DIR="ovms-engine/components/model-faster-rcnn"
TEMP_DIR="temp_model"

echo "Downloading Faster R-CNN model from Kaggle..."

# Create directories
mkdir -p "$COMPONENT_DIR"
mkdir -p "$TEMP_DIR"

# Download model
curl -L --create-dirs \
    https://www.kaggle.com/api/v1/models/tensorflow/faster-rcnn-resnet-v1/tensorFlow2/faster-rcnn-resnet50-v1-640x640/1/download \
    -o "$TEMP_DIR/model.tar.gz"

# Extract model
tar xzf "$TEMP_DIR/model.tar.gz" -C "$TEMP_DIR"

# Copy OpenVINO IR files to the snap component directory
# After conversion to IR format, the files are model.xml and model.bin
# For this demo, placeholder .xml/.bin files exist in the component directory.
# Replace them with actual converted IR files:
#
#   pip install openvino-dev
#   mo --saved_model_dir temp_model/saved_model --output_dir ovms-engine/components/model-faster-rcnn/
#
echo "Model downloaded to $TEMP_DIR/"
echo ""
echo "Next steps:"
echo "  1. Convert to OpenVINO IR format:"
echo "     mo --saved_model_dir $TEMP_DIR/saved_model --output_dir $COMPONENT_DIR/"
echo ""
echo "  2. Verify the component directory contains:"
echo "     $COMPONENT_DIR/model.xml"
echo "     $COMPONENT_DIR/model.bin"
echo "     $COMPONENT_DIR/manifest.json"
echo "     $COMPONENT_DIR/labels.txt"
echo "     $COMPONENT_DIR/component.yaml"

# Clean up
rm -rf "$TEMP_DIR"

echo ""
echo "Done."
