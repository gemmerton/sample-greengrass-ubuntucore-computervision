#!/bin/bash
set -e

# Setup a VLM inference snap on the Ubuntu Core edge device.
#
# The VLM runs as a separate inference snap (e.g. qwen-vl or gemma3) that exposes
# an OpenAI-compatible HTTP API. VlmHandler calls this API with camera snapshots.
#
# Usage:
#   1. SSH to the device
#   2. Install the VLM snap:
#        sudo snap install qwen-vl
#        # or: sudo snap install gemma3
#   3. Verify it's running:
#        curl http://localhost:9090/v1/models
#   4. Seed the VLM config in the shadow (run from your laptop):
#        ./scripts/prepare_vlm_model.sh
#
# This script seeds the shadow with default VLM prompts so VlmHandler starts
# generating risk assessments once the snap is available.

THING_NAME="ucore-kvs-3"
REGION="eu-west-1"
MODEL_NAME="qwen-vl"

echo "=== VLM Inference Snap Setup ==="
echo ""
echo "Step 1: Install the VLM snap on the device"
echo "  SSH to device and run:"
echo "    sudo snap install ${MODEL_NAME}"
echo "    curl http://localhost:9090/v1/models"
echo ""
echo "Step 2: Seed shadow config (running now)..."
echo ""

# Seed vlm_config with default prompts
aws iot-data update-thing-shadow \
  --thing-name "${THING_NAME}" \
  --shadow-name model-config \
  --region "${REGION}" \
  --cli-binary-format raw-in-base64-out \
  --payload '{
    "state": {
      "desired": {
        "vlm_config": {
          "system_prompt": "You are a workplace safety analyst. Analyse the image and return a JSON object with: risk_level (HIGH/MEDIUM/LOW/NONE), summary (one sentence), and risks (array of {description, severity, category}). Only return the JSON object, no other text.",
          "user_prompt": "Assess workplace safety risks visible in this scene.",
          "inference_interval": 15,
          "max_tokens": 256
        },
        "active_vlm_model": "'"${MODEL_NAME}"'"
      }
    }
  }' /dev/stdout 2>/dev/null | python3 -m json.tool

echo ""
echo "=== Done ==="
echo ""
echo "Once the snap is installed and responding on the device,"
echo "VlmHandler will start sending risk assessments to camera/vlm."
echo "Check the React dashboard VLM panel for results."
